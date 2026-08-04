"""任务规划工具函数测试。"""

import json
from unittest.mock import patch, MagicMock

import pytest

from agent.task_planner import TaskPlanner, TaskPlan, SubTask
from agent.tools import task_tools


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_planner():
    """每个测试前后重置模块级 _planner，避免状态泄漏。"""
    original = task_tools._planner
    task_tools._planner = None
    yield
    task_tools._planner = original


@pytest.fixture()
def planner():
    """返回一个干净的 TaskPlanner 并注入到 task_tools。"""
    p = TaskPlanner()
    task_tools.set_planner(p)
    return p


# ──────────────────────────────────────────────
# set_planner / _get_planner
# ──────────────────────────────────────────────

class TestSetPlanner:
    def test_set_and_get(self, planner):
        assert task_tools._get_planner() is planner

    def test_get_planner_raises_when_not_set(self):
        task_tools._planner = None
        with pytest.raises(RuntimeError, match="未初始化"):
            task_tools._get_planner()


# ──────────────────────────────────────────────
# create_plan
# ──────────────────────────────────────────────

class TestCreatePlan:
    def test_create_plan_with_json_array(self, planner):
        subtasks_json = json.dumps(["分析需求", "修改代码", "运行测试"])
        result = task_tools.create_plan("完成功能A", subtasks_json)

        assert "✅ 计划已创建" in result
        assert "完成功能A" in result
        assert "子任务数: 3" in result
        assert "[1] 分析需求" in result
        assert "[2] 修改代码" in result
        assert "[3] 运行测试" in result
        assert planner.current_plan is not None
        assert len(planner.current_plan.subtasks) == 3

    def test_create_plan_with_newline_separated(self, planner):
        """兼容纯文本换行分隔格式。"""
        subtasks_text = "分析需求\n修改代码\n运行测试"
        result = task_tools.create_plan("完成功能A", subtasks_text)

        assert "✅ 计划已创建" in result
        assert "子任务数: 3" in result

    def test_create_plan_empty_subtasks_returns_error(self, planner):
        result = task_tools.create_plan("空任务", "[]")
        assert "❌" in result
        assert "不能为空" in result

    def test_create_plan_non_list_json_returns_error(self, planner):
        result = task_tools.create_plan("错误格式", '{"key": "value"}')
        assert "❌" in result
        assert "JSON 数组" in result

    def test_create_plan_overwrites_previous(self, planner):
        task_tools.create_plan("计划1", json.dumps(["步骤A"]))
        task_tools.create_plan("计划2", json.dumps(["步骤B", "步骤C"]))

        assert planner.current_plan.goal == "计划2"
        assert len(planner.current_plan.subtasks) == 2


# ──────────────────────────────────────────────
# next_step
# ──────────────────────────────────────────────

class TestNextStep:
    def test_next_step_returns_first_pending(self, planner):
        task_tools.create_plan("测试", json.dumps(["步骤1", "步骤2"]))
        result = task_tools.next_step()

        assert "▶" in result
        assert "[1]" in result
        assert "步骤1" in result

    def test_next_step_advances(self, planner):
        task_tools.create_plan("测试", json.dumps(["步骤1", "步骤2"]))
        task_tools.next_step()          # 获取步骤1，标记 in_progress
        task_tools.complete_step(1)     # 完成步骤1
        result = task_tools.next_step()  # 应返回步骤2

        assert "[2]" in result
        assert "步骤2" in result

    def test_next_step_all_done(self, planner):
        task_tools.create_plan("测试", json.dumps(["步骤1"]))
        task_tools.next_step()
        task_tools.complete_step(1)
        result = task_tools.next_step()

        assert "已完成" in result or "无待执行" in result

    def test_next_step_no_plan(self, planner):
        result = task_tools.next_step()
        assert "已完成" in result or "无待执行" in result


# ──────────────────────────────────────────────
# complete_step
# ──────────────────────────────────────────────

class TestCompleteStep:
    def test_complete_existing_step(self, planner):
        task_tools.create_plan("测试", json.dumps(["步骤1", "步骤2"]))
        task_tools.next_step()
        result = task_tools.complete_step(1, "搞定了")

        assert "✓" in result
        assert "任务 [1] 已完成" in result

    def test_complete_nonexistent_step(self, planner):
        task_tools.create_plan("测试", json.dumps(["步骤1"]))
        result = task_tools.complete_step(99)

        assert "❌" in result
        assert "99" in result

    def test_complete_with_result_recorded(self, planner):
        task_tools.create_plan("测试", json.dumps(["步骤1"]))
        task_tools.next_step()
        task_tools.complete_step(1, "修复了3个bug")

        step = planner.current_plan.subtasks[0]
        assert step.status == "done"
        assert step.result == "修复了3个bug"

    def test_complete_last_step_marks_plan_completed(self, planner):
        task_tools.create_plan("测试", json.dumps(["步骤1"]))
        task_tools.next_step()
        task_tools.complete_step(1)

        assert planner.current_plan.status == "completed"


# ──────────────────────────────────────────────
# plan_status
# ──────────────────────────────────────────────

class TestPlanStatus:
    def test_plan_status_no_plan(self, planner):
        result = task_tools.plan_status()
        assert "无执行计划" in result

    def test_plan_status_shows_progress(self, planner):
        task_tools.create_plan("重构模块", json.dumps(["分析", "修改", "测试"]))
        task_tools.next_step()
        task_tools.complete_step(1, "分析完毕")

        result = task_tools.plan_status()
        assert "重构模块" in result
        assert "1/3 完成" in result

    def test_plan_status_shows_all_states(self, planner):
        task_tools.create_plan("测试", json.dumps(["A", "B", "C"]))
        task_tools.next_step()           # A → in_progress
        task_tools.complete_step(1)      # A → done
        task_tools.next_step()           # B → in_progress

        result = task_tools.plan_status()
        assert "✓" in result   # A done
        assert "◉" in result   # B in_progress
        assert "○" in result   # C pending
