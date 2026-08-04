"""任务规划引擎：将复杂任务拆解为有序子任务，逐步执行并跟踪进度。

存储位置：~/.aicoding/plans/{task_id}.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

PLAN_DIR = Path.home() / ".aicoding" / "plans"


# ──────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────

@dataclass
class SubTask:
    """单个子任务。"""
    id: int
    description: str
    status: str = "pending"          # pending | in_progress | done | failed | skipped
    result: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubTask:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class TaskPlan:
    """任务计划：包含目标和有序子任务列表。"""
    task_id: str
    goal: str
    subtasks: list[SubTask] = field(default_factory=list)
    created_at: str = ""
    status: str = "planning"         # planning | executing | completed | failed

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "subtasks": [s.to_dict() for s in self.subtasks],
            "created_at": self.created_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskPlan:
        subtasks = [SubTask.from_dict(s) for s in data.get("subtasks", [])]
        return cls(
            task_id=data["task_id"],
            goal=data["goal"],
            subtasks=subtasks,
            created_at=data.get("created_at", ""),
            status=data.get("status", "planning"),
        )


# ──────────────────────────────────────────────
# 核心类
# ──────────────────────────────────────────────

class TaskPlanner:
    """管理任务计划的创建、推进、状态更新与持久化。"""

    def __init__(self) -> None:
        self._current_plan: TaskPlan | None = None

    # ── 计划生命周期 ──

    @property
    def current_plan(self) -> TaskPlan | None:
        return self._current_plan

    def create_plan(self, goal: str, subtasks_desc: list[str]) -> TaskPlan:
        """创建一个新计划，覆盖旧计划。"""
        task_id = f"plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        subtasks = [
            SubTask(id=i + 1, description=desc)
            for i, desc in enumerate(subtasks_desc)
        ]
        plan = TaskPlan(
            task_id=task_id,
            goal=goal,
            subtasks=subtasks,
            status="planning",
        )
        self._current_plan = plan
        return plan

    def get_next(self) -> SubTask | None:
        """获取下一个待执行子任务，并标记为 in_progress。"""
        plan = self._current_plan
        if plan is None:
            return None

        for st in plan.subtasks:
            if st.status == "pending":
                st.status = "in_progress"
                plan.status = "executing"
                return st
        return None

    def mark_done(self, step_id: int, result: str = "") -> bool:
        """标记指定子任务为完成。"""
        st = self._find_step(step_id)
        if st is None:
            return False
        st.status = "done"
        st.result = result
        # 检查是否所有任务完成
        if all(s.status in ("done", "skipped") for s in self._current_plan.subtasks):
            self._current_plan.status = "completed"
        return True

    def mark_failed(self, step_id: int, reason: str = "") -> bool:
        """标记指定子任务为失败。"""
        st = self._find_step(step_id)
        if st is None:
            return False
        st.status = "failed"
        st.result = reason
        self._current_plan.status = "failed"
        return True

    def skip_step(self, step_id: int, reason: str = "") -> bool:
        """跳过指定子任务。"""
        st = self._find_step(step_id)
        if st is None:
            return False
        st.status = "skipped"
        st.result = reason
        # 检查是否所有任务完成
        if all(s.status in ("done", "skipped") for s in self._current_plan.subtasks):
            self._current_plan.status = "completed"
        return True

    # ── 进度查询 ──

    def progress_summary(self) -> str:
        """返回进度摘要文本。"""
        plan = self._current_plan
        if plan is None:
            return "当前无执行计划"

        total = len(plan.subtasks)
        done = sum(1 for s in plan.subtasks if s.status == "done")
        failed = sum(1 for s in plan.subtasks if s.status == "failed")
        skipped = sum(1 for s in plan.subtasks if s.status == "skipped")
        in_progress = next(
            (s for s in plan.subtasks if s.status == "in_progress"), None
        )

        lines = [
            f"计划: {plan.goal}",
            f"进度: {done}/{total} 完成"
            + (f", {failed} 失败" if failed else "")
            + (f", {skipped} 跳过" if skipped else ""),
        ]
        if in_progress:
            lines.append(f"当前: [{in_progress.id}] {in_progress.description}")

        # 子任务明细
        for s in plan.subtasks:
            icon = {
                "pending": "○",
                "in_progress": "◉",
                "done": "✓",
                "failed": "✗",
                "skipped": "⊘",
            }.get(s.status, "?")
            lines.append(f"  {icon} [{s.id}] {s.description}")

        return "\n".join(lines)

    def get_step(self, step_id: int) -> SubTask | None:
        """获取指定子任务。"""
        return self._find_step(step_id)

    # ── 持久化 ──

    def save(self) -> Path | None:
        """保存当前计划到磁盘。"""
        if self._current_plan is None:
            return None
        PLAN_DIR.mkdir(parents=True, exist_ok=True)
        path = PLAN_DIR / f"{self._current_plan.task_id}.json"
        path.write_text(
            json.dumps(self._current_plan.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def load(self, task_id: str) -> bool:
        """从磁盘加载计划。"""
        path = PLAN_DIR / f"{task_id}.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._current_plan = TaskPlan.from_dict(data)
            return True
        except (json.JSONDecodeError, KeyError):
            return False

    def list_plans(self) -> list[dict[str, str]]:
        """列出所有已保存的计划摘要。"""
        if not PLAN_DIR.exists():
            return []
        plans = []
        for f in sorted(PLAN_DIR.glob("plan_*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                plans.append({
                    "task_id": data.get("task_id", f.stem),
                    "goal": data.get("goal", "")[:80],
                    "status": data.get("status", "unknown"),
                    "created_at": data.get("created_at", ""),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return plans

    # ── 内部方法 ──

    def _find_step(self, step_id: int) -> SubTask | None:
        if self._current_plan is None:
            return None
        for s in self._current_plan.subtasks:
            if s.id == step_id:
                return s
        return None
