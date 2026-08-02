"""差异分析工具测试。"""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import config
from agent.tools.git_ops import analyze_changes, get_related_files, git_diff


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """创建一个临时 git 仓库作为测试工作区。"""
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


class TestAnalyzeChanges:
    """analyze_changes() 测试。"""

    def test_no_changes(self, workspace):
        """无变更时返回提示信息。"""
        result = analyze_changes()
        assert "无未提交变更" in result

    def test_detect_modified_file(self, workspace):
        """检测到修改的文件。"""
        # 修改文件
        (workspace / "README.md").write_text("# Modified")
        result = analyze_changes()
        assert "README.md" in result
        assert "修改" in result

    def test_detect_new_file(self, workspace):
        """检测到新增的文件。"""
        (workspace / "new_file.py").write_text("print('hello')")
        result = analyze_changes()
        assert "new_file.py" in result
        assert "新增" in result

    def test_detect_deleted_file(self, workspace):
        """检测到删除的文件。"""
        # 先创建一个文件并提交
        (workspace / "to_delete.txt").write_text("delete me")
        subprocess.run("git add -A && git commit -m 'add file'", shell=True,
                       cwd=str(workspace), capture_output=True, check=True)
        # 删除文件
        (workspace / "to_delete.txt").unlink()
        result = analyze_changes()
        assert "to_delete.txt" in result
        assert "删除" in result

    def test_show_line_stats(self, workspace):
        """显示行数统计。"""
        (workspace / "README.md").write_text("# Line1\n# Line2\n# Line3\n")
        result = analyze_changes()
        assert "新增行数" in result
        assert "删除行数" in result

    def test_show_file_count(self, workspace):
        """显示变更文件数。"""
        (workspace / "file1.py").write_text("a = 1")
        (workspace / "file2.py").write_text("b = 2")
        result = analyze_changes()
        assert "变更文件数: 2" in result


class TestGetRelatedFiles:
    """get_related_files() 测试。"""

    def test_find_python_imports(self, workspace):
        """查找 Python 文件的 import 引用。"""
        # 创建模块文件
        pkg_dir = workspace / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        (pkg_dir / "utils.py").write_text("def helper(): pass")

        # 创建引用文件
        (workspace / "main.py").write_text("from pkg.utils import helper\n")
        (workspace / "app.py").write_text("import pkg.utils\n")

        # 提交以便 git grep 能找到
        subprocess.run("git add -A && git commit -m 'add files'", shell=True,
                       cwd=str(workspace), capture_output=True, check=True)

        result = get_related_files("pkg/utils.py")
        # 检查能找到引用文件（可能包含完整路径）
        assert "main" in result
        assert "app" in result
        assert "utils" in result

    def test_no_related_files(self, workspace):
        """无引用时返回提示。"""
        (workspace / "standalone.py").write_text("x = 1")
        subprocess.run("git add -A && git commit -m 'add'", shell=True,
                       cwd=str(workspace), capture_output=True, check=True)

        result = get_related_files("standalone.py")
        assert "未找到" in result

    def test_requires_file_extension(self, workspace):
        """无扩展名时提示。"""
        result = get_related_files("no_extension")
        assert "需含扩展名" in result

    def test_find_js_imports(self, workspace):
        """查找 JS 文件的 import 引用。"""
        (workspace / "utils.js").write_text("export function helper() {}")
        (workspace / "app.js").write_text("import { helper } from './utils.js'\n")

        subprocess.run("git add -A && git commit -m 'add js'", shell=True,
                       cwd=str(workspace), capture_output=True, check=True)

        result = get_related_files("utils.js")
        assert "app" in result


class TestGitDiffEnhanced:
    """增强版 git_diff() 测试。"""

    def test_diff_all(self, workspace):
        """不传参数时查看全部 diff。"""
        (workspace / "README.md").write_text("# Changed")
        result = git_diff()
        assert "-# Test" in result
        assert "+# Changed" in result

    def test_diff_specific_file(self, workspace):
        """指定文件时只查看该文件的 diff。"""
        # 修改已跟踪的文件
        (workspace / "README.md").write_text("# Changed")
        (workspace / "file2.txt").write_text("content2")
        result = git_diff(file_path="README.md")
        assert "README.md" in result or "Changed" in result

    def test_diff_no_changes(self, workspace):
        """无变更时返回无输出。"""
        result = git_diff()
        assert "无输出" in result


class TestToolRegistration:
    """验证新工具已正确注册。"""

    def test_analyze_changes_registered(self):
        from agent.tools import TOOL_FUNCTIONS, TOOLS_SCHEMA
        assert "analyze_changes" in TOOL_FUNCTIONS
        schema_names = [s["function"]["name"] for s in TOOLS_SCHEMA]
        assert "analyze_changes" in schema_names

    def test_get_related_files_registered(self):
        from agent.tools import TOOL_FUNCTIONS, TOOLS_SCHEMA
        assert "get_related_files" in TOOL_FUNCTIONS
        schema_names = [s["function"]["name"] for s in TOOLS_SCHEMA]
        assert "get_related_files" in schema_names

    def test_git_diff_has_file_path_param(self):
        from agent.tools import TOOLS_SCHEMA
        diff_schema = None
        for s in TOOLS_SCHEMA:
            if s["function"]["name"] == "git_diff":
                diff_schema = s["function"]
                break
        assert diff_schema is not None
        assert "file_path" in diff_schema["parameters"]["properties"]
