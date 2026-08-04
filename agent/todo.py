"""持久化 Todo 列表：细粒度任务追踪。

参考 Claude Code TodoWrite 机制，模型自主管理待办事项。
支持 PENDING / IN_PROGRESS / COMPLETE 三种状态，跨会话持久化。

存储位置：~/.aicoding/todos/{session_id}.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.logger import get_logger

logger = get_logger(__name__)

TODO_DIR = Path.home() / ".aicoding" / "todos"


# ──────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────

@dataclass
class TodoItem:
    """单个 Todo 项。"""

    id: int
    content: str
    status: str = "pending"          # pending | in_progress | complete
    result: str = ""                  # 完成时的结果摘要
    error: str = ""                   # 失败时的错误信息
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TodoItem:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ──────────────────────────────────────────────
# Todo 列表管理
# ──────────────────────────────────────────────

class TodoList:
    """Todo 列表管理器，支持增删改查和持久化。"""

    def __init__(self, session_id: str = "default") -> None:
        self._session_id = session_id
        self._items: list[TodoItem] = []
        self._next_id: int = 1

    @property
    def items(self) -> list[TodoItem]:
        return list(self._items)

    @property
    def item_count(self) -> int:
        return len(self._items)

    # ── 增删改查 ──

    def add(self, content: str) -> TodoItem:
        """添加一个待办项，返回新建的 TodoItem。"""
        item = TodoItem(id=self._next_id, content=content)
        self._next_id += 1
        self._items.append(item)
        logger.info("Todo 新增: [%d] %s", item.id, content[:50])
        return item

    def update(
        self,
        todo_id: int,
        content: str | None = None,
        status: str | None = None,
    ) -> TodoItem | None:
        """更新指定 Todo 项的内容或状态。"""
        item = self._find(todo_id)
        if item is None:
            return None
        if content is not None:
            item.content = content
        if status is not None:
            if status not in ("pending", "in_progress", "complete"):
                return None
            item.status = status
        item.updated_at = datetime.now().isoformat()
        return item

    def complete(self, todo_id: int, result: str = "") -> bool:
        """标记指定 Todo 项为完成。"""
        item = self._find(todo_id)
        if item is None:
            return False
        item.status = "complete"
        item.result = result
        item.updated_at = datetime.now().isoformat()
        logger.info("Todo 完成: [%d] %s", todo_id, item.content[:50])
        return True

    def set_error(self, todo_id: int, error: str) -> bool:
        """为指定 Todo 项附加错误信息。"""
        item = self._find(todo_id)
        if item is None:
            return False
        item.error = error
        item.updated_at = datetime.now().isoformat()
        return True

    def get(self, todo_id: int) -> TodoItem | None:
        """获取指定 Todo 项。"""
        return self._find(todo_id)

    def get_current(self) -> TodoItem | None:
        """获取当前进行中的 Todo 项。"""
        for item in self._items:
            if item.status == "in_progress":
                return item
        return None

    def list_all(self) -> list[TodoItem]:
        """列出所有 Todo 项。"""
        return list(self._items)

    def clear(self) -> None:
        """清空所有 Todo 项。"""
        self._items.clear()
        self._next_id = 1

    # ── 进度摘要 ──

    def summary(self) -> str:
        """返回进度摘要文本。"""
        if not self._items:
            return "无 Todo 项"

        total = len(self._items)
        pending = sum(1 for i in self._items if i.status == "pending")
        in_progress = sum(1 for i in self._items if i.status == "in_progress")
        complete = sum(1 for i in self._items if i.status == "complete")

        lines = [f"📝 Todo: {complete}/{total} 完成"]
        if in_progress:
            lines.append(f"  {in_progress} 进行中")
        if pending:
            lines.append(f"  {pending} 待办")

        # 明细
        for item in self._items:
            icon = {"pending": "○", "in_progress": "◉", "complete": "✓"}.get(
                item.status, "?"
            )
            line = f"  {icon} [{item.id}] {item.content}"
            if item.error:
                line += f"  ⚠️ {item.error[:50]}"
            lines.append(line)

        return "\n".join(lines)

    def progress_line(self) -> str:
        """返回单行进度摘要，用于注入 system prompt。"""
        if not self._items:
            return ""
        total = len(self._items)
        complete = sum(1 for i in self._items if i.status == "complete")
        in_progress = sum(1 for i in self._items if i.status == "in_progress")
        pending = sum(1 for i in self._items if i.status == "pending")

        parts = [f"📝 Todo: {complete}/{total} 完成"]
        if in_progress:
            parts.append(f"{in_progress} 进行中")
        if pending:
            parts.append(f"{pending} 待办")
        return ", ".join(parts)

    # ── 持久化 ──

    def save(self) -> Path | None:
        """保存到磁盘。"""
        if not self._items:
            return None
        TODO_DIR.mkdir(parents=True, exist_ok=True)
        path = TODO_DIR / f"{self._session_id}.json"
        data = {
            "session_id": self._session_id,
            "next_id": self._next_id,
            "items": [item.to_dict() for item in self._items],
        }
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Todo 已保存: %s", path)
        return path

    def load(self) -> bool:
        """从磁盘加载。"""
        path = TODO_DIR / f"{self._session_id}.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._next_id = data.get("next_id", 1)
            self._items = [
                TodoItem.from_dict(item) for item in data.get("items", [])
            ]
            logger.info("Todo 已加载: %d 项", len(self._items))
            return True
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning("Todo 加载失败: %s", e)
            return False

    # ── 内部方法 ──

    def _find(self, todo_id: int) -> TodoItem | None:
        for item in self._items:
            if item.id == todo_id:
                return item
        return None
