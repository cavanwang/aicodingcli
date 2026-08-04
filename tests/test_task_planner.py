"""任务规划引擎测试。"""

import json
import shutil
from pathlib import Path

import pytest

from agent.task_planner import TaskPlanner, TaskPlan, SubTask, PLAN_DIR


class TestSubTask:
    """SubTask 数据模型测试。"""

    def test_subtask_creation(self):
        st = SubTask(id=1, description="测试任务")
        assert st.id == 1
        assert st.description == "测试任务"
        assert st.status == "pending"
        assert st.result == ""

    def test_subtask_to_dict(self):
        st = SubTask(id=1, description="测试任务", status="done", result="完成")
        data = st.to_dict()
        assert data["id"] == 1
        assert data["description"] == "测试任务"
        assert data["status"] == "done"
        assert data["result"] == "完成"

    def test_subtask_from_dict(self):
        data = {"id": 2, "description": "任务B", "status": "in_progress", "result": ""}
        st = SubTask.from_dict(data)
        assert st.id == 2
        assert st.description == "任务B"
        assert st.status == "in_progress"


class TestTaskPlan:
    """TaskPlan 数据模型测试。"""

    def test_plan_creation(self):
        plan = TaskPlan(task_id="plan_001", goal="测试目标")
        assert plan.task_id == "plan_001"
        assert plan.goal == "测试目标"
        assert plan.status == "planning"
        assert plan.subtasks == []
        assert plan.created_at != ""

    def test_plan_with_subtasks(self):
        subtasks = [
            SubTask(id=1, description="步骤1"),
            SubTask(id=2, description="步骤2"),
        ]
        plan = TaskPlan(task_id="plan_002", goal="目标", subtasks=subtasks)
        assert len(plan.subtasks) == 2
        assert plan.subtasks[0].description == "步骤1"

    def test_plan_to_dict(self):
        subtasks = [SubTask(id=1, description="步骤1")]
        plan = TaskPlan(task_id="plan_003", goal="目标", subtasks=subtasks)
        data = plan.to_dict()
        assert data["task_id"] == "plan_003"
        assert len(data["subtasks"]) == 1
        assert data["subtasks"][0]["id"] == 1

    def test_plan_from_dict(self):
        data = {
            "task_id": "plan_004",
            "goal": "测试目标",
            "subtasks": [{"id": 1, "description": "步骤1", "status": "pending", "result": ""}],
            "created_at": "2024-01-01T00:00:00",
            "status": "executing",
        }
        plan = TaskPlan.from_dict(data)
        assert plan.task_id == "plan_004"
        assert plan.goal == "测试目标"
        assert plan.status == "executing"
        assert len(plan.subtasks) == 1


class TestTaskPlanner:
    """TaskPlanner 核心类测试。"""

    def test_initial_state(self):
        planner = TaskPlanner()
        assert planner.current_plan is None

    def test_create_plan(self):
        planner = TaskPlanner()
        plan = planner.create_plan("重构模块", ["分析代码", "修改文件", "运行测试"])
        assert plan.goal == "重构模块"
        assert len(plan.subtasks) == 3
        assert plan.subtasks[0].id == 1
        assert plan.subtasks[0].status == "pending"
        assert planner.current_plan is plan

    def test_get_next(self):
        planner = TaskPlanner()
        planner.create_plan("目标", ["任务A", "任务B"])

        step = planner.get_next()
        assert step is not None
        assert step.id == 1
        assert step.status == "in_progress"
        assert planner.current_plan.status == "executing"

    def test_get_next_returns_none_when_all_done(self):
        planner = TaskPlanner()
        planner.create_plan("目标", ["任务A"])
        step = planner.get_next()
        planner.mark_done(1, "完成")
        assert planner.get_next() is None

    def test_mark_done(self):
        planner = TaskPlanner()
        planner.create_plan("目标", ["任务A", "任务B"])
        planner.get_next()

        ok = planner.mark_done(1, "任务A完成")
        assert ok is True
        assert planner.current_plan.subtasks[0].status == "done"
        assert planner.current_plan.subtasks[0].result == "任务A完成"

    def test_mark_done_completes_plan(self):
        planner = TaskPlanner()
        planner.create_plan("目标", ["任务A"])
        planner.get_next()
        planner.mark_done(1)
        assert planner.current_plan.status == "completed"

    def test_mark_done_invalid_id(self):
        planner = TaskPlanner()
        planner.create_plan("目标", ["任务A"])
        assert planner.mark_done(99) is False

    def test_mark_failed(self):
        planner = TaskPlanner()
        planner.create_plan("目标", ["任务A"])
        planner.get_next()

        ok = planner.mark_failed(1, "出错了")
        assert ok is True
        assert planner.current_plan.subtasks[0].status == "failed"
        assert planner.current_plan.status == "failed"

    def test_skip_step(self):
        planner = TaskPlanner()
        planner.create_plan("目标", ["任务A", "任务B"])
        planner.skip_step(1, "不需要")

        assert planner.current_plan.subtasks[0].status == "skipped"

        # 跳过所有任务后计划应完成
        planner.skip_step(2)
        assert planner.current_plan.status == "completed"

    def test_progress_summary_no_plan(self):
        planner = TaskPlanner()
        assert planner.current_plan is None
        summary = planner.progress_summary()
        assert "无执行计划" in summary

    def test_progress_summary_with_plan(self):
        planner = TaskPlanner()
        planner.create_plan("重构", ["分析", "修改", "测试"])
        planner.get_next()  # 任务1 in_progress

        summary = planner.progress_summary()
        assert "重构" in summary
        assert "0/3" in summary
        assert "分析" in summary

    def test_progress_summary_partial_done(self):
        planner = TaskPlanner()
        planner.create_plan("目标", ["A", "B", "C"])
        planner.get_next()
        planner.mark_done(1)
        planner.get_next()
        planner.mark_done(2)

        summary = planner.progress_summary()
        assert "2/3" in summary

    def test_save_and_load(self):
        planner = TaskPlanner()
        planner.create_plan("测试持久化", ["步骤1", "步骤2"])
        planner.get_next()
        planner.mark_done(1, "完成")

        path = planner.save()
        assert path is not None
        assert path.exists()

        # 新 planner 加载
        planner2 = TaskPlanner()
        ok = planner2.load(planner.current_plan.task_id)
        assert ok is True
        assert planner2.current_plan.goal == "测试持久化"
        assert len(planner2.current_plan.subtasks) == 2
        assert planner2.current_plan.subtasks[0].status == "done"

        # 清理
        path.unlink(missing_ok=True)

    def test_load_nonexistent(self):
        planner = TaskPlanner()
        assert planner.load("nonexistent_plan") is False

    def test_save_no_plan(self):
        planner = TaskPlanner()
        assert planner.save() is None

    def test_get_step(self):
        planner = TaskPlanner()
        planner.create_plan("目标", ["A", "B"])
        step = planner.get_step(2)
        assert step is not None
        assert step.description == "B"
        assert planner.get_step(99) is None

    def test_list_plans_empty(self):
        planner = TaskPlanner()
        plans = planner.list_plans()
        assert isinstance(plans, list)
