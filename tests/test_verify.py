"""verify_changes 工具测试。"""

import subprocess
import sys
from pathlib import Path

import pytest

import config
import agent.tools.verify as verify_module
from agent.tools.verify import (
    verify_changes,
    _get_changed_files,
    _find_related_tests,
    _run_tests,
)


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
    
    # 创建 tests 目录
    (tmp_path / "tests").mkdir()
    
    return tmp_path


class TestGetChangedFiles:
    """_get_changed_files() 测试。"""

    def test_no_changes(self, workspace):
        """无变更时返回空列表。"""
        files = _get_changed_files()
        assert files == []

    def test_detect_modified_file(self, workspace):
        """检测到修改的文件。"""
        (workspace / "README.md").write_text("# Modified")
        files = _get_changed_files()
        # README.md 不是 .py/.js 文件，应该被过滤
        assert "README.md" not in files

    def test_detect_python_file(self, workspace):
        """检测 Python 文件变更。"""
        (workspace / "core.py").write_text("x = 1")
        files = _get_changed_files()
        assert "core.py" in files

    def test_exclude_test_files(self, workspace):
        """排除测试文件本身的变更。"""
        (workspace / "tests" / "test_core.py").write_text("def test_x(): pass")
        files = _get_changed_files()
        # 测试文件应该被排除
        assert not any("test_" in f for f in files)

    def test_exclude_deleted_files(self, workspace):
        """排除已删除的文件。"""
        (workspace / "to_delete.py").write_text("x = 1")
        subprocess.run("git add -A && git commit -m 'add'", shell=True,
                       cwd=str(workspace), capture_output=True, check=True)
        (workspace / "to_delete.py").unlink()
        files = _get_changed_files()
        assert "to_delete.py" not in files


class TestFindRelatedTests:
    """_find_related_tests() 测试。"""

    def test_find_test_in_tests_dir(self, workspace):
        """在 tests/ 目录下找到测试文件。"""
        (workspace / "tests" / "test_core.py").write_text("def test_x(): pass")
        
        tests = _find_related_tests(["core.py"])
        assert "tests/test_core.py" in tests

    def test_find_test_with_module_prefix(self, workspace):
        """支持 test_ 前缀匹配。"""
        (workspace / "tests" / "test_utils.py").write_text("def test_y(): pass")
        
        tests = _find_related_tests(["utils.py"])
        assert "tests/test_utils.py" in tests

    def test_no_related_tests(self, workspace):
        """无相关测试时返回空列表。"""
        tests = _find_related_tests(["nonexistent.py"])
        assert tests == []

    def test_multiple_changed_files(self, workspace):
        """多个变更文件时找到所有相关测试。"""
        (workspace / "tests" / "test_core.py").write_text("def test_x(): pass")
        (workspace / "tests" / "test_utils.py").write_text("def test_y(): pass")
        
        tests = _find_related_tests(["core.py", "utils.py"])
        assert len(tests) == 2
        assert "tests/test_core.py" in tests
        assert "tests/test_utils.py" in tests

    def test_no_duplicate_tests(self, workspace):
        """不返回重复的测试文件。"""
        (workspace / "tests" / "test_core.py").write_text("def test_x(): pass")
        
        # 同一个模块被多次引用
        tests = _find_related_tests(["core.py", "core.py"])
        assert tests.count("tests/test_core.py") == 1


class TestRunTests:
    """_run_tests() 测试。"""

    def test_run_passing_tests(self, workspace):
        """运行通过的测试。"""
        test_file = workspace / "tests" / "test_pass.py"
        test_file.write_text("def test_ok(): assert True\n")
        
        result = _run_tests(["tests/test_pass.py"])
        assert "✅ 测试通过" in result

    def test_run_failing_tests(self, workspace):
        """运行失败的测试。"""
        test_file = workspace / "tests" / "test_fail.py"
        test_file.write_text("def test_bad(): assert False\n")
        
        result = _run_tests(["tests/test_fail.py"])
        assert "❌ 测试失败" in result

    def test_run_no_tests(self, workspace):
        """无测试可运行时返回提示。"""
        result = _run_tests([])
        assert "无测试可运行" in result

    def test_uses_current_interpreter(self, workspace, monkeypatch):
        """必须用当前解释器跑测试，不能用裸 python（防解析到无 pytest 的系统环境）。"""
        captured = {}

        class FakeResult:
            returncode = 0
            stdout = "1 passed"
            stderr = ""

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env")
            return FakeResult()

        monkeypatch.setattr(verify_module.subprocess, "run", fake_run)
        _run_tests(["tests/test_pass.py"])
        assert captured["cmd"].startswith(sys.executable)
        assert "pytest" in captured["cmd"]
        # PATH 必须包含当前解释器所在目录
        assert str(Path(sys.executable).parent) in captured["env"]["PATH"]


class TestVerifyChanges:
    """verify_changes() 集成测试。"""

    def test_no_changes_message(self, workspace):
        """无变更时返回提示。"""
        result = verify_changes()
        assert "无文件变更" in result

    def test_changes_with_tests(self, workspace):
        """有变更且有相关测试时运行测试。"""
        # 创建源代码和测试
        (workspace / "core.py").write_text("x = 1")
        (workspace / "tests" / "test_core.py").write_text(
            "def test_core(): assert True\n"
        )
        
        result = verify_changes()
        assert "变更文件" in result
        assert "相关测试" in result
        assert "✅ 测试通过" in result

    def test_changes_without_tests(self, workspace):
        """有变更但无相关测试时返回提示。"""
        (workspace / "new_module.py").write_text("x = 1")
        
        result = verify_changes()
        assert "变更文件" in result
        assert "未找到相关测试" in result


class TestToolRegistration:
    """验证工具已正确注册。"""

    def test_verify_changes_registered(self):
        from agent.tools import TOOL_FUNCTIONS, TOOLS_SCHEMA
        assert "verify_changes" in TOOL_FUNCTIONS
        schema_names = [s["function"]["name"] for s in TOOLS_SCHEMA]
        assert "verify_changes" in schema_names
