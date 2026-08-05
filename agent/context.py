"""上下文预算管理（Phase 11 任务 D2）。

职责：
- 轻量 token 估算（不依赖 tiktoken：混合文本按 ~1.8 字符/token 估算）
- 判断消息历史是否超出上下文预算，供 Agent 主循环触发强制压缩/截断
"""

from __future__ import annotations

import json


def estimate_text_tokens(text: str) -> int:
    """估算单段文本的 token 数。

    经验值：中英混合文本约 1.8 字符/token，取上整保证偏保守（宁可早压缩）。
    """
    if not text:
        return 0
    return max(1, int(len(text) / 1.8) + 1)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算消息列表的总 token 数（含 content 与 tool_calls 序列化开销）。"""
    total = 0
    for m in messages:
        total += estimate_text_tokens(m.get("content") or "")
        tool_calls = m.get("tool_calls")
        if tool_calls:
            total += estimate_text_tokens(json.dumps(tool_calls, ensure_ascii=False))
        total += 4  # 每条消息的角色/分隔开销
    return total


class ContextBudget:
    """上下文预算检查器。"""

    def __init__(self, max_tokens: int, ratio: float = 0.8):
        self.max_tokens = max_tokens
        self.ratio = ratio

    @property
    def threshold(self) -> int:
        """触发预算控制的 token 阈值（max_tokens * ratio）。"""
        return int(self.max_tokens * self.ratio)

    def is_over_budget(self, messages: list[dict]) -> bool:
        return estimate_messages_tokens(messages) > self.threshold

    def report(self, messages: list[dict]) -> str:
        used = estimate_messages_tokens(messages)
        return f"{used}/{self.max_tokens} tokens（阈值 {self.threshold}）"
