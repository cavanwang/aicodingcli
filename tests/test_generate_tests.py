"""generate_tests 自动生成测试工具测试。"""

import subprocess
from pathlib import Path

import pytest

import config
from agent.tools.generate_tests import (
    generate_tests,
    _get_changed_python_files,
    _extract_signatures,
    _get_test_file_path,
    _generate_test_code,
    _build_call_args,
    _write_test,
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """创建测试工作目录（含 git 仓库）。"""
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)

    subprocess.run("git init", shell=True, cwd=str(tmp_path),
                   capture_output=True, check=True)
    subprocess.run("git config user.email 'test@test.com'", shell=True,
                   cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run("git config user.name 'Test'", shell=True,
                   cwd=str(tmp_path), capture_output=True, check=True)

    # 创建 tests 目录和初始提交
    (tmp_path / "tests").mkdir()
    (tmp_path / "README.md").write_text("# Test")
    subprocess.run("git add -A && git commit -m 'init'", shell=True,
                   cwd=str(tmp_path), capture_output=True, check=True)

    return tmp_path


class TestExtractSignatures:
    """AST 签名提取测试。"""

    def test_extract_public_functions(self, workspace):
        """提取公开函数。"""
        (workspace / "mymod.py").write_text(
            "def hello():\n    pass\n\n"
            "def greet(name):\n    pass\n\n"
            "def _private():\n    pass\n"
        )
        sigs = _extract_signatures("mymod.py")
        assert sigs is not None
        func_names = [f["name"] for f in sigs["functions"]]
        assert "hello" in func_names
        assert "greet" in func_names
        assert "_private" not in func_names

    def test_extract_classes(self, workspace):
        """提取公开类。"""
        (workspace / "mymod.py").write_text(
            "class MyClass:\n"
            "    def __init__(self):\n"
            "        pass\n"
            "    def do_thing(self):\n"
            "        pass\n"
            "    def _internal(self):\n"
            "        pass\n\n"
            "class _Private:\n"
            "    pass\n"
        )
        sigs = _extract_signatures("mymod.py")
        assert sigs is not None
        class_names = [c["name"] for c in sigs["classes"]]
        assert "MyClass" in class_names
        assert "_Private" not in class_names
        # 只包含公开方法
        my_class = next(c for c in sigs["classes"] if c["name"] == "MyClass")
        assert "do_thing" in my_class["methods"]
        assert "_internal" not in my_class["methods"]

    def test_extract_with_params_defaults(self, workspace):
        """提取带默认值的参数。"""
        (workspace / "mymod.py").write_text(
            "def func(name, count=10, flag=True):\n    pass\n"
        )
        sigs = _extract_signatures("mymod.py")
        func = sigs["functions"][0]
        assert func["name"] == "func"
        params = func["params"]
        assert len(params) == 3
        assert params[0]["name"] == "name"
        assert params[0]["has_default"] is False
        assert params[1]["name"] == "count"
        assert params[1]["has_default"] is True

    def test_syntax_error_returns_none(self, workspace):
        """语法错误文件返回 None。"""
        (workspace / "bad.py").write_text("def broken(:\n")
        assert _extract_signatures("bad.py") is None

    def test_nonexistent_file(self, workspace):
        """不存在的文件返回 None。"""
        assert _extract_signatures("no_such.py") is None


class TestBuildCallArgs:
    """参数调用值生成测试。"""

    def test_empty_params(self):
        assert _build_call_args([]) == ""

    def test_path_param(self):
        result = _build_call_args([{"name": "file_path", "has_default": False}])
        assert '""' in result

    def test_count_param(self):
        result = _build_call_args([{"name": "count", "has_default": False}])
        assert "0" in result

    def test_flag_param(self):
        result = _build_call_args([{"name": "is_valid", "has_default": False}])
        assert "True" in result

    def test_items_param(self):
        result = _build_call_args([{"name": "items", "has_default": False}])
        assert "[]" in result

    def test_config_param(self):
        result = _build_call_args([{"name": "config", "has_default": False}])
        assert "{}" in result

    def test_unknown_param(self):
        result = _build_call_args([{"name": "foo", "has_default": False}])
        assert "None" in result

    def test_stops_at_default(self):
        """有默认值的参数不传值。"""
        params = [
            {"name": "name", "has_default": False},
            {"name": "count", "has_default": True},
        ]
        result = _build_call_args(params)
        assert result == '""'


class TestGetTestFilePath:
    """测试文件路径生成。"""

    def test_simple_file(self):
        assert _get_test_file_path("utils.py") == "tests/test_utils.py"

    def test_nested_file(self):
        assert _get_test_file_path("agent/core.py") == "tests/test_core.py"


class TestGenerateTestCode:
    """测试代码生成。"""

    def test_generate_function_test(self, workspace):
        """为函数生成测试。"""
        sigs = {
            "functions": [
                {"name": "hello", "params": [], "is_async": False},
            ],
            "classes": [],
        }
        code = _generate_test_code("mymod.py", sigs, "tests/test_mymod.py")
        assert code is not None
        assert "test_auto_hello" in code
        assert "from mymod import hello" in code

    def test_generate_class_test(self, workspace):
        """为类生成测试。"""
        sigs = {
            "functions": [],
            "classes": [
                {"name": "MyClass", "methods": ["do_thing"]},
            ],
        }
        code = _generate_test_code("mymod.py", sigs, "tests/test_mymod.py")
        assert code is not None
        assert "test_auto_MyClass_init" in code
        assert "test_auto_MyClass_do_thing" in code

    def test_skip_existing_tests(self, workspace):
        """已存在的测试跳过。"""
        test_path = workspace / "tests" / "test_mymod.py"
        test_path.write_text("def test_auto_hello():\n    pass\n")

        sigs = {
            "functions": [
                {"name": "hello", "params": [], "is_async": False},
            ],
            "classes": [],
        }
        code = _generate_test_code("mymod.py", sigs, "tests/test_mymod.py")
        assert code is None  # 已存在，跳过

    def test_nested_module_import(self, workspace):
        """嵌套路径模块导入。"""
        sigs = {
            "functions": [
                {"name": "run", "params": [], "is_async": False},
            ],
            "classes": [],
        }
        code = _generate_test_code("agent/core.py", sigs, "tests/test_core.py")
        assert "from agent.core import run" in code


class TestWriteTest:
    """测试文件写入。"""

    def test_create_new_file(self, workspace):
        """创建新测试文件。"""
        _write_test("tests/test_new.py", "def test_one():\n    pass\n")
        content = (workspace / "tests" / "test_new.py").read_text()
        assert "test_one" in content

    def test_append_to_existing(self, workspace):
        """追加到已有测试文件。"""
        test_path = workspace / "tests" / "test_existing.py"
        test_path.write_text("def test_old():\n    pass\n")

        _write_test("tests/test_existing.py", "\ndef test_new():\n    pass\n")
        content = test_path.read_text()
        assert "test_old" in content
        assert "test_new" in content


class TestGetChangedPythonFiles:
    """变更文件检测。"""

    def test_no_changes(self, workspace):
        """无变更时返回空。"""
        files = _get_changed_python_files()
        assert files == []

    def test_detect_modified_file(self, workspace):
        """检测修改的 Python 文件。"""
        (workspace / "mymod.py").write_text("x = 1\n")
        subprocess.run("git add -A", shell=True, cwd=str(workspace),
                       capture_output=True)

        files = _get_changed_python_files()
        assert "mymod.py" in files

    def test_exclude_test_files(self, workspace):
        """排除测试文件。"""
        (workspace / "tests" / "test_mod.py").write_text("def test_x():\n    pass\n")
        subprocess.run("git add -A", shell=True, cwd=str(workspace),
                       capture_output=True)

        files = _get_changed_python_files()
        assert not any("test_" in f for f in files)

    def test_exclude_non_python(self, workspace):
        """排除非 Python 文件。"""
        (workspace / "readme.md").write_text("# changed")
        subprocess.run("git add -A", shell=True, cwd=str(workspace),
                       capture_output=True)

        files = _get_changed_python_files()
        assert not any(f.endswith(".md") for f in files)


class TestGenerateTestsIntegration:
    """集成测试。"""

    def test_no_changes_message(self, workspace):
        """无变更时提示信息。"""
        result = generate_tests()
        assert "无 Python 文件变更" in result

    def test_generate_and_run(self, workspace):
        """生成并运行测试。"""
        # 创建一个简单模块
        (workspace / "calc.py").write_text(
            "def add(a, b):\n    return a + b\n"
        )
        subprocess.run("git add -A", shell=True, cwd=str(workspace),
                       capture_output=True)

        result = generate_tests()
        assert "calc.py" in result
        # 测试文件应该被创建
        assert (workspace / "tests" / "test_calc.py").exists()


class TestToolRegistration:
    """工具注册测试。"""

    def test_registered(self):
        """generate_tests 已注册到工具集。"""
        from agent.tools import TOOL_FUNCTIONS, TOOLS_SCHEMA, CONFIRM_TOOLS

        assert "generate_tests" in TOOL_FUNCTIONS
        assert any(s["function"]["name"] == "generate_tests" for s in TOOLS_SCHEMA)
        assert "generate_tests" in CONFIRM_TOOLS  # 需要确认
