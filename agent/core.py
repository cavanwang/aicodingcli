"""Agent 实体：封装 client、工具、记忆、流式循环。"""

import json
import time
from openai import OpenAI
from rich.console import Console

import config
from agent.logger import get_logger
from agent.recovery import RecoveryManager
from agent.task_planner import TaskPlanner
from agent.memory import CodeMemory
from agent.tools import TOOL_FUNCTIONS, TOOLS_SCHEMA, CONFIRM_TOOLS
from agent.tools.task_tools import set_planner
from agent.tools.memory_tools import set_memory
from agent.project import build_context
from agent.project_config import build_project_prompt
from agent.project_memory import build_project_memory_prompt
from agent.tracer import ExecutionTracer
from agent.usage import UsageTracker
from agent.todo import TodoList
from agent.tools.todo_tools import set_todo_list
from agent.mcp_manager import MCPManager, MCPServerConfig
from agent.mcp_tools import register_mcp_tools

console = Console()
logger = get_logger(__name__)


class Agent:
    """一个有记忆、有工具、支持流式输出的对话 Agent。"""

    def __init__(
        self,
        client: OpenAI,
        model: str,
        system_prompt: str,
        max_rounds: int = 10,
        confirm_fn=None,
        max_result_len: int | None = None,
        debug: bool = False,
    ):
        self._client = client
        self._model = model
        self._max_rounds = max_rounds
        self._confirm = confirm_fn
        self._debug = debug
        self._max_result_len = (
            max_result_len
            if max_result_len is not None
            else config.MAX_TOOL_RESULT_CHARS
        )
        self._messages: list[dict] = [{"role": "system", "content": system_prompt}]

        # 自愈管理器：接管重试控制、历史记录、回滚保护
        def _do_rollback() -> str:
            fn = TOOL_FUNCTIONS.get("git_rollback")
            return fn() if fn else "无可用回滚工具"

        self._recovery = RecoveryManager(
            max_attempts=3,
            rollback_fn=_do_rollback,
        )

        # 任务规划器
        self._planner = TaskPlanner()
        set_planner(self._planner)

        # 代码记忆
        self._memory = CodeMemory.load()
        # 启动时检测文件变更，清理过期记忆
        changes = self._memory.refresh_from_scan()
        if changes["deleted_files"] or changes["modified_files"]:
            logger.info(
                "记忆刷新: 新增=%d, 删除=%d, 修改=%d",
                len(changes["new_files"]),
                len(changes["deleted_files"]),
                len(changes["modified_files"]),
            )
            self._memory.save()
        set_memory(self._memory)

        # 执行轨迹记录器
        self._tracer = ExecutionTracer()

        # Token 用量跟踪器
        self._usage = UsageTracker()

        # Todo 列表
        self._todo = TodoList(session_id="current")
        self._todo.load()  # 尝试加载上次的 todo
        set_todo_list(self._todo)

        # MCP 客户端管理器
        self._mcp = MCPManager()

    @property
    def messages(self) -> list[dict]:
        return self._messages

    @property
    def tracer(self) -> ExecutionTracer:
        """获取执行轨迹记录器。"""
        return self._tracer

    @property
    def planner(self) -> TaskPlanner:
        """获取任务规划器。"""
        return self._planner

    @property
    def memory(self) -> CodeMemory:
        """获取代码记忆。"""
        return self._memory

    @property
    def usage(self) -> UsageTracker:
        """获取 Token 用量跟踪器。"""
        return self._usage

    @property
    def todo(self) -> TodoList:
        """获取 Todo 列表。"""
        return self._todo

    @property
    def mcp(self) -> MCPManager:
        """获取 MCP 客户端管理器。"""
        return self._mcp

    def init_mcp(self, server_configs: list[dict]) -> int:
        """初始化 MCP 连接，注册工具。返回注册的工具数。"""
        for cfg_dict in server_configs:
            self._mcp.add_server(MCPServerConfig(
                name=cfg_dict["name"],
                command=cfg_dict["command"],
                args=cfg_dict.get("args", []),
                env=cfg_dict.get("env"),
                cwd=cfg_dict.get("cwd"),
            ))

        tool_names = self._mcp.connect_all()
        if tool_names:
            count = register_mcp_tools(self._mcp)
            logger.info("MCP 工具已注册: %d 个 (%s)", count, ", ".join(tool_names))
            return count
        return 0

    def reset(self) -> None:
        """清空对话历史，只保留 system prompt。"""
        self._messages = [self._messages[0]]

    # ──────────────────────────────────────────────
    # 历史压缩
    # ──────────────────────────────────────────────

    def _find_compress_boundary(self, keep_recent: int) -> int:
        """找到安全的压缩边界索引，确保不拆分 tool_call/tool 对。

        返回：从该索引开始的消息可以被压缩（之前的消息将被替换为摘要）。
        边界保证：不会截断 assistant(tool_calls) 和对应的 tool(result)。
        """
        msgs = self._messages
        total = len(msgs)

        if total <= keep_recent + 1:
            return 0  # 消息太少，不需要压缩

        # 从后往前找安全边界：跳过 tool 消息及其对应的 assistant(tool_calls)
        boundary = total - keep_recent

        # 向前扫描，确保不会截断工具调用对
        while boundary > 1:  # 至少保留 system prompt
            msg = msgs[boundary]
            if msg["role"] == "tool":
                # 找到对应的 assistant(tool_calls) 消息，一起保留
                boundary -= 1
                while boundary > 1 and msgs[boundary]["role"] != "assistant":
                    boundary -= 1
                # 现在 boundary 指向 assistant(tool_calls)，再往前一位
                boundary -= 1
                continue
            elif msg["role"] == "assistant" and msg.get("tool_calls"):
                # assistant 有 tool_calls，检查后面的 tool 结果是否都在保留范围
                # 如果是，安全；如果不是，需要往前找
                next_idx = boundary + 1
                has_orphan_tool = False
                while next_idx < total and msgs[next_idx]["role"] == "tool":
                    if next_idx < total - keep_recent:
                        has_orphan_tool = True
                    next_idx += 1
                if has_orphan_tool:
                    boundary -= 1
                    continue
            break

        return max(1, boundary)  # 至少保留 system prompt (index 0)

    def _build_summary_text(self, messages_to_compress: list[dict]) -> str:
        """将旧消息构建为可读的摘要文本（本地截断摘要，作为 LLM 失败时的回退）。"""
        summary_parts = []
        user_msgs = [m for m in messages_to_compress if m["role"] == "user"]
        assistant_msgs = [m for m in messages_to_compress if m["role"] == "assistant"]
        tool_msgs = [m for m in messages_to_compress if m["role"] == "tool"]

        # 提取用户请求摘要
        for m in user_msgs:
            content = m.get("content", "")
            if content:
                summary_parts.append(f"用户请求: {content[:200]}")

        # 提取助手操作摘要
        tool_calls_summary = []
        for m in assistant_msgs:
            if m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    fn = tc.get("function", {})
                    name = fn.get("name", "unknown")
                    args_str = fn.get("arguments", "{}")
                    try:
                        args = json.loads(args_str)
                        # 提取关键参数
                        key_args = {k: str(v)[:50] for k, v in list(args.items())[:3]}
                        tool_calls_summary.append(f"{name}({key_args})")
                    except json.JSONDecodeError:
                        tool_calls_summary.append(name)
            # 纯文本回复
            content = m.get("content") or ""
            if content and not m.get("tool_calls"):
                summary_parts.append(f"助手回复: {content[:200]}")

        if tool_calls_summary:
            summary_parts.append(f"执行工具: {', '.join(tool_calls_summary[:20])}")

        # 工具结果摘要
        if tool_msgs:
            summary_parts.append(f"工具结果: {len(tool_msgs)} 条")

        return "\n".join(summary_parts) if summary_parts else "(无有效历史)"

    def _llm_summarize(self, messages_to_compress: list[dict]) -> str | None:
        """调用 LLM 生成智能摘要。失败时返回 None。"""
        try:
            # 构建待摘要的对话文本
            conversation_parts = []
            for m in messages_to_compress:
                role = m.get("role", "unknown")
                content = m.get("content", "") or ""
                if role == "user" and content:
                    conversation_parts.append(f"用户: {content[:500]}")
                elif role == "assistant":
                    if content and not m.get("tool_calls"):
                        conversation_parts.append(f"助手: {content[:500]}")
                    if m.get("tool_calls"):
                        for tc in m["tool_calls"]:
                            fn = tc.get("function", {})
                            name = fn.get("name", "unknown")
                            conversation_parts.append(f"助手调用工具: {name}")
                elif role == "tool":
                    tool_content = content[:300] if content else ""
                    conversation_parts.append(f"工具结果: {tool_content}")

            if not conversation_parts:
                return None

            conversation_text = "\n".join(conversation_parts)

            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个对话摘要助手。请将以下编程对话历史压缩为简洁的摘要。\n"
                            "要求：\n"
                            "1. 保留用户的核心需求和意图\n"
                            "2. 保留助手执行的关键操作和结果\n"
                            "3. 保留重要的技术决策和发现\n"
                            "4. 丢弃重复、冗余和细节性内容\n"
                            "5. 用中文输出，控制在 500 字以内\n"
                            "6. 直接输出摘要内容，不要加标题或前缀"
                        ),
                    },
                    {"role": "user", "content": f"请摘要以下对话历史：\n\n{conversation_text}"},
                ],
                max_tokens=800,
                temperature=0.3,
            )

            summary = response.choices[0].message.content
            if summary and len(summary.strip()) > 20:
                logger.info("LLM 智能摘要生成成功: %d 字符", len(summary))
                return summary.strip()
            return None
        except Exception as e:
            logger.warning("LLM 摘要生成失败，将回退到本地摘要: %s", e)
            return None

    def compress_history(self) -> bool:
        """压缩对话历史：将旧消息替换为 LLM 智能摘要（失败时回退到本地摘要）。

        返回 True 表示执行了压缩，False 表示不需要压缩。
        """
        threshold = config.COMPRESS_THRESHOLD
        keep_recent = config.COMPRESS_KEEP_RECENT

        if len(self._messages) <= threshold:
            return False

        boundary = self._find_compress_boundary(keep_recent)
        if boundary <= 1:
            return False  # 没有可压缩的消息

        # 提取需要压缩的消息（跳过 system prompt）
        to_compress = self._messages[1:boundary]
        if not to_compress:
            return False

        # 构建摘要：优先 LLM 智能摘要，失败回退到本地截断
        summary_text = self._llm_summarize(to_compress)
        if not summary_text:
            summary_text = self._build_summary_text(to_compress)
            logger.info("使用本地截断摘要")
        compressed_msg = {
            "role": "system",
            "content": (
                "[历史对话摘要]\n"
                "以下是之前对话的摘要，请参考：\n\n"
                f"{summary_text}\n\n"
                "[摘要结束]"
            ),
        }

        # 保留：system prompt + 摘要 + 最近的消息
        self._messages = [self._messages[0], compressed_msg] + self._messages[boundary:]

        logger.info(
            "历史压缩: %d 条消息压缩为摘要，保留最近 %d 条",
            len(to_compress),
            len(self._messages) - 2,
        )
        return True

    # ──────────────────────────────────────────────
    # 核心对话方法
    # ──────────────────────────────────────────────

    def chat(self, user_message: str) -> str:
        """处理一轮用户输入，流式输出，返回最终文本回复。"""
        self._messages.append({"role": "user", "content": user_message})
        logger.info("用户输入: %s", user_message[:100])

        # 进度上下文注入：将 TaskPlan + Todo 摘要注入 system prompt
        self._inject_progress_context()

        # 自动压缩：消息数超过阈值时压缩旧消息
        if self.compress_history():
            logger.info("对话历史已自动压缩")
            if self._debug:
                console.print(
                    f"  [dim]📦 历史已压缩，当前消息数: {len(self._messages)}[/]",
                    highlight=False,
                )

        logger.debug(
            "对话状态: tools=%d, messages=%d",
            len(TOOLS_SCHEMA), len(self._messages),
        )

        for round_idx in range(self._max_rounds):
            logger.debug("LLM 请求: round=%d, messages=%d", round_idx + 1, len(self._messages))
            self._tracer.record_round(round_idx + 1, len(self._messages))

            if self._debug:
                console.print(
                    f"\n  [dim]🔄 第 {round_idx + 1} 轮 | 消息数: {len(self._messages)}[/]",
                    highlight=False,
                )

            # 构建 API 请求参数
            request_kwargs = {
                "model": self._model,
                "messages": self._messages,
                "tools": TOOLS_SCHEMA,
                "tool_choice": "auto",
                "stream": True,
                "stream_options": {"include_usage": True},
            }

            # 思考模式（qwen-plus 支持思维链）
            if config.ENABLE_THINKING:
                request_kwargs["extra_body"] = {
                    "enable_thinking": True,
                    "thinking_budget": config.THINKING_BUDGET,
                }

            stream = self._client.chat.completions.create(**request_kwargs)

            content, tool_calls, usage = self._consume_stream(stream)

            # 记录 Token 用量
            if usage:
                self._usage.record_usage(
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                )

            assistant_msg = self._build_assistant_message(content, tool_calls)
            self._messages.append(assistant_msg)

            if tool_calls:
                self._execute_tools(tool_calls)
                continue

            console.print()  # 流式打印后换行
            return content

        logger.info("达到最大工具调用轮数 (%d)，停止执行", self._max_rounds)
        return "⚠️ 达到最大工具调用轮数，已停止。"

    # ──────────────────────────────────────────────
    # 流式消费
    # ──────────────────────────────────────────────

    def _consume_stream(self, stream) -> tuple[str, list[dict], dict | None]:
        """消费流式响应，实时打印文本，累积 tool_calls 片段，收集 usage。

        支持思考模式：reasoning_content 用暗色显示，不计入正式回复。
        """
        collected_content = ""
        thinking_content = ""
        tool_calls_map: dict[int, dict] = {}
        usage_data: dict | None = None
        in_thinking = False

        for chunk in stream:
            # 收集 usage 信息（通常在最后一个 chunk 中）
            if hasattr(chunk, 'usage') and chunk.usage:
                usage_data = {
                    "prompt_tokens": chunk.usage.prompt_tokens,
                    "completion_tokens": chunk.usage.completion_tokens,
                    "total_tokens": chunk.usage.total_tokens,
                }

            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # 思考内容（reasoning_content）：暗色显示
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                if not in_thinking:
                    console.print("\n  💭 ", end="", highlight=False)
                    in_thinking = True
                thinking_content += reasoning
                console.print(reasoning, end="", highlight=False, style="dim")

            # 文本片段：实时打印
            if delta.content:
                if in_thinking:
                    console.print()  # 思考结束换行
                    in_thinking = False
                collected_content += delta.content
                console.print(delta.content, end="", highlight=False)

            # 工具调用片段：累积
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        }
                    entry = tool_calls_map[idx]
                    if tc_delta.id:
                        entry["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            entry["name"] += tc_delta.function.name
                        if tc_delta.function.arguments:
                            entry["arguments"] += tc_delta.function.arguments

        tool_calls = (
            [tool_calls_map[i] for i in sorted(tool_calls_map.keys())]
            if tool_calls_map
            else []
        )

        return collected_content, tool_calls, usage_data

    # ──────────────────────────────────────────────
    # 构造完整 assistant message
    # ──────────────────────────────────────────────

    def _build_assistant_message(self, content: str, tool_calls: list[dict]) -> dict:
        msg: dict = {"role": "assistant", "content": content or None}
        if tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    },
                }
                for tc in tool_calls
            ]
        return msg

    # ──────────────────────────────────────────────
    # 工具执行
    # ──────────────────────────────────────────────

    def _execute_tools(self, tool_calls: list[dict]) -> None:
        for tc in tool_calls:
            func_name = tc["name"]
            func_args = json.loads(tc["arguments"])

            console.print(
                f"\n  🔧 [bold cyan]{func_name}[/]({func_args})",
                highlight=False,
            )
            logger.info("工具调用: %s(%s)", func_name, func_args)
            self._usage.record_tool_call()

            if self._debug:
                console.print(
                    f"  [dim]📎 参数详情: {json.dumps(func_args, ensure_ascii=False, indent=2)}[/]",
                    highlight=False,
                )

            # 用户确认：查注册表，不 hardcode 工具名
            if self._confirm and func_name in CONFIRM_TOOLS:
                if not self._confirm(func_name, func_args):
                    logger.info("用户拒绝操作: %s", func_name)
                    self._tracer.record_user_rejected(func_name)
                    self._append_tool_result(tc["id"], "⛔ 用户拒绝了该操作")
                    continue

            # 执行
            func = TOOL_FUNCTIONS.get(func_name)
            if func is None:
                result = f"未知工具: {func_name}"
                logger.warning("未知工具: %s", func_name)
                self._tracer.record_tool_call(func_name, func_args, result, 0, success=False)
            else:
                start_time = time.time()
                try:
                    if func_name in {
                        "edit_file",
                        "write_file",
                        "run_command",
                    } and func_name not in {
                        "git_checkpoint",
                        "git_rollback",
                    }:
                        checkpoint_func = TOOL_FUNCTIONS.get("git_checkpoint")
                        if checkpoint_func is not None:
                            checkpoint_result = checkpoint_func(
                                message="before-tool-change"
                            )
                            console.print(
                                f"  📝 [yellow]{checkpoint_result}[/]",
                                highlight=False,
                            )

                    result = func(**func_args)
                    duration_ms = (time.time() - start_time) * 1000
                    self._tracer.record_tool_call(func_name, func_args, result, duration_ms, success=True)
                except PermissionError as e:
                    result = f"🚫 权限错误: {e}"
                    duration_ms = (time.time() - start_time) * 1000
                    logger.warning("权限错误: %s - %s", func_name, e)
                    self._tracer.record_tool_call(func_name, func_args, result, duration_ms, success=False)
                    # 失败信息传递到 Todo
                    self._attach_error_to_current_todo(f"{func_name}: {e}")
                except Exception as e:
                    result = f"❌ 执行出错: {e}"
                    duration_ms = (time.time() - start_time) * 1000
                    logger.error("工具执行异常: %s - %s", func_name, e, exc_info=True)
                    self._tracer.record_tool_call(func_name, func_args, result, duration_ms, success=False)
                    # 失败信息传递到 Todo
                    self._attach_error_to_current_todo(f"{func_name}: {e}")

            # ── 错误自愈：run_command 失败时进入修复循环 ──
            if func_name == "run_command" and RecoveryManager.is_failure(result):
                action = self._recovery.handle_failure(func_name, result)
                recovery_prompt = action["recovery_prompt"]
                logger.warning(
                    "命令执行失败，触发自愈 (attempt=%d/%d, error_type=%s): %s",
                    self._recovery.attempts, self._recovery.max_attempts,
                    action["classification"]["error_type"],
                    result[:200],
                )
                self._tracer.record_recovery(
                    func_name,
                    action["classification"]["error_type"],
                    action["classification"],
                    self._recovery.attempts,
                    self._recovery.max_attempts,
                    action["exhausted"],
                )

                if action["exhausted"]:
                    logger.warning(
                        "自愈达到上限 (%d 次)，执行自动回滚",
                        self._recovery.max_attempts,
                    )
                    self._tracer.record_rollback(func_name, action["rollback_result"])
                    console.print(
                        f"  🔙 [yellow]自动回滚: {action['rollback_result']}[/]",
                        highlight=False,
                    )
                console.print(f"  🛠️ [magenta]{recovery_prompt}[/]", highlight=False)
                self._append_tool_result(
                    tc["id"], f"{result}\n\n[error_recovery]\n{recovery_prompt}"
                )

                if not action["exhausted"]:
                    self._messages.append(
                        {
                            "role": "system",
                            "content": RecoveryManager.build_retry_guidance(),
                        }
                    )
                continue

            # 在 _execute_tools 中，结果太长时截断
            if len(result) > self._max_result_len:
                result = result[: self._max_result_len] + (
                    f"\n... (共 {len(result)} 字符，已截断)"
                )

            # 打印摘要
            display = result[:200] + "..." if len(result) > 200 else result
            console.print(f"  📋 [green]{display}[/]", highlight=False)

            if self._debug:
                console.print(
                    f"  [dim]📄 结果长度: {len(result)} 字符[/]",
                    highlight=False,
                )
                logger.debug("工具结果 [%s]: %s", func_name, result[:500])

            self._append_tool_result(tc["id"], result)

    def _append_tool_result(self, tool_call_id: str, result: str) -> None:
        self._messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result,
            }
        )

    # ──────────────────────────────────────────────
    # 进度上下文注入 + 失败信息传递
    # ──────────────────────────────────────────────

    def _inject_progress_context(self) -> None:
        """将 TaskPlan + Todo 进度摘要注入 system prompt。"""
        parts = []

        # TaskPlan 进度
        if self._planner.current_plan is not None:
            plan = self._planner.current_plan
            if plan.status not in ("completed", "failed"):
                total = len(plan.subtasks)
                done = sum(1 for s in plan.subtasks if s.status == "done")
                parts.append(f"📋 当前计划: {done}/{total} 完成")

        # Todo 进度
        todo_line = self._todo.progress_line()
        if todo_line:
            parts.append(todo_line)

        if parts:
            progress_msg = " | ".join(parts)
            self._messages.append({
                "role": "system",
                "content": f"[进度感知] {progress_msg}",
            })
            logger.debug("进度注入: %s", progress_msg)

    def _attach_error_to_current_todo(self, error: str) -> None:
        """将错误信息附加到当前进行中的 Todo 项。"""
        current = self._todo.get_current()
        if current is not None:
            self._todo.set_error(current.id, error)
            logger.info("错误已附加到 Todo [%d]: %s", current.id, error[:100])


# ──────────────────────────────────────────────────
# 工厂函数
# ──────────────────────────────────────────────────


def create_agent(confirm_fn=None, debug: bool = False) -> Agent:
    """读取配置，创建并返回一个就绪的 Agent 实例。"""
    config.validate()

    client = OpenAI(
        api_key=config.API_KEY,
        base_url=config.BASE_URL,
    )

    # 构建 system prompt：基础 + 项目上下文 + 项目配置 + 项目记忆
    project_prompt = build_project_prompt(config.WORKSPACE_DIR)
    system_prompt = config.SYSTEM_PROMPT + "\n\n" + build_context()
    if project_prompt:
        system_prompt += "\n\n" + project_prompt

    # 加载项目记忆（跨会话持久化）
    memory_prompt = build_project_memory_prompt(config.WORKSPACE_DIR)
    if memory_prompt:
        system_prompt += "\n\n" + memory_prompt

    agent = Agent(
        client=client,
        model=config.MODEL_NAME,
        system_prompt=system_prompt,
        max_rounds=config.MAX_TOOL_ROUNDS,
        confirm_fn=confirm_fn,
        max_result_len=config.MAX_TOOL_RESULT_CHARS,
        debug=debug,
    )

    # 初始化 MCP 连接（如果有配置）
    if config.MCP_SERVERS:
        mcp_count = agent.init_mcp(config.MCP_SERVERS)
        if mcp_count > 0:
            console.print(
                f"  🔌 [cyan]MCP 已连接: {mcp_count} 个外部工具[/]",
                highlight=False,
            )

    return agent
