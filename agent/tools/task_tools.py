"""任务规划工具函数：供 Agent 工具注册表调用。

通过模块级 _planner 引用访问 TaskPlanner 实例，
由 Agent 初始化时通过 set_planner() 注入。
"""

from __future__ import annotations

import json
from typing import Any

from agent.task_planner import TaskPlanner

# 模块级 planner 引用，由 Agent 初始化时注入
_planner: TaskPlanner | None = None


def set_planner(planner: TaskPlanner) -> None:
    """注入 TaskPlanner 实例（Agent 初始化时调用）。"""
    global _planner
    _planner = planner


def _get_planner() -> TaskPlanner:
    if _planner is None:
        raise RuntimeError("TaskPlanner 未初始化，请先调用 set_planner()")
    return _planner


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

# 代码修改类关键词（触发自动审查）
_CODE_KEYWORDS = {"修改", "创建", "编辑", "实现", "修复", "重构", "新增", "删除", "编写", "开发"}


def _is_code_task(description: str) -> bool:
    """判断子任务是否为代码修改类。"""
    return any(kw in description for kw in _CODE_KEYWORDS)

def create_plan(goal: str, subtasks: str) -> str:
    """创建任务执行计划。

    Args:
        goal: 任务目标描述
        subtasks: JSON 数组字符串，每个元素是一个子任务描述
                  示例: '["分析需求", "修改代码", "运行测试"]'
    """
    planner = _get_planner()
    try:
        subtasks_list = json.loads(subtasks)
        if not isinstance(subtasks_list, list):
            return "❌ subtasks 必须是 JSON 数组格式"
    except json.JSONDecodeError:
        # 兼容纯文本格式：用换行分隔
        subtasks_list = [s.strip() for s in subtasks.strip().split("\n") if s.strip()]

    if not subtasks_list:
        return "❌ 子任务列表不能为空"

    plan = planner.create_plan(goal, subtasks_list)
    planner.save()

    lines = [f"✅ 计划已创建: {plan.task_id}"]
    lines.append(f"目标: {goal}")
    lines.append(f"子任务数: {len(plan.subtasks)}")
    for s in plan.subtasks:
        lines.append(f"  [{s.id}] {s.description}")
    return "\n".join(lines)


def next_step() -> str:
    """获取下一个待执行子任务。"""
    planner = _get_planner()
    step = planner.get_next()
    if step is None:
        return "所有子任务已完成或无待执行任务"
    planner.save()
    return f"▶ 当前任务 [{step.id}]: {step.description}"


def complete_step(step_id: int, result: str = "") -> str:
    """标记子任务完成。

    Args:
        step_id: 子任务序号
        result: 执行结果摘要
    """
    planner = _get_planner()

    # 先获取子任务描述（用于判断是否代码类）
    step = None
    for s in planner.current_plan.subtasks if planner.current_plan else []:
        if s.id == step_id:
            step = s
            break

    ok = planner.mark_done(step_id, result)
    if not ok:
        return f"❌ 未找到序号为 {step_id} 的子任务"
    planner.save()

    output = f"✓ 任务 [{step_id}] 已完成\n{planner.progress_summary()}"

    # 代码修改类任务完成后，自动触发审查
    if step and _is_code_task(step.description):
        try:
            from agent.tools.memory_tools import review_changes
            review_report = review_changes(format="text")
            output += f"\n\n🔍 自动审查报告:\n{review_report}"
        except Exception:
            pass  # 审查失败不影响任务完成

    return output


def plan_status() -> str:
    """查看当前计划进度。"""
    planner = _get_planner()
    return planner.progress_summary()
