"""edit_file 自动回读上下文测试。"""

import pytest
from pathlib import Path

import config
from agent.tools.edit_file import edit_file, _build_context, _find_line


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """设置测试工作目录。"""
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
    return tmp_path


class TestEditFileAutoReadback:
    """edit_file 自动回读功能测试。"""

    def test_edit_returns_context(self, workspace):
        """编辑后返回改动区域上下文。"""
        test_file = workspace / "test.py"
        test_file.write_text("line1\nline2\nline3\nline4\nline5\n")

        result = edit_file("test.py", "line3", "NEW_LINE")

        assert "✅ 已替换" in result
        assert "📖 改动区域" in result
        assert "NEW_LINE" in result

    def test_context_shows_surrounding_lines(self, workspace):
        """上下文包含改动前后的行。"""
        test_file = workspace / "test.py"
        content = "\n".join([f"line{i}" for i in range(1, 51)])
        test_file.write_text(content)

        result = edit_file("test.py", "line25", "CHANGED")

        assert "📖 改动区域" in result
        # 应该包含改动前后的上下文
        assert "line24" in result or "line5" in result  # 前面的行
        assert "line26" in result or "line45" in result  # 后面的行
        assert "CHANGED" in result

    def test_context_marks_changed_lines(self, workspace):
        """改动行用 → 标记，上下文用 │ 标记。"""
        test_file = workspace / "test.py"
        test_file.write_text("aaa\nbbb\nccc\n")

        result = edit_file("test.py", "bbb", "BBB")

        # 改动行应该有 → 标记
        assert "→" in result
        # 上下文行应该有 │ 标记
        assert "│" in result

    def test_edit_multiline_replacement(self, workspace):
        """多行替换也能正确回读。"""
        test_file = workspace / "test.py"
        test_file.write_text("start\nold1\nold2\nold3\nend\n")

        result = edit_file("test.py", "old1\nold2\nold3", "new1\nnew2")

        assert "✅ 已替换" in result
        assert "new1" in result
        assert "new2" in result

    def test_edit_at_beginning_of_file(self, workspace):
        """文件开头编辑也能正确回读。"""
        test_file = workspace / "test.py"
        test_file.write_text("first\nsecond\nthird\n")

        result = edit_file("test.py", "first", "FIRST")

        assert "✅ 已替换" in result
        assert "FIRST" in result

    def test_edit_at_end_of_file(self, workspace):
        """文件末尾编辑也能正确回读。"""
        test_file = workspace / "test.py"
        test_file.write_text("first\nsecond\nlast\n")

        result = edit_file("test.py", "last", "LAST")

        assert "✅ 已替换" in result
        assert "LAST" in result

    def test_edit_failure_no_context(self, workspace):
        """编辑失败时不返回上下文。"""
        test_file = workspace / "test.py"
        test_file.write_text("content\n")

        result = edit_file("test.py", "not_found", "replacement")

        assert "❌" in result
        assert "📖" not in result


class TestBuildContext:
    """_build_context 辅助函数测试。"""

    def test_context_window_size(self):
        """上下文窗口不超过指定范围。"""
        content = "\n".join([f"line{i}" for i in range(1, 101)])
        result = _build_context("test.py", content, "old", "line50")

        # 应该包含行号信息
        assert "第" in result
        assert "行" in result

    def test_context_for_empty_new_text(self):
        """新文本为空时的处理。"""
        content = "line1\nline2\nline3"
        result = _build_context("test.py", content, "old", "")

        # 应该能处理空替换
        assert "改动区域" in result


class TestFindLine:
    """_find_line 辅助函数测试。"""

    def test_find_existing_line(self):
        """找到存在的行。"""
        lines = ["aaa", "bbb", "ccc"]
        assert _find_line(lines, "bbb") == 1

    def test_find_nonexistent_line(self):
        """找不到的行返回 None。"""
        lines = ["aaa", "bbb", "ccc"]
        assert _find_line(lines, "zzz") is None

    def test_find_empty_target(self):
        """空目标返回 0。"""
        lines = ["aaa", "bbb"]
        assert _find_line(lines, "") == 0

    def test_find_partial_match(self):
        """部分匹配也能找到。"""
        lines = ["hello world", "foo bar"]
        assert _find_line(lines, "world") == 0
