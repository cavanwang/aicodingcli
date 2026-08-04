"""验证护栏增强测试：JSON 输出、rollback CLI、自动审查触发。"""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent.review import ReviewResult, ChangeReviewer
from agent.tools.task_tools import _is_code_task, _CODE_KEYWORDS


# ──────────────────────────────────────────────
# ReviewResult.to_json() 测试
# ──────────────────────────────────────────────

class TestReviewResultToJson:
    """ReviewResult.to_json() 测试。"""

    def test_basic_serialization(self):
        """基本序列化。"""
        result = ReviewResult(
            files_changed=["a.py", "b.py"],
            lines_added=10,
            lines_removed=5,
            risk_level="low",
            suggestions=["建议1"],
        )
        data = json.loads(result.to_json())
        assert data["files_changed"] == ["a.py", "b.py"]
        assert data["lines_added"] == 10
        assert data["lines_removed"] == 5
        assert data["risk_level"] == "low"
        assert data["suggestions"] == ["建议1"]

    def test_truncates_long_test_output(self):
        """截断过长的 test_output。"""
        long_output = "x" * 1000
        result = ReviewResult(test_output=long_output)
        data = json.loads(result.to_json())
        assert len(data["test_output"]) < 600
        assert "truncated" in data["test_output"]

    def test_truncates_long_raw_analysis(self):
        """截断过长的 raw_analysis。"""
        long_analysis = "y" * 2000
        result = ReviewResult(raw_analysis=long_analysis)
        data = json.loads(result.to_json())
        assert len(data["raw_analysis"]) < 1100
        assert "truncated" in data["raw_analysis"]

    def test_empty_result(self):
        """空结果序列化。"""
        result = ReviewResult()
        data = json.loads(result.to_json())
        assert data["files_changed"] == []
        assert data["lines_added"] == 0
        assert data["risk_level"] == "low"

    def test_valid_json_output(self):
        """输出是合法 JSON。"""
        result = ReviewResult(
            files_changed=["core.py"],
            tests_found=["test_core.py"],
            tests_passed=5,
            tests_failed=1,
            risk_level="high",
        )
        output = result.to_json()
        # 应该能正常解析
        data = json.loads(output)
        assert isinstance(data, dict)
        assert "files_changed" in data


# ──────────────────────────────────────────────
# review_changes format 参数测试
# ──────────────────────────────────────────────

class TestReviewChangesFormat:
    """review_changes format 参数测试。"""

    def test_text_format(self):
        """text 格式返回文本报告。"""
        with patch("agent.review.ChangeReviewer") as MockReviewer:
            instance = MockReviewer.return_value
            instance.review.return_value = ReviewResult(
                files_changed=["a.py"],
                risk_level="low",
            )
            instance.format_report.return_value = "📋 审查报告"

            from agent.tools.memory_tools import review_changes
            result = review_changes(format="text")
            assert "审查报告" in result

    def test_json_format(self):
        """json 格式返回 JSON 字符串。"""
        with patch("agent.review.ChangeReviewer") as MockReviewer:
            instance = MockReviewer.return_value
            instance.review.return_value = ReviewResult(
                files_changed=["a.py"],
                risk_level="low",
            )

            from agent.tools.memory_tools import review_changes
            result = review_changes(format="json")
            data = json.loads(result)
            assert data["files_changed"] == ["a.py"]

    def test_default_format_is_text(self):
        """默认格式是 text。"""
        with patch("agent.review.ChangeReviewer") as MockReviewer:
            instance = MockReviewer.return_value
            instance.review.return_value = ReviewResult()
            instance.format_report.return_value = "📋 报告"

            from agent.tools.memory_tools import review_changes
            result = review_changes()
            assert "报告" in result


# ──────────────────────────────────────────────
# _is_code_task 测试
# ──────────────────────────────────────────────

class TestIsCodeTask:
    """_is_code_task() 测试。"""

    def test_code_keywords(self):
        """包含代码关键词。"""
        assert _is_code_task("修改 core.py 的逻辑")
        assert _is_code_task("创建新的工具函数")
        assert _is_code_task("编辑配置文件")
        assert _is_code_task("实现用户认证")
        assert _is_code_task("修复登录 bug")
        assert _is_code_task("重构数据库层")
        assert _is_code_task("新增 API 接口")
        assert _is_code_task("删除废弃代码")
        assert _is_code_task("编写测试用例")
        assert _is_code_task("开发前端页面")

    def test_non_code_tasks(self):
        """非代码任务。"""
        assert not _is_code_task("分析需求")
        assert not _is_code_task("运行测试")
        assert not _is_code_task("查看文档")
        assert not _is_code_task("讨论方案")
        assert not _is_code_task("部署上线")

    def test_code_keywords_set(self):
        """关键词集合完整。"""
        expected = {"修改", "创建", "编辑", "实现", "修复", "重构", "新增", "删除", "编写", "开发"}
        assert _CODE_KEYWORDS == expected


# ──────────────────────────────────────────────
# complete_step 自动审查触发测试
# ──────────────────────────────────────────────

class TestCompleteStepAutoReview:
    """complete_step 自动审查触发测试。"""

    def test_code_task_triggers_review(self):
        """代码类任务完成后触发审查。"""
        from agent.tools import task_tools

        # 创建 mock planner
        mock_planner = MagicMock()
        mock_plan = MagicMock()
        mock_step = MagicMock()
        mock_step.id = 1
        mock_step.description = "修改 core.py"
        mock_plan.subtasks = [mock_step]
        mock_planner.current_plan = mock_plan
        mock_planner.mark_done.return_value = True
        mock_planner.progress_summary.return_value = "1/1 完成"

        task_tools.set_planner(mock_planner)

        with patch("agent.tools.memory_tools.review_changes", return_value="📋 审查报告") as mock_review:
            result = task_tools.complete_step(1, "已修改")
            mock_review.assert_called_once_with(format="text")
            assert "自动审查报告" in result

    def test_non_code_task_no_review(self):
        """非代码类任务不触发审查。"""
        from agent.tools import task_tools

        mock_planner = MagicMock()
        mock_plan = MagicMock()
        mock_step = MagicMock()
        mock_step.id = 1
        mock_step.description = "分析需求"
        mock_plan.subtasks = [mock_step]
        mock_planner.current_plan = mock_plan
        mock_planner.mark_done.return_value = True
        mock_planner.progress_summary.return_value = "1/1 完成"

        task_tools.set_planner(mock_planner)

        with patch("agent.tools.memory_tools.review_changes") as mock_review:
            result = task_tools.complete_step(1, "已完成")
            mock_review.assert_not_called()
            assert "自动审查报告" not in result

    def test_review_failure_doesnt_break(self):
        """审查失败不影响任务完成。"""
        from agent.tools import task_tools

        mock_planner = MagicMock()
        mock_plan = MagicMock()
        mock_step = MagicMock()
        mock_step.id = 1
        mock_step.description = "修复 bug"
        mock_plan.subtasks = [mock_step]
        mock_planner.current_plan = mock_plan
        mock_planner.mark_done.return_value = True
        mock_planner.progress_summary.return_value = "1/1 完成"

        task_tools.set_planner(mock_planner)

        with patch("agent.tools.memory_tools.review_changes", side_effect=RuntimeError("boom")):
            result = task_tools.complete_step(1, "已修复")
            assert "✓ 任务" in result  # 任务仍然完成


# ──────────────────────────────────────────────
# registry schema 测试
# ──────────────────────────────────────────────

class TestRegistrySchema:
    """registry schema 更新测试。"""

    def test_review_changes_has_format_param(self):
        """review_changes 有 format 参数。"""
        from agent.tools import TOOLS_SCHEMA
        review_schema = None
        for s in TOOLS_SCHEMA:
            if s["function"]["name"] == "review_changes":
                review_schema = s["function"]
                break
        assert review_schema is not None
        props = review_schema["parameters"]["properties"]
        assert "format" in props
        assert props["format"]["type"] == "string"
        assert "enum" in props["format"]
