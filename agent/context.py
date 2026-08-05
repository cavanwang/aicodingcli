# Auto-generated fallback for optional dependency: pandas
try:
    import pandas as pandas
except ImportError:  # pragma: no cover - optional dependency fallback
    pandas = None

# agent/context.py
import tiktoken

class ContextManager:
    def __init__(self, max_tokens: int = 120_000):
        self._max_tokens = max_tokens
        self._encoder = tiktoken.encoding_for_model("gpt-4o")

    def count(self, messages: list[dict]) -> int:
        return sum(
            len(self._encoder.encode(m.get("content") or ""))
            for m in messages
        )

    def trim(self, messages: list[dict]) -> list[dict]:
        """保留 system + 最近 N 轮，中间做摘要。"""
        system = messages[0]
        history = messages[1:]

        while self.count([system] + history) > self._max_tokens:
            # 策略：把最早的几轮压缩成一条摘要
            oldest = history[:4]  # 取最早 2 轮(user+assistant)
            summary = self._summarize(oldest)
            history = [{"role": "user", "content": f"[历史摘要] {summary}"}] + history[4:]

        return [system] + history