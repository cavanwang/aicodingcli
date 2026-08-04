"""变更审查模块测试。"""

import pytest

from agent.review import ReviewResult, ChangeReviewer


class TestReviewResult:
    """ReviewResult 数据模型测试。"""

    def test_default_values(self):
        result = ReviewResult()
        assert result.files_changed == []
        assert result.lines_added == 0
        assert result.lines_removed == 0
        assert result.tests_found == []
        assert result.tests_passed == 0
        assert result.tests_failed == 0
        assert result.risk_level == "low"
        assert result.suggestions == []


class TestChangeReviewer:
    """ChangeReviewer 审查器测试。"""

    def test_parse_changed_files(self):
        reviewer = ChangeReviewer()
        analysis = """ M agent/core.py
 M agent/tools/registry.py
?? new_file.py"""
        files = reviewer._parse_changed_files(analysis)
        assert "agent/core.py" in files
        assert "agent/tools/registry.py" in files
        assert "new_file.py" in files

    def test_parse_changed_files_empty(self):
        reviewer = ChangeReviewer()
        files = reviewer._parse_changed_files("当前无未提交变更")
        assert files == []

    def test_assess_risk_low(self):
        reviewer = ChangeReviewer()
        result = ReviewResult(
            files_changed=["utils.py"],
            lines_added=10,
            lines_removed=5,
        )
        assert reviewer._assess_risk(result) == "low"

    def test_assess_risk_high_on_test_failure(self):
        reviewer = ChangeReviewer()
        result = ReviewResult(
            files_changed=["core.py"],
            tests_failed=2,
        )
        assert reviewer._assess_risk(result) == "high"

    def test_assess_risk_high_on_many_files(self):
        reviewer = ChangeReviewer()
        result = ReviewResult(
            files_changed=[f"file_{i}.py" for i in range(15)],
        )
        assert reviewer._assess_risk(result) == "high"

    def test_assess_risk_high_on_large_changes(self):
        reviewer = ChangeReviewer()
        result = ReviewResult(
            files_changed=["big.py"],
            lines_added=400,
            lines_removed=200,
        )
        assert reviewer._assess_risk(result) == "high"

    def test_assess_risk_medium_on_core_change(self):
        reviewer = ChangeReviewer()
        result = ReviewResult(
            files_changed=["core.py"],
            lines_added=20,
        )
        assert reviewer._assess_risk(result) == "medium"

    def test_assess_risk_medium_no_tests(self):
        reviewer = ChangeReviewer()
        result = ReviewResult(
            files_changed=["a.py", "b.py", "c.py", "d.py"],
            tests_found=[],
        )
        assert reviewer._assess_risk(result) == "medium"

    def test_generate_suggestions_test_failure(self):
        reviewer = ChangeReviewer()
        result = ReviewResult(tests_failed=3)
        suggestions = reviewer._generate_suggestions(result)
        assert any("失败" in s for s in suggestions)

    def test_generate_suggestions_no_tests(self):
        reviewer = ChangeReviewer()
        result = ReviewResult(files_changed=["a.py", "b.py"])
        suggestions = reviewer._generate_suggestions(result)
        assert any("测试" in s for s in suggestions)

    def test_generate_suggestions_many_files(self):
        reviewer = ChangeReviewer()
        result = ReviewResult(files_changed=[f"f{i}.py" for i in range(8)])
        suggestions = reviewer._generate_suggestions(result)
        assert any("分拆" in s or "文件" in s for s in suggestions)

    def test_generate_suggestions_core_change(self):
        reviewer = ChangeReviewer()
        result = ReviewResult(files_changed=["config.py"])
        suggestions = reviewer._generate_suggestions(result)
        assert any("核心" in s for s in suggestions)

    def test_format_report_empty(self):
        reviewer = ChangeReviewer()
        result = ReviewResult()
        report = reviewer.format_report(result)
        assert "无变更" in report

    def test_format_report_with_changes(self):
        reviewer = ChangeReviewer()
        result = ReviewResult(
            files_changed=["a.py", "b.py"],
            lines_added=50,
            lines_removed=10,
            risk_level="low",
            suggestions=["建议1"],
        )
        report = reviewer.format_report(result)
        assert "变更审查报告" in report
        assert "a.py" in report
        assert "b.py" in report
        assert "+50" in report
        assert "-10" in report
        assert "低风险" in report
        assert "建议1" in report

    def test_format_report_with_tests(self):
        reviewer = ChangeReviewer()
        result = ReviewResult(
            files_changed=["core.py"],
            tests_found=["test_core.py"],
            tests_passed=5,
            tests_failed=1,
            risk_level="high",
        )
        report = reviewer.format_report(result)
        assert "test_core.py" in report
        assert "5" in report
        assert "1" in report
        assert "高风险" in report

    def test_review_no_changes(self):
        """测试无变更时的审查。"""
        reviewer = ChangeReviewer()
        result = reviewer.review()
        # 如果没有变更，应该返回空结果
        assert isinstance(result, ReviewResult)
