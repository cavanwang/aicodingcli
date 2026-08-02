"""Agent 实体：封装 client、工具、记忆、流式循环。"""

import json
from openai import OpenAI
from rich.console import Console

import config
from agent.recovery import RecoveryManager
from agent.tools import TOOL_FUNCTIONS, TOOLS_SCHEMA, CONFIRM_TOOLS
from agent.project import build_context

console = Console()


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
    ):
        self._client = client
        self._model = model
        self._max_rounds = max_rounds
        self._confirm = confirm_fn
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

    @property
    def messages(self) -> list[dict]:
        return self._messages

    def reset(self) -> None:
        """清空对话历史，只保留 system prompt。"""
        self._messages = [self._messages[0]]

    # ──────────────────────────────────────────────
    # 核心对话方法
    # ──────────────────────────────────────────────

    def chat(self, user_message: str) -> str:
        """处理一轮用户输入，流式输出，返回最终文本回复。"""
        self._messages.append({"role": "user", "content": user_message})

        # ===== DEBUG START =====
        print(f"\n[DEBUG] TOOLS_SCHEMA 数量: {len(TOOLS_SCHEMA)}")
        print(
            f"[DEBUG] 第一个工具: {TOOLS_SCHEMA[0]['function']['name'] if TOOLS_SCHEMA else '空!'}"
        )
        print(f"[DEBUG] messages 数量: {len(self._messages)}")
        print(f"[DEBUG] system prompt 前100字: {self._messages[0]['content'][:100]}")
        # ===== DEBUG END =====

        for _ in range(self._max_rounds):
            stream = self._client.chat.completions.create(
                model=self._model,
                messages=self._messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
                stream=True,
            )

            content, tool_calls = self._consume_stream(stream)

            assistant_msg = self._build_assistant_message(content, tool_calls)
            self._messages.append(assistant_msg)

            if tool_calls:
                self._execute_tools(tool_calls)
                continue

            console.print()  # 流式打印后换行
            return content

        return "⚠️ 达到最大工具调用轮数，已停止。"

    # ──────────────────────────────────────────────
    # 流式消费
    # ──────────────────────────────────────────────

    def _consume_stream(self, stream) -> tuple[str, list[dict]]:
        """消费流式响应，实时打印文本，累积 tool_calls 片段。"""
        collected_content = ""
        tool_calls_map: dict[int, dict] = {}

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # 文本片段：实时打印
            if delta.content:
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

        return collected_content, tool_calls

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

            # 用户确认：查注册表，不 hardcode 工具名
            if self._confirm and func_name in CONFIRM_TOOLS:
                if not self._confirm(func_name, func_args):
                    self._append_tool_result(tc["id"], "⛔ 用户拒绝了该操作")
                    continue

            # 执行
            func = TOOL_FUNCTIONS.get(func_name)
            if func is None:
                result = f"未知工具: {func_name}"
            else:
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
                except PermissionError as e:
                    result = f"🚫 权限错误: {e}"
                except Exception as e:
                    result = f"❌ 执行出错: {e}"

            # ── 错误自愈：run_command 失败时进入修复循环 ──
            if func_name == "run_command" and RecoveryManager.is_failure(result):
                action = self._recovery.handle_failure(func_name, result)
                recovery_prompt = action["recovery_prompt"]

                if action["exhausted"]:
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

            self._append_tool_result(tc["id"], result)

    def _append_tool_result(self, tool_call_id: str, result: str) -> None:
        self._messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result,
            }
        )


# ──────────────────────────────────────────────────
# 工厂函数
# ──────────────────────────────────────────────────


def create_agent(confirm_fn=None) -> Agent:
    """读取配置，创建并返回一个就绪的 Agent 实例。"""
    config.validate()

    client = OpenAI(
        api_key=config.API_KEY,
        base_url=config.BASE_URL,
    )

    return Agent(
        client=client,
        model=config.MODEL_NAME,
        system_prompt=config.SYSTEM_PROMPT + "\n\n" + build_context(),
        max_rounds=config.MAX_TOOL_ROUNDS,
        confirm_fn=confirm_fn,
        max_result_len=config.MAX_TOOL_RESULT_CHARS,
    )
