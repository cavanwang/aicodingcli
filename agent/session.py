# agent/session.py
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.core import Agent

SESSION_DIR = Path.home() / ".aicoding" / "sessions"


def _session_path(session_id: str) -> Path:
    if not session_id or not session_id.strip():
        raise ValueError("session_id 不能为空")
    return SESSION_DIR / f"{session_id.strip()}.json"


def save_session(agent: "Agent", session_id: str) -> Path:
    """将当前会话消息序列化到磁盘。"""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    path = _session_path(session_id)
    payload = getattr(agent, "messages", None)
    if payload is None:
        payload = getattr(agent, "_messages", [])
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_session(agent: "Agent", session_id: str) -> bool:
    """从磁盘恢复会话消息。"""
    path = _session_path(session_id)
    if not path.exists():
        return False

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False

    if isinstance(data, list):
        agent._messages = data
        return True
    return False
