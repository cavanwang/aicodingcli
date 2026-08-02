"""batch_edit 多文件联合编辑测试。"""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import config
from agent.tools.batch_edit import batch_edit


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """创建测试工作目录（含 git 仓库）。"""
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)

    # 初始化 git 仓库
    subprocess.run("git init", shell=True, cwd=str(tmp_path),
                   capture_output=True, check=True)
    subprocess.run("git config user.email 'test@test.com'", shell=True,
                   cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run("git config user.name 'Test'", shell=True,
                   cwd=str(tmp_path), capture_output=True, check=True)

    # 创建初始提交
    (tmp_path / "README.md").write_text("# Test")
    subprocess.run("git add -A && git commit -m 'init'", shell=True,
                   cwd=str(tmp_path), capture_output=True, check=True)

    return tmp_path


class TestBatchEditBasic:
    """batch_edit 基础功能测试。"""

    def test_batch_edit_two_files(self, workspace):
        """同时编辑两个文件。"""
        (workspace / "a.py").write_text("x = 1\n")
        (workspace / "b.py").write_text("y = 2\n")

        edits = json.dumps([
            {"file_path": "a.py", "old_text": "x = 1", "new_text": "x = 10"},
            {"file_path": "b.py", "old_text": "y = 2", "new_text": "y = 20"},
        ])

        result = batch_edit(edits)

        assert "2/2 成功" in result
        assert "a.py" in result
        assert "b.py" in result
        assert (workspace / "a.py").read_text() == "x = 10\n"
        assert (workspace / "b.py").read_text() == "y = 20\n"

    def test_batch_edit_single_file(self, workspace):
        """编辑单个文件。"""
        (workspace / "main.py").write_text("old_func()\n")

        edits = json.dumps([
            {"file_path": "main.py", "old_text": "old_func()", "new_text": "new_func()"},
        ])

        result = batch_edit(edits)
        assert "1/1 成功" in result
        assert "new_func()" in (workspace / "main.py").read_text()

    def test_batch_edit_creates_checkpoint(self, workspace):
        """批量编辑前自动创建 checkpoint。"""
        (workspace / "f.py").write_text("a = 1\n")

        edits = json.dumps([
            {"file_path": "f.py", "old_text": "a = 1", "new_text": "a = 2"},
        ])

        result = batch_edit(edits)
        assert "Checkpoint" in result or "checkpoint" in result


class TestBatchEditPartialFailure:
    """batch_edit 部分失败场景。"""

    def test_partial_failure(self, workspace):
        """一个成功一个失败。"""
        (workspace / "ok.py").write_text("hello\n")
        # not_exist.py 不存在

        edits = json.dumps([
            {"file_path": "ok.py", "old_text": "hello", "new_text": "world"},
            {"file_path": "not_exist.py", "old_text": "a", "new_text": "b"},
        ])

        result = batch_edit(edits)
        assert "1/2 成功" in result
        assert "1 个编辑失败" in result
        assert (workspace / "ok.py").read_text() == "world\n"

    def test_all_fail(self, workspace):
        """全部编辑失败。"""
        (workspace / "f.py").write_text("content\n")

        edits = json.dumps([
            {"file_path": "f.py", "old_text": "NOT_FOUND", "new_text": "x"},
        ])

        result = batch_edit(edits)
        assert "0/1 成功" in result


class TestBatchEditValidation:
    """batch_edit 参数校验。"""

    def test_invalid_json(self):
        """非法 JSON 输入。"""
        result = batch_edit("not json")
        assert "❌" in result
        assert "JSON" in result

    def test_not_array(self):
        """JSON 不是数组。"""
        result = batch_edit('{"key": "value"}')
        assert "❌" in result
        assert "数组" in result

    def test_empty_array(self):
        """空数组。"""
        result = batch_edit("[]")
        assert "❌" in result
        assert "不能为空" in result

    def test_missing_field(self):
        """缺少必要字段。"""
        edits = json.dumps([
            {"file_path": "a.py", "old_text": "x"},  # 缺少 new_text
        ])
        result = batch_edit(edits)
        assert "❌" in result
        assert "new_text" in result

    def test_not_dict(self):
        """数组元素不是对象。"""
        result = batch_edit('["string"]')
        assert "❌" in result
        assert "不是 JSON 对象" in result

    def test_too_many_edits(self):
        """超过 20 个编辑操作。"""
        edits = json.dumps([
            {"file_path": "f.py", "old_text": "a", "new_text": "b"}
            for _ in range(21)
        ])
        result = batch_edit(edits)
        assert "❌" in result
        assert "最多支持 20" in result


class TestBatchEditRegistration:
    """batch_edit 工具注册测试。"""

    def test_registered_in_tools(self):
        """batch_edit 已注册到工具集。"""
        from agent.tools import TOOL_FUNCTIONS, TOOLS_SCHEMA, CONFIRM_TOOLS

        assert "batch_edit" in TOOL_FUNCTIONS
        assert any(s["function"]["name"] == "batch_edit" for s in TOOLS_SCHEMA)
        assert "batch_edit" in CONFIRM_TOOLS  # 需要确认

    def test_schema_has_edits_param(self):
        """schema 包含 edits 参数。"""
        from agent.tools import TOOLS_SCHEMA

        schema = next(s for s in TOOLS_SCHEMA if s["function"]["name"] == "batch_edit")
        params = schema["function"]["parameters"]["properties"]
        assert "edits" in params
        assert params["edits"]["type"] == "string"
