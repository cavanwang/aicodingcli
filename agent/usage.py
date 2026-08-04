"""Token 用量统计与持久化。

存储位置：~/.aicoding/usage/{date}.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path

from agent.logger import get_logger

logger = get_logger(__name__)

USAGE_DIR = Path.home() / ".aicoding" / "usage"

# 模型价格表（美元 / 百万 token）
# 格式: {模型名: (input_price, output_price)}
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-haiku": (0.25, 1.25),
    "claude-3-opus": (15.00, 75.00),
    "qwen-plus": (0.80, 2.00),
    "qwen-turbo": (0.30, 0.60),
    "qwen-max": (2.00, 6.00),
    "deepseek-chat": (0.14, 0.28),
    "deepseek-coder": (0.14, 0.28),
}


@dataclass
class UsageStats:
    """单次会话的 Token 用量统计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    api_calls: int = 0
    tool_calls: int = 0
    started_at: str = ""
    last_updated: str = ""

    def record(self, prompt_tokens: int, completion_tokens: int, total_tokens: int) -> None:
        """记录一次 API 调用的用量。"""
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += total_tokens
        self.api_calls += 1
        self.last_updated = datetime.now().isoformat()

    def record_tool_call(self) -> None:
        """记录一次工具调用。"""
        self.tool_calls += 1

    def summary(self, model_name: str = "") -> str:
        """返回格式化的用量摘要。"""
        if self.api_calls == 0:
            return "本次会话无 API 调用"

        lines = [
            f"📊 Token 用量统计",
            f"  API 调用: {self.api_calls} 次",
            f"  工具调用: {self.tool_calls} 次",
            f"  输入 Token: {self.prompt_tokens:,}",
            f"  输出 Token: {self.completion_tokens:,}",
            f"  总计 Token: {self.total_tokens:,}",
        ]

        cost = self.estimated_cost(model_name)
        if cost > 0:
            lines.append(f"  💰 费用估算: ${cost:.4f}")

        return "\n".join(lines)

    def estimated_cost(self, model_name: str = "") -> float:
        """估算本次会话的费用（美元）。

        Args:
            model_name: 模型名称，用于查找价格表

        Returns:
            估算费用（美元），找不到价格时返回 0.0
        """
        prices = MODEL_PRICES.get(model_name)
        if prices is None:
            # 尝试模糊匹配
            for key, p in MODEL_PRICES.items():
                if key in model_name or model_name in key:
                    prices = p
                    break
        if prices is None:
            return 0.0

        input_price, output_price = prices
        cost = (self.prompt_tokens / 1_000_000 * input_price +
                self.completion_tokens / 1_000_000 * output_price)
        return cost

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> UsageStats:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class UsageTracker:
    """Token 用量跟踪器，支持会话级统计和历史持久化。"""

    def __init__(self) -> None:
        self._session = UsageStats(started_at=datetime.now().isoformat())

    @property
    def session(self) -> UsageStats:
        return self._session

    def record_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None:
        """记录一次 API 调用的 Token 用量。"""
        self._session.record(prompt_tokens, completion_tokens, total_tokens)

    def record_tool_call(self) -> None:
        """记录一次工具调用。"""
        self._session.record_tool_call()

    def summary(self, model_name: str = "") -> str:
        """返回当前会话的用量摘要。"""
        return self._session.summary(model_name=model_name)

    def save(self) -> Path | None:
        """保存当前会话用量到磁盘。"""
        if self._session.api_calls == 0:
            return None

        USAGE_DIR.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        path = USAGE_DIR / f"{today}.json"

        # 如果今天已有记录，累加
        existing = self._load_file(path)
        if existing:
            merged = self._merge(existing, self._session)
        else:
            merged = self._session.to_dict()

        path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Token 用量已保存: %s", path)
        return path

    def _load_file(self, path: Path) -> dict | None:
        """加载已有的日用量文件。"""
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _merge(self, existing: dict, new_session: UsageStats) -> dict:
        """合并已有记录和当前会话。"""
        return {
            "prompt_tokens": existing.get("prompt_tokens", 0) + new_session.prompt_tokens,
            "completion_tokens": existing.get("completion_tokens", 0) + new_session.completion_tokens,
            "total_tokens": existing.get("total_tokens", 0) + new_session.total_tokens,
            "api_calls": existing.get("api_calls", 0) + new_session.api_calls,
            "tool_calls": existing.get("tool_calls", 0) + new_session.tool_calls,
            "started_at": existing.get("started_at", new_session.started_at),
            "last_updated": new_session.last_updated,
        }

    @staticmethod
    def load_history(days: int = 7) -> list[dict]:
        """加载最近 N 天的用量历史。"""
        if not USAGE_DIR.exists():
            return []

        history = []
        for f in sorted(USAGE_DIR.glob("*.json"), reverse=True)[:days]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                data["date"] = f.stem
                history.append(data)
            except (json.JSONDecodeError, OSError):
                continue
        return history

    @staticmethod
    def format_history(history: list[dict]) -> str:
        """格式化历史用量为可读文本。"""
        if not history:
            return "无用量记录"

        lines = ["📊 最近用量:"]
        total_tokens = 0
        total_calls = 0

        for entry in history:
            d = entry.get("date", "?")
            tokens = entry.get("total_tokens", 0)
            calls = entry.get("api_calls", 0)
            total_tokens += tokens
            total_calls += calls
            lines.append(f"  {d}: {tokens:,} tokens, {calls} 次调用")

        lines.append(f"  ─────────────────")
        lines.append(f"  合计: {total_tokens:,} tokens, {total_calls} 次调用")
        return "\n".join(lines)
