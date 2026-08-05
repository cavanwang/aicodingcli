"""会话持久化：保存/加载/列出历史会话。

存储位置：~/.aicoding/sessions/{session_id}.json

每个会话文件包含：
- session_id: 唯一标识（时间戳格式 YYYYMMDD-HHMMSS）
- created_at: 创建时间
- updated_at: 最后更新时间
- messages: 完整对话消息列表
- preview: 首条用户消息摘要（用于列表展示）
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.logger import get_logger

if TYPE_CHECKING:
    from agent.core import Agent

logger = get_logger(__name__)

SESSION_DIR = Path.home() / ".aicoding" / "sessions"


def _session_path(session_id: str) -> Path:
    if not session_id or not session_id.strip():
        raise ValueError("session_id 不能为空")
    return SESSION_DIR / f"{session_id.strip()}.json"


def _generate_session_id() -> str:
    """基于时间戳生成唯一 session_id。"""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _extract_preview(messages: list[dict]) -> str:
    """从消息列表中提取首条用户消息作为预览摘要。"""
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if content:
                # 截取前 60 字符
                preview = content.strip().replace("\n", " ")
                return preview[:60] + ("..." if len(preview) > 60 else "")
    return "(空会话)"


# ──────────────────────────────────────────────
# 保存 / 加载
# ──────────────────────────────────────────────

def save_session(
    agent: "Agent",
    session_id: str | None = None,
) -> Path:
    """将当前会话消息序列化到磁盘。

    Args:
        agent: Agent 实例
        session_id: 会话 ID，为 None 时自动生成

    Returns:
        保存的文件路径
    """
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    if session_id is None:
        session_id = _generate_session_id()

    path = _session_path(session_id)
    now = datetime.now().isoformat()

    # 如果文件已存在，保留 created_at
    created_at = now
    if path.exists():
        try:
            old_data = json.loads(path.read_text(encoding="utf-8"))
            created_at = old_data.get("created_at", now)
        except (json.JSONDecodeError, KeyError):
            pass

    payload = {
        "session_id": session_id,
        "created_at": created_at,
        "updated_at": now,
        "model": getattr(agent, "_model", "unknown"),
        "message_count": len(agent._messages),
        "preview": _extract_preview(agent._messages),
        "messages": agent._messages,
    }

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("会话已保存: %s (%d 条消息)", path.name, len(agent._messages))
    return path


def load_session(agent: "Agent", session_id: str) -> bool:
    """从磁盘恢复会话消息。

    Args:
        agent: Agent 实例
        session_id: 会话 ID

    Returns:
        True 表示加载成功，False 表示失败
    """
    path = _session_path(session_id)
    if not path.exists():
        return False

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False

    # 支持新旧格式：新格式有 messages 字段，旧格式直接是列表
    if isinstance(data, dict):
        messages = data.get("messages", [])
    elif isinstance(data, list):
        messages = data
    else:
        return False

    if messages:
        agent._messages = messages
        logger.info("会话已加载: %s (%d 条消息)", session_id, len(messages))
        return True
    return False


# ──────────────────────────────────────────────
# 列出 / 查询
# ──────────────────────────────────────────────

def list_sessions(limit: int = 20) -> list[dict[str, Any]]:
    """列出历史会话（按更新时间倒序）。

    Args:
        limit: 最多返回几条

    Returns:
        会话元数据列表 [{session_id, created_at, updated_at, message_count, preview}, ...]
    """
    if not SESSION_DIR.exists():
        return []

    sessions = []
    for path in SESSION_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                sessions.append({
                    "session_id": data.get("session_id", path.stem),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "model": data.get("model", ""),
                    "message_count": data.get("message_count", len(data.get("messages", []))),
                    "preview": data.get("preview", ""),
                })
            elif isinstance(data, list):
                # 旧格式：直接是消息列表
                sessions.append({
                    "session_id": path.stem,
                    "created_at": "",
                    "updated_at": "",
                    "model": "",
                    "message_count": len(data),
                    "preview": _extract_preview(data),
                })
        except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
            continue

    # 按 updated_at 倒序（最新的在前）
    sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return sessions[:limit]


def delete_session(session_id: str) -> bool:
    """删除指定会话文件。

    Args:
        session_id: 会话 ID

    Returns:
        True 表示删除成功
    """
    path = _session_path(session_id)
    if path.exists():
        path.unlink()
        logger.info("会话已删除: %s", session_id)
        return True
    return False


def format_sessions_list(sessions: list[dict[str, Any]]) -> str:
    """格式化会话列表为可读文本。"""
    if not sessions:
        return "暂无历史会话"

    lines = []
    for i, s in enumerate(sessions, 1):
        sid = s["session_id"]
        updated = s["updated_at"][:16].replace("T", " ") if s["updated_at"] else "未知"
        count = s["message_count"]
        preview = s["preview"]
        model = s.get("model", "")

        model_str = f" [{model}]" if model else ""
        lines.append(f"  {i}. [cyan]{sid}[/]{model_str}")
        lines.append(f"     更新: {updated} | 消息: {count}")
        lines.append(f"     {preview}")

    return "\n".join(lines)

