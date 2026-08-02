"""执行轨迹记录：结构化保存工具调用、自愈事件、LLM 交互。

用于事后复盘、问题排查、性能分析。
存储位置：~/.aicoding/traces/{timestamp}.json
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import config

TRACE_DIR = Path.home() / ".aicoding" / "traces"


class ExecutionTracer:
    """记录一轮对话中的所有关键事件。"""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._session_start = datetime.now()
        self._round_count = 0

    # ──────────────────────────────────────────────
    # 记录方法
    # ──────────────────────────────────────────────

    def record_round(self, round_num: int, message_count: int) -> None:
        """记录一轮 LLM 请求。"""
        self._round_count += 1
        self._events.append({
            "type": "round",
            "timestamp": datetime.now().isoformat(),
            "round": round_num,
            "message_count": message_count,
        })

    def record_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        result: str,
        duration_ms: float,
        success: bool = True,
    ) -> None:
        """记录一次工具调用。"""
        self._events.append({
            "type": "tool_call",
            "timestamp": datetime.now().isoformat(),
            "tool": name,
            "args": args,
            "result_preview": result[:500] if result else "",
            "result_length": len(result) if result else 0,
            "duration_ms": round(duration_ms, 2),
            "success": success,
        })

    def record_recovery(
        self,
        tool_name: str,
        error_type: str,
        classification: dict[str, Any],
        attempt: int,
        max_attempts: int,
        exhausted: bool,
    ) -> None:
        """记录一次自愈触发。"""
        self._events.append({
            "type": "recovery",
            "timestamp": datetime.now().isoformat(),
            "tool": tool_name,
            "error_type": error_type,
            "classification": classification,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "exhausted": exhausted,
        })

    def record_rollback(self, tool_name: str, result: str) -> None:
        """记录一次自动回滚。"""
        self._events.append({
            "type": "rollback",
            "timestamp": datetime.now().isoformat(),
            "tool": tool_name,
            "result": result[:200] if result else "",
        })

    def record_user_rejected(self, tool_name: str) -> None:
        """记录用户拒绝操作。"""
        self._events.append({
            "type": "user_rejected",
            "timestamp": datetime.now().isoformat(),
            "tool": tool_name,
        })

    # ──────────────────────────────────────────────
    # 持久化
    # ──────────────────────────────────────────────

    def save(self) -> Path:
        """保存轨迹到文件，返回路径。"""
        TRACE_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = self._session_start.strftime("%Y%m%d_%H%M%S")
        trace_file = TRACE_DIR / f"trace_{timestamp}.json"

        payload = {
            "session_start": self._session_start.isoformat(),
            "total_rounds": self._round_count,
            "total_events": len(self._events),
            "events": self._events,
        }

        trace_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return trace_file

    # ──────────────────────────────────────────────
    # 状态查询
    # ──────────────────────────────────────────────

    @property
    def event_count(self) -> int:
        """当前记录的事件数。"""
        return len(self._events)

    @property
    def round_count(self) -> int:
        """当前记录的轮次数。"""
        return self._round_count

    def summary(self) -> dict[str, Any]:
        """返回轨迹摘要统计。"""
        tool_calls = [e for e in self._events if e["type"] == "tool_call"]
        recoveries = [e for e in self._events if e["type"] == "recovery"]
        rollbacks = [e for e in self._events if e["type"] == "rollback"]

        return {
            "total_rounds": self._round_count,
            "total_tool_calls": len(tool_calls),
            "total_recoveries": len(recoveries),
            "total_rollbacks": len(rollbacks),
            "avg_tool_duration_ms": (
                sum(tc["duration_ms"] for tc in tool_calls) / len(tool_calls)
                if tool_calls
                else 0
            ),
        }

    def reset(self) -> None:
        """清空轨迹，重新开始记录。"""
        self._events.clear()
        self._session_start = datetime.now()
        self._round_count = 0
