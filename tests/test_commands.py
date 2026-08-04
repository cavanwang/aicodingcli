"""Slash 命令系统测试。"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

from cli.commands import (
    COMMANDS,
    dispatch_command,
    cmd_help,
    cmd_compact,
    cmd_cost,
    cmd_clear,
    cmd_status,
    cmd_review,
    cmd_doctor,
    cmd_usage,
    cmd_todo,
    cmd_plan,
    cmd_memory,
    cmd_init,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture()
def mock_agent():
    """创建一个模拟 Agent 实例。"""
    agent = MagicMock()

    # messages
    agent.messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]

    # usage
    agent.usage.summary.return_value = "📊 Token: 1,000"
    agent.usage.session.api_calls = 2
    agent.usage.session.prompt_tokens = 500
    agent.usage.session.completion_tokens = 300
    agent.usage.session.total_tokens = 800
    agent.usage.session.estimated_cost.return_value = 0.01

    # planner
    agent.planner.current_plan = None
    agent.planner.progress_summary.return_value = "当前无执行计划"

    # todo
    agent.todo.progress_line.return_value = ""
    agent.todo.summary.return_value = "无 Todo 项"

    # memory
    agent.memory.tracked_file_count = 10
    agent.memory.file_count = 3
    agent.memory.file_summaries = {
        "core.py": "核心模块",
        "utils.py": "工具函数",
    }

    # compress
    agent.compress_history.return_value = True

    # reset
    agent.reset.return_value = None

    return agent


# ──────────────────────────────────────────────
# 命令注册表测试
# ──────────────────────────────────────────────

class TestCommandRegistry:
    """命令注册表测试。"""

    def test_all_12_commands_registered(self):
        """12 个命令全部注册。"""
        assert len(COMMANDS) == 12

    def test_expected_commands_exist(self):
        """预期的命令都存在。"""
        expected = [
            "/help", "/compact", "/cost", "/clear",
            "/status", "/review", "/doctor",
            "/usage", "/todo", "/plan", "/memory", "/init",
        ]
        for cmd in expected:
            assert cmd in COMMANDS, f"{cmd} 未注册"

    def test_each_command_has_handler_and_description(self):
        """每个命令都有处理函数和描述。"""
        for name, (handler, desc) in COMMANDS.items():
            assert callable(handler), f"{name} 的 handler 不可调用"
            assert isinstance(desc, str) and len(desc) > 0, f"{name} 缺少描述"


# ──────────────────────────────────────────────
# dispatch_command 测试
# ──────────────────────────────────────────────

class TestDispatch:
    """命令分发测试。"""

    def test_dispatch_known_command(self, mock_agent):
        """已知命令正常执行。"""
        result = dispatch_command("/help", mock_agent)
        assert result is True

    def test_dispatch_unknown_command(self, mock_agent):
        """未知命令返回 True（继续循环）。"""
        result = dispatch_command("/nonexistent", mock_agent)
        assert result is True

    def test_dispatch_case_insensitive(self, mock_agent):
        """命令大小写不敏感。"""
        result = dispatch_command("/HELP", mock_agent)
        assert result is True

    def test_dispatch_with_extra_args(self, mock_agent):
        """命令带额外参数不报错。"""
        result = dispatch_command("/help extra", mock_agent)
        assert result is True

    def test_dispatch_handles_exception(self, mock_agent):
        """命令抛异常时不崩溃。"""
        mock_agent.compress_history.side_effect = RuntimeError("boom")
        result = dispatch_command("/compact", mock_agent)
        assert result is True


# ──────────────────────────────────────────────
# 各命令功能测试
# ──────────────────────────────────────────────

class TestCmdHelp:
    """/help 命令测试。"""

    def test_returns_true(self, mock_agent):
        assert cmd_help(mock_agent) is True


class TestCmdCompact:
    """/compact 命令测试。"""

    def test_compress_called(self, mock_agent):
        cmd_compact(mock_agent)
        mock_agent.compress_history.assert_called_once()

    def test_returns_true(self, mock_agent):
        assert cmd_compact(mock_agent) is True


class TestCmdCost:
    """/cost 命令测试。"""

    def test_summary_called(self, mock_agent):
        cmd_cost(mock_agent)
        mock_agent.usage.summary.assert_called_once()

    def test_returns_true(self, mock_agent):
        assert cmd_cost(mock_agent) is True


class TestCmdClear:
    """/clear 命令测试。"""

    def test_reset_called(self, mock_agent):
        cmd_clear(mock_agent)
        mock_agent.reset.assert_called_once()

    def test_returns_true(self, mock_agent):
        assert cmd_clear(mock_agent) is True


class TestCmdStatus:
    """/status 命令测试。"""

    def test_returns_true(self, mock_agent):
        assert cmd_status(mock_agent) is True

    def test_with_plan_and_todo(self, mock_agent):
        """有计划和 Todo 时不报错。"""
        plan = MagicMock()
        plan.status = "in_progress"
        plan.subtasks = [
            MagicMock(status="done"),
            MagicMock(status="pending"),
        ]
        mock_agent.planner.current_plan = plan
        mock_agent.todo.progress_line.return_value = "📝 Todo: 1/3 完成"

        assert cmd_status(mock_agent) is True


class TestCmdReview:
    """/review 命令测试。"""

    def test_returns_true(self, mock_agent):
        # review 会调用 git，mock 掉
        with patch("agent.review.ChangeReviewer") as MockReviewer:
            instance = MockReviewer.return_value
            instance.review.return_value = MagicMock()
            instance.format_report.return_value = "📋 审查报告"
            assert cmd_review(mock_agent) is True


class TestCmdDoctor:
    """/doctor 命令测试。"""

    def test_returns_true(self, mock_agent):
        assert cmd_doctor(mock_agent) is True


class TestCmdUsage:
    """/usage 命令测试。"""

    def test_returns_true(self, mock_agent):
        with patch("agent.usage.UsageTracker") as MockTracker:
            MockTracker.load_history.return_value = []
            MockTracker.format_history.return_value = "无用量记录"
            assert cmd_usage(mock_agent) is True


class TestCmdTodo:
    """/todo 命令测试。"""

    def test_summary_called(self, mock_agent):
        cmd_todo(mock_agent)
        mock_agent.todo.summary.assert_called_once()

    def test_returns_true(self, mock_agent):
        assert cmd_todo(mock_agent) is True


class TestCmdPlan:
    """/plan 命令测试。"""

    def test_progress_summary_called(self, mock_agent):
        cmd_plan(mock_agent)
        mock_agent.planner.progress_summary.assert_called_once()

    def test_returns_true(self, mock_agent):
        assert cmd_plan(mock_agent) is True


class TestCmdMemory:
    """/memory 命令测试。"""

    def test_returns_true(self, mock_agent):
        assert cmd_memory(mock_agent) is True


class TestCmdInit:
    """/init 命令测试。"""

    def test_creates_agent_md(self, mock_agent, tmp_path):
        """在目标目录创建 .agent.md。"""
        with patch("cli.commands.config") as mock_config:
            mock_config.WORKSPACE_DIR = str(tmp_path)
            assert cmd_init(mock_agent) is True
            assert (tmp_path / ".agent.md").exists()

    def test_does_not_overwrite(self, mock_agent, tmp_path):
        """已存在时不覆盖。"""
        target = tmp_path / ".agent.md"
        target.write_text("existing content")

        with patch("cli.commands.config") as mock_config:
            mock_config.WORKSPACE_DIR = str(tmp_path)
            assert cmd_init(mock_agent) is True
            # 内容不变
            assert target.read_text() == "existing content"

    def test_template_contains_sections(self, mock_agent, tmp_path):
        """模板包含必要段落。"""
        with patch("cli.commands.config") as mock_config:
            mock_config.WORKSPACE_DIR = str(tmp_path)
            cmd_init(mock_agent)
            content = (tmp_path / ".agent.md").read_text()
            assert "项目简介" in content
            assert "技术栈" in content
            assert "编码规范" in content
            assert "常用命令" in content
            assert "禁止事项" in content
