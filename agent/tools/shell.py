"""Shell 命令执行工具（白名单 + 沙箱隔离）。"""

import config
from agent.sandbox import SandboxExecutor

# 模块级沙箱执行器，延迟初始化
_executor: SandboxExecutor | None = None


def _get_executor() -> SandboxExecutor:
    """获取或创建沙箱执行器（延迟初始化）。"""
    global _executor
    if _executor is None:
        _executor = SandboxExecutor(
            workspace_dir=config.WORKSPACE_DIR,
            enabled=config.SANDBOX_ENABLED,
        )
    return _executor


def run_command(command: str) -> str:
    """在工作目录中执行一条 shell 命令。

    安全机制：
    1. 命令白名单检查
    2. 沙箱隔离执行（macOS sandbox-exec）
    3. 超时控制 + 输出截断
    """
    cmd_name = command.strip().split()[0] if command.strip() else ""

    if cmd_name not in config.ALLOWED_COMMANDS:
        allowed = ", ".join(sorted(config.ALLOWED_COMMANDS))
        return f"🚫 命令 '{cmd_name}' 不在白名单中。允许: {allowed}"

    executor = _get_executor()
    result = executor.execute(
        command,
        timeout=config.COMMAND_TIMEOUT_SECONDS,
    )

    output = result.stdout
    if result.stderr:
        output += f"\n[stderr]\n{result.stderr}"
    if result.returncode != 0:
        output += f"\n[exit code: {result.returncode}]"
    if len(output) > config.MAX_COMMAND_OUTPUT_CHARS:
        output = output[: config.MAX_COMMAND_OUTPUT_CHARS] + "\n... (截断)"
    return output.strip() or "(无输出)"
