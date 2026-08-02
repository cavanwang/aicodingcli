"""Shell 命令执行工具（白名单限制）。"""

import subprocess
import config


def run_command(command: str) -> str:
    """在工作目录中执行一条 shell 命令。"""
    cmd_name = command.strip().split()[0] if command.strip() else ""

    if cmd_name not in config.ALLOWED_COMMANDS:
        allowed = ", ".join(sorted(config.ALLOWED_COMMANDS))
        return f"🚫 命令 '{cmd_name}' 不在白名单中。允许: {allowed}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=config.COMMAND_TIMEOUT_SECONDS,
            cwd=str(config.WORKSPACE_DIR),
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        if len(output) > config.MAX_COMMAND_OUTPUT_CHARS:
            output = output[: config.MAX_COMMAND_OUTPUT_CHARS] + "\n... (截断)"
        return output.strip() or "(无输出)"
    except subprocess.TimeoutExpired:
        return f"⏰ 命令超时 ({config.COMMAND_TIMEOUT_SECONDS}s)"
    except Exception as e:
        return f"执行失败: {e}"
