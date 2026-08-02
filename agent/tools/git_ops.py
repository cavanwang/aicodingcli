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


def git_checkpoint(message: str = "auto-checkpoint") -> str:
    """自动提交当前状态，作为回滚点。"""
    _git("add -A")
    result = _git(f'commit -m "[agent] {message}" --allow-empty')
    if "nothing to commit" in result:
        return "(无变更，跳过 checkpoint)"
    return f"✅ checkpoint 已创建: {message}"


def git_rollback() -> str:
    """回滚到上一个 checkpoint（丢弃工作区改动）。"""
    # 先确认有上一个提交
    log = _git("log --oneline -2")
    if log.count("\n") < 1:
        return "❌ 没有可回滚的历史提交"

    _git("checkout HEAD~1 -- .")
    _git("add -A")
    _git('commit -m "[agent] rollback" --allow-empty')
    return "✅ 已回滚到上一个 checkpoint"
