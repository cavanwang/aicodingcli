"""错误自愈管理器：封装重试控制、历史记录、回滚保护。

将原 core.py 中散落的自愈逻辑统一收敛到此模块，
使 Agent 核心循环更清晰，也便于后续扩展。
"""

from __future__ import annotations

from typing import Any, Callable

from agent.error_recovery import classify_error, build_recovery_prompt


# 判断命令输出是否包含失败信号的关键词
_FAILURE_KEYWORDS = ("失败", "错误", "exit code", "超时")


class RecoveryManager:
    """管理错误自愈循环的状态与行为。"""

    def __init__(
        self,
        max_attempts: int = 3,
        rollback_fn: Callable[[], str] | None = None,
    ) -> None:
        self._max_attempts = max_attempts
        self._attempts: int = 0
        self._history: list[dict[str, Any]] = []
        self._rollback_fn = rollback_fn

    # ──────────────────────────────────────────────
    # 状态查询
    # ──────────────────────────────────────────────

    @property
    def attempts(self) -> int:
        return self._attempts

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    @property
    def exhausted(self) -> bool:
        """是否已达到最大重试次数。"""
        return self._attempts >= self._max_attempts

    def reset(self) -> None:
        """重置自愈状态（新任务开始时调用）。"""
        self._attempts = 0
        self._history.clear()

    # ──────────────────────────────────────────────
    # 核心判断
    # ──────────────────────────────────────────────

    @staticmethod
    def is_failure(result: str) -> bool:
        """判断命令输出是否包含失败信号。"""
        if not isinstance(result, str):
            return False
        return any(kw in result for kw in _FAILURE_KEYWORDS)

    # ──────────────────────────────────────────────
    # 处理失败
    # ──────────────────────────────────────────────

    def handle_failure(
        self,
        tool_name: str,
        result: str,
    ) -> dict[str, Any]:
        """处理一次工具执行失败，返回自愈动作描述。

        返回 dict 包含:
        - exhausted: bool  是否已耗尽
        - classification: dict  错误分类结果
        - recovery_prompt: str  给模型的修复提示
        - rollback_result: str  回滚结果（仅 exhausted 时）
        """
        self._attempts += 1

        # 用 classify_error 做完整分类
        classification = classify_error(result)

        # 补充简要摘要到历史
        summary = classification.get("summary", "命令执行失败")
        if "exit code" in result.lower():
            summary = "命令返回非零退出码"
        elif "超时" in result:
            summary = "命令执行超时"
        self._history.append({
            "error_type": classification["error_type"],
            "summary": summary,
        })

        if self.exhausted:
            # 达到上限：自动回滚
            rollback_result = ""
            if self._rollback_fn is not None:
                rollback_result = self._rollback_fn()

            recovery_prompt = (
                "错误自愈：已达到最大重试次数，已自动回滚到修改前状态。"
                f"回滚结果: {rollback_result}\n"
                f"请停止继续重试，并总结当前失败原因。\n原始输出:\n{result}"
            )
            return {
                "exhausted": True,
                "classification": classification,
                "recovery_prompt": recovery_prompt,
                "rollback_result": rollback_result,
            }

        # 未达上限：生成修复提示
        recovery_prompt = build_recovery_prompt(
            tool_name,
            result,
            history=self._history,
            attempt_number=self._attempts,
            max_attempts=self._max_attempts,
        )
        return {
            "exhausted": False,
            "classification": classification,
            "recovery_prompt": recovery_prompt,
            "rollback_result": "",
        }

    # ──────────────────────────────────────────────
    # 生成重试引导消息
    # ──────────────────────────────────────────────

    @staticmethod
    def build_retry_guidance() -> str:
        """返回注入 messages 的系统引导消息，提示 Agent 继续自愈。"""
        return (
            "请继续推进错误自愈："
            "基于上一次失败输出，先分析原因，随后进行最小修复，"
            "最后重新执行验证。"
            "请在下一轮中优先再次执行原始命令以验证修复是否生效。"
        )
