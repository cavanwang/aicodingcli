"""符号导航工具（find_definition / find_references / get_import_tree）测试。"""

import pytest

import config
from agent.tools.symbol_nav import (
    find_definition,
    find_references,
    get_import_tree,
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """创建带示例 Python 模块的测试工作目录。"""
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)

    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "math_utils.py").write_text(
        "MAX_RETRY = 3\n\n"
        "def paginate(items, page, page_size):\n"
        "    return items[page * page_size:(page + 1) * page_size]\n\n"
        "class Paginator:\n"
        "    def next_page(self):\n"
        "        return paginate([], 0, MAX_RETRY)\n"
    )
    (pkg / "api.py").write_text(
        "from mypkg.math_utils import paginate, Paginator\n\n"
        "def handle():\n"
        "    return paginate([1, 2, 3], 0, 2)\n"
    )
    # 干扰项：应被忽略的目录
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "fake.py").write_text("def paginate(): pass\n")
    return tmp_path


class TestFindDefinition:
    def test_find_function(self, workspace):
        out = find_definition("paginate")
        assert "mypkg/math_utils.py:3" in out
        assert "函数" in out
        # .venv 内的同名函数不应出现
        assert ".venv" not in out

    def test_find_class(self, workspace):
        out = find_definition("Paginator")
        assert "mypkg/math_utils.py:6" in out
        assert "class" in out

    def test_find_module_level_assign(self, workspace):
        out = find_definition("MAX_RETRY")
        assert "mypkg/math_utils.py:1" in out

    def test_limit_to_single_file(self, workspace):
        out = find_definition("paginate", file_path="mypkg/api.py")
        assert "未找到" in out  # api.py 只有引用没有定义

    def test_not_found(self, workspace):
        assert "未找到" in find_definition("no_such_symbol")

    def test_empty_symbol(self, workspace):
        assert "错误" in find_definition("  ")

    def test_file_not_exist(self, workspace):
        assert "文件不存在" in find_definition("x", file_path="nope.py")

    def test_path_escape(self, workspace):
        assert "路径越界" in find_definition("x", file_path="../etc/passwd")


class TestFindReferences:
    def test_name_and_attribute_refs(self, workspace):
        out = find_references("paginate")
        assert "mypkg/api.py:1" in out  # from ... import paginate
        assert "mypkg/api.py:4" in out  # 调用处
        assert "mypkg/math_utils.py" in out  # 包内调用

    def test_no_venv_pollution(self, workspace):
        out = find_references("paginate")
        assert ".venv" not in out

    def test_not_found(self, workspace):
        assert "未找到" in find_references("no_such_symbol")


class TestGetImportTree:
    def test_forward_and_reverse(self, workspace):
        out = get_import_tree("mypkg/math_utils.py")
        assert "正链" in out and "反链" in out
        assert "mypkg/api.py" in out  # api.py 导入了它

    def test_forward_imports(self, workspace):
        out = get_import_tree("mypkg/api.py")
        assert "from mypkg.math_utils import paginate, Paginator" in out

    def test_not_python(self, workspace):
        (workspace / "note.txt").write_text("hi")
        assert "仅支持 Python 文件" in get_import_tree("note.txt")

    def test_not_exist(self, workspace):
        assert "文件不存在" in get_import_tree("nope.py")


class TestRegistryIntegration:
    def test_tools_registered(self):
        from agent.tools.registry import _REGISTRY, TOOL_FUNCTIONS

        names = {i["schema"]["name"] for i in _REGISTRY}
        assert {"find_definition", "find_references", "get_import_tree"} <= names
        assert TOOL_FUNCTIONS["find_definition"] is find_definition

    def test_not_in_confirm_tools(self):
        from agent.tools.registry import CONFIRM_TOOLS

        assert "find_definition" not in CONFIRM_TOOLS
        assert "find_references" not in CONFIRM_TOOLS
        assert "get_import_tree" not in CONFIRM_TOOLS
