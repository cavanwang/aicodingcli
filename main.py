"""qcoder-cli 入口：支持子命令 + --server 模式。"""

import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import threading
import queue as queue_mod

from cli import run as run_repl
from agent.logger import get_logger

logger = get_logger(__name__)


def cmd_usage(args) -> None:
    """查看历史 Token 用量。"""
    from agent.usage import UsageTracker

    history = UsageTracker.load_history(days=args.days)
    print(UsageTracker.format_history(history))


def cmd_rollback(args) -> None:
    """回滚到上一个 checkpoint。"""
    import config

    workspace = str(config.WORKSPACE_DIR)

    # 列出最近 checkpoint
    result = subprocess.run(
        'git log --grep="checkpoint" --oneline -5',
        shell=True, capture_output=True, text=True, cwd=workspace,
    )
    checkpoints = result.stdout.strip()

    if not checkpoints:
        print("❌ 未找到 checkpoint 提交")
        sys.exit(1)

    print("📝 最近 checkpoint:")
    for line in checkpoints.split("\n"):
        print(f"  {line}")
    print()

    if not args.yes:
        answer = input("确认回滚到上一个 checkpoint？[y/N] > ").strip().lower()
        if answer != "y":
            print("已取消")
            return

    # 执行回滚
    rollback_result = subprocess.run(
        "git reset --hard HEAD~1",
        shell=True, capture_output=True, text=True, cwd=workspace,
    )

    if rollback_result.returncode == 0:
        print("✅ 已回滚到上一个 checkpoint")
    else:
        print(f"❌ 回滚失败: {rollback_result.stderr}")
        sys.exit(1)


def run_server(workspace: str | None = None) -> None:
    """JSON Lines 服务模式：从 stdin 读消息，往 stdout 写回复。

    协议：
    - 输入: {"type": "chat", "message": "..."}
              {"type": "confirm_reply", "approved": true}
    - 输出: {"type": "text", "content": "..."}
              {"type": "tool", "name": "...", "args": {...}}
              {"type": "memory_confirm", "section": "...", "content": "..."}
              {"type": "done", "reply": "..."}
              {"type": "error", "message": "..."}
    """
    # ── 记忆保存确认机制（线程安全）──
    # 当 save_memory 的 source="chat" 时，需要用户确认
    _confirm_event = threading.Event()
    _confirm_approved = False

    def _server_confirm_fn(name: str, args: dict) -> bool:
        """Server 模式的确认函数：save_memory(source=chat) 时暂停等待用户确认。"""
        nonlocal _confirm_approved
        if name == "save_memory" and args.get("source", "chat") == "chat":
            # 发送确认请求给前端
            _emit({
                "type": "memory_confirm",
                "section": args.get("section", "(根)"),
                "content": args.get("content", ""),
                "action": args.get("action", "save"),
            })
            # 等待前端回复 confirm_reply
            _confirm_event.clear()
            _confirm_event.wait(timeout=120)  # 最多等 2 分钟
            return _confirm_approved
        # 其他工具自动批准
        return True
    # 设置工作目录
    if workspace:
        os.environ["WORKSPACE_DIR"] = workspace
        # 重新加载 config 以应用新的工作目录
        import importlib
        import config
        importlib.reload(config)

    # 创建 Agent（server 模式自动确认所有操作）
    from agent import create_agent
    logger.info("[Server] 启动: workspace=%s", workspace or ".")
    agent = create_agent(confirm_fn=_server_confirm_fn, debug=False)

    # 发送就绪消息
    _emit({"type": "ready", "model": agent._model, "workspace": workspace or "."})
    logger.info("[Server] 就绪: model=%s", agent._model)

    # ── 后台 stdin 读取线程 ──
    # 解决 agent.chat() 阻塞时无法读取 confirm_reply 的问题
    _msg_queue = queue_mod.Queue()

    def _stdin_reader():
        """后台线程：持续读取 stdin，confirm_reply 直接处理，其他消息放入队列。"""
        nonlocal _confirm_approved
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning("[Server] JSON 解析失败: %s — %s", line[:100], e)
                _emit({"type": "error", "message": f"JSON 解析失败: {e}"})
                continue

            msg_type = msg.get("type", "")
            if msg_type == "confirm_reply":
                # 直接处理确认回复
                _confirm_approved = msg.get("approved", False)
                _confirm_event.set()
                logger.info("[Server] 收到确认回复: approved=%s", _confirm_approved)
            else:
                _msg_queue.put(msg)
        # stdin 耗尽，发送退出信号
        _msg_queue.put(None)

    _stdin_thread = threading.Thread(target=_stdin_reader, daemon=True)
    _stdin_thread.start()

    # 主循环：从队列读消息
    while True:
        try:
            msg = _msg_queue.get()
            if msg is None:  # stdin 耗尽
                break
        except (EOFError, KeyboardInterrupt):
            break

        msg_type = msg.get("type", "")
        logger.debug("[Server] 收到消息: type=%s", msg_type)

        if msg_type == "chat":
            raw_message = msg.get("message", "")
            user_message = _build_message(msg)
            if not user_message.strip():
                _emit({"type": "error", "message": "消息内容为空"})
                continue

            logger.info("[Server] chat: %s", user_message[:200])

            # Slash 命令本地处理，不经过 LLM
            if raw_message.strip().startswith("/"):
                try:
                    from cli.commands import dispatch_command
                    # 捕获 Console 输出
                    output_buf = io.StringIO()
                    with contextlib.redirect_stdout(output_buf), contextlib.redirect_stderr(output_buf):
                        should_continue = dispatch_command(raw_message.strip(), agent)
                    reply = output_buf.getvalue().strip()
                    if not reply:
                        reply = "✅ 命令已执行"
                    _emit({"type": "done", "reply": reply})
                    logger.info("[Server] slash 命令完成: %d 字符", len(reply))
                except Exception as e:
                    logger.error("[Server] 命令执行异常: %s", e, exc_info=True)
                    _emit({"type": "error", "message": f"命令执行出错: {e}"})
                continue

            try:
                reply = agent.chat(user_message)
                _emit({"type": "done", "reply": reply})
                logger.info("[Server] done: %d 字符", len(reply))
            except Exception as e:
                logger.error("[Server] chat 异常: %s", e, exc_info=True)
                _emit({"type": "error", "message": f"执行出错: {e}"})

        elif msg_type == "ping":
            _emit({"type": "pong"})

        elif msg_type == "quit":
            logger.info("[Server] 收到 quit，保存状态...")
            # 保存会话历史
            if len(agent._messages) > 1:
                from agent.session import save_session
                session_path = save_session(agent)
                logger.info("[Server] 会话已保存: %s", session_path.name)
            # 保存状态
            if agent.tracer.event_count > 0:
                agent.tracer.save()
            if agent.memory.file_count > 0:
                agent.memory.save()
            if agent.planner.current_plan is not None:
                agent.planner.save()
            if agent.usage.session.api_calls > 0:
                agent.usage.save()
            _emit({"type": "bye"})
            logger.info("[Server] 已退出")
            break

        else:
            _emit({"type": "error", "message": f"未知消息类型: {msg_type}"})


def _build_message(msg: dict) -> str:
    """将 chat 消息 + 编辑器上下文 + @file 引用组装为最终用户消息。"""
    user_message = msg.get("message", "")
    parts: list[str] = []

    # 编辑器上下文：当前文件 + 选区
    active_file = msg.get("activeFile", "")
    selection = msg.get("selection", "")
    if active_file:
        parts.append(f"[当前编辑文件: {active_file}]")
    if selection:
        parts.append(f"[选中内容]:\n{selection}")

    # @file 引用：将 @file:path 替换为文件内容
    workspace = os.environ.get("WORKSPACE_DIR", ".")

    def _replace_at_file(match: re.Match) -> str:
        filepath = match.group(1)
        # 支持绝对路径和相对路径
        if os.path.isabs(filepath):
            full_path = filepath
        else:
            full_path = os.path.join(workspace, filepath)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            return f"[文件 {filepath} 的内容]:\n```\n{content}\n```"
        except Exception as e:
            return f"[无法读取文件 {filepath}: {e}]"

    user_message = re.sub(r"@file:(\S+)", _replace_at_file, user_message)

    if parts:
        return "\n".join(parts) + "\n\n" + user_message
    return user_message


def _emit(msg: dict) -> None:
    """向 stdout 输出一条 JSON 消息（自动刷新缓冲区）。"""
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    """主入口：解析子命令并分发。"""
    parser = argparse.ArgumentParser(
        prog="qcoder-cli",
        description="qcoder-cli AI 编程助手",
    )
    parser.add_argument(
        "--server", action="store_true",
        help="以 JSON Lines 服务模式运行（供 VS Code 扩展调用）",
    )
    parser.add_argument(
        "--workspace", type=str, default=None,
        help="工作目录路径（--server 模式下使用）",
    )
    subparsers = parser.add_subparsers(dest="command")

    # usage 子命令
    usage_parser = subparsers.add_parser("usage", help="查看历史 Token 用量")
    usage_parser.add_argument(
        "--days", type=int, default=7,
        help="查看最近 N 天的用量（默认 7）",
    )

    # rollback 子命令
    rollback_parser = subparsers.add_parser("rollback", help="回滚到上一个 checkpoint")
    rollback_parser.add_argument(
        "--yes", "-y", action="store_true",
        help="跳过确认提示",
    )

    args = parser.parse_args()

    # --server 模式：JSON Lines 服务循环
    if args.server:
        run_server(workspace=args.workspace)
        return

    if args.command == "usage":
        cmd_usage(args)
    elif args.command == "rollback":
        cmd_rollback(args)
    else:
        # 无子命令时启动 REPL
        run_repl()


if __name__ == "__main__":
    main()
