"""Git 操作工具。"""

import subprocess
import config


def _git(args: str) -> str:
    try:
        result = subprocess.run(
            f"git {args}",
            shell=True, capture_output=True, text=True,
            timeout=15, cwd=str(config.WORKSPACE_DIR),
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > config.MAX_COMMAND_OUTPUT_CHARS:
            output = output[:config.MAX_COMMAND_OUTPUT_CHARS] + "\n...(截断)"
        return output or "(无输出)"
    except Exception as e:
        return f"git 执行失败: {e}"


def git_diff() -> str:
    """查看当前未提交的改动。"""
    return _git("diff")


def git_log(count: int = 10) -> str:
    """查看最近 N 条提交记录。"""
    return _git(f"log --oneline -{count}")


def git_status() -> str:
    """查看工作区状态。"""
    return _git("status --short")