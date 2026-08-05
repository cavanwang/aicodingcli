"""代码记忆模块测试。"""

import json
import time
from pathlib import Path

import pytest

import config
from agent.memory import (
    CodeMemory,
    MEMORY_DIR,
    MEMORY_FILE,
    quick_scan,
    _compute_file_hash,
    _is_ignored_dir,
    _is_ignored_file,
    _is_tracked_extension,
)


class TestCodeMemory:
    """CodeMemory 数据模型测试。"""

    def test_initial_state(self):
        mem = CodeMemory()
        assert mem.file_summaries == {}
        assert mem.key_interfaces == {}
        assert mem.project_facts == []
        assert mem.file_hashes == {}
        assert mem.file_mtimes == {}
        assert mem.known_files == []
        assert mem.last_updated != ""

    def test_update_file_summary(self):
        mem = CodeMemory()
        mem.update_file_summary("agent/core.py", "Agent 核心循环")
        assert mem.file_summaries["agent/core.py"] == "Agent 核心循环"

    def test_update_key_interfaces(self):
        mem = CodeMemory()
        mem.update_key_interfaces("agent/core.py", ["Agent", "chat", "reset"])
        assert mem.key_interfaces["agent/core.py"] == ["Agent", "chat", "reset"]

    def test_add_project_fact(self):
        mem = CodeMemory()
        mem.add_project_fact("使用 pytest 做测试")
        assert "使用 pytest 做测试" in mem.project_facts

        # 重复添加不会重复
        mem.add_project_fact("使用 pytest 做测试")
        assert mem.project_facts.count("使用 pytest 做测试") == 1

    def test_remove_file(self):
        mem = CodeMemory()
        mem.update_file_summary("test.py", "测试文件")
        mem.update_key_interfaces("test.py", ["TestClass"])
        mem.known_files = ["test.py"]

        ok = mem.remove_file("test.py")
        assert ok is True
        assert "test.py" not in mem.file_summaries
        assert "test.py" not in mem.key_interfaces
        assert "test.py" not in mem.known_files

    def test_remove_nonexistent(self):
        mem = CodeMemory()
        assert mem.remove_file("nonexistent.py") is False

    def test_update_from_scan(self):
        mem = CodeMemory()
        scan_result = {
            "a.py": "模块A",
            "b.py": "模块B",
        }
        mem.update_from_scan(scan_result)
        assert mem.file_summaries["a.py"] == "模块A"
        assert mem.file_summaries["b.py"] == "模块B"

    def test_get_context_empty(self):
        mem = CodeMemory()
        assert mem.get_context() == ""

    def test_get_context_with_data(self):
        mem = CodeMemory()
        mem.update_file_summary("core.py", "核心模块")
        mem.update_key_interfaces("core.py", ["Agent", "chat"])
        mem.add_project_fact("使用 Python")

        ctx = mem.get_context()
        assert "代码库记忆" in ctx
        assert "core.py" in ctx
        assert "核心模块" in ctx
        assert "关键接口" in ctx
        assert "Agent" in ctx
        assert "项目事实" in ctx
        assert "Python" in ctx

    def test_should_refresh(self):
        mem = CodeMemory()
        mem.update_file_summary("a.py", "模块A")

        assert mem.should_refresh(["a.py"]) is False
        assert mem.should_refresh(["b.py"]) is True

    def test_get_file_summary(self):
        mem = CodeMemory()
        mem.update_file_summary("test.py", "测试")
        assert mem.get_file_summary("test.py") == "测试"
        assert mem.get_file_summary("nonexistent.py") is None

    def test_get_file_interfaces(self):
        mem = CodeMemory()
        mem.update_key_interfaces("test.py", ["fn1", "fn2"])
        assert mem.get_file_interfaces("test.py") == ["fn1", "fn2"]
        assert mem.get_file_interfaces("nonexistent.py") == []

    def test_clear(self):
        mem = CodeMemory()
        mem.update_file_summary("a.py", "A")
        mem.add_project_fact("fact")
        mem.file_hashes = {"a.py": "abc"}
        mem.known_files = ["a.py"]
        mem.clear()
        assert mem.file_count == 0
        assert mem.tracked_file_count == 0
        assert mem.project_facts == []
        assert mem.file_hashes == {}

    def test_file_count(self):
        mem = CodeMemory()
        assert mem.file_count == 0
        mem.update_file_summary("a.py", "A")
        mem.update_file_summary("b.py", "B")
        assert mem.file_count == 2

    def test_tracked_file_count(self):
        mem = CodeMemory()
        assert mem.tracked_file_count == 0
        mem.known_files = ["a.py", "b.py"]
        assert mem.tracked_file_count == 2


class TestCodeMemoryPersistence:
    """CodeMemory 持久化测试。"""

    def test_to_dict(self):
        mem = CodeMemory()
        mem.update_file_summary("a.py", "A")
        mem.file_hashes = {"a.py": "abc123"}
        mem.file_mtimes = {"a.py": 1234567890.0}
        mem.known_files = ["a.py"]
        data = mem.to_dict()
        assert "file_summaries" in data
        assert "file_hashes" in data
        assert "file_mtimes" in data
        assert "known_files" in data
        assert data["file_hashes"]["a.py"] == "abc123"

    def test_from_dict(self):
        data = {
            "file_summaries": {"b.py": "B"},
            "key_interfaces": {"b.py": ["fn"]},
            "project_facts": ["fact1"],
            "last_updated": "2024-01-01",
            "file_hashes": {"b.py": "def456"},
            "file_mtimes": {"b.py": 1234567890.0},
            "known_files": ["b.py"],
        }
        mem = CodeMemory.from_dict(data)
        assert mem.file_summaries["b.py"] == "B"
        assert mem.key_interfaces["b.py"] == ["fn"]
        assert mem.file_hashes["b.py"] == "def456"
        assert mem.known_files == ["b.py"]

    def test_from_dict_missing_fields(self):
        """向后兼容：旧格式数据缺少新字段时不报错。"""
        data = {
            "file_summaries": {"a.py": "A"},
            "project_facts": [],
            "last_updated": "2024-01-01",
        }
        mem = CodeMemory.from_dict(data)
        assert mem.file_hashes == {}
        assert mem.known_files == []

    def test_save_and_load(self):
        # 保存
        mem = CodeMemory()
        mem.update_file_summary("test.py", "测试文件")
        mem.add_project_fact("测试事实")
        mem.file_hashes = {"test.py": "hash123"}
        mem.known_files = ["test.py"]
        path = mem.save()
        assert path.exists()

        # 加载
        mem2 = CodeMemory.load()
        assert mem2.file_summaries.get("test.py") == "测试文件"
        assert "测试事实" in mem2.project_facts
        assert mem2.file_hashes.get("test.py") == "hash123"
        assert "test.py" in mem2.known_files

        # 清理
        path.unlink(missing_ok=True)

    def test_load_nonexistent(self):
        # 确保文件不存在
        if MEMORY_FILE.exists():
            MEMORY_FILE.unlink()
        mem = CodeMemory.load()
        assert mem.file_count == 0


class TestFileFiltering:
    """文件过滤规则测试。"""

    def test_ignored_dirs(self):
        assert _is_ignored_dir(".git") is True
        assert _is_ignored_dir("node_modules") is True
        assert _is_ignored_dir("__pycache__") is True
        assert _is_ignored_dir(".venv") is True
        assert _is_ignored_dir("src") is False
        assert _is_ignored_dir("agent") is False

    def test_ignored_files(self):
        assert _is_ignored_file("main.pyc") is True
        assert _is_ignored_file("lib.so") is True
        assert _is_ignored_file("app.exe") is True
        assert _is_ignored_file("package-lock.json") is True
        assert _is_ignored_file(".DS_Store") is True
        assert _is_ignored_file("main.py") is False
        assert _is_ignored_file("core.py") is False

    def test_tracked_extensions(self):
        assert _is_tracked_extension("main.py") is True
        assert _is_tracked_extension("app.js") is True
        assert _is_tracked_extension("core.ts") is True
        assert _is_tracked_extension("style.css") is True
        assert _is_tracked_extension("config.json") is True
        assert _is_tracked_extension("data.yaml") is True
        assert _is_tracked_extension("Makefile") is True
        assert _is_tracked_extension("image.png") is False
        assert _is_tracked_extension("data.csv") is False
        assert _is_tracked_extension("archive.zip") is False


class TestComputeHash:
    """文件哈希计算测试。"""

    def test_compute_hash_real_file(self):
        """测试真实文件的哈希计算。"""
        # 使用项目中实际存在的文件
        test_file = config.WORKSPACE_DIR / "config.py"
        if test_file.exists():
            h = _compute_file_hash(test_file)
            assert h != ""
            assert len(h) == 32  # MD5 长度

    def test_compute_hash_nonexistent(self):
        """不存在的文件返回空字符串。"""
        h = _compute_file_hash(Path("/nonexistent/file.py"))
        assert h == ""


class TestQuickScan:
    """快速扫描测试。"""

    def test_quick_scan_returns_dict(self):
        result = quick_scan()
        assert isinstance(result, dict)

    def test_quick_scan_excludes_ignored(self):
        result = quick_scan()
        for fp in result:
            assert "__pycache__" not in fp
            # 检查 .git 目录（不包含 .gitignore 等文件）
            assert "/.git/" not in fp and not fp.startswith(".git/")
            assert "node_modules" not in fp
            assert not fp.endswith(".pyc")

    def test_quick_scan_includes_source(self):
        result = quick_scan()
        # 项目有 config.py，应该被扫描到
        py_files = [fp for fp in result if fp.endswith(".py")]
        assert len(py_files) > 0


class TestChangeDetection:
    """文件变更检测测试。"""

    def test_detect_changes_no_memory(self):
        """空记忆时，所有文件都是新增。"""
        mem = CodeMemory()
        changes = mem.detect_changes()
        assert len(changes["new_files"]) > 0
        assert changes["deleted_files"] == []
        assert changes["modified_files"] == []

    def test_detect_changes_unchanged(self):
        """文件未变时，全部在 unchanged 中。"""
        mem = CodeMemory()
        # 先刷新一次，建立基线
        mem.refresh_from_scan()
        # 再次检测，应该没有变更
        changes = mem.detect_changes()
        assert changes["new_files"] == []
        assert changes["deleted_files"] == []
        assert changes["modified_files"] == []
        assert len(changes["unchanged_files"]) > 0

    def test_detect_changes_new_file(self):
        """新增文件被检测到。"""
        mem = CodeMemory()
        mem.known_files = ["config.py"]
        mem.file_hashes = {"config.py": "old_hash"}
        changes = mem.detect_changes()
        # 除了 config.py，其他文件都是新增
        assert len(changes["new_files"]) > 0

    def test_detect_changes_deleted_file(self):
        """已删除文件被检测到。"""
        mem = CodeMemory()
        mem.known_files = ["nonexistent_file_xyz.py", "config.py"]
        mem.file_hashes = {"nonexistent_file_xyz.py": "abc", "config.py": "def"}
        changes = mem.detect_changes()
        assert "nonexistent_file_xyz.py" in changes["deleted_files"]

    def test_detect_changes_modified_file(self):
        """修改的文件被检测到（hash 不匹配）。"""
        mem = CodeMemory()
        mem.refresh_from_scan()
        # 手动篡改一个 hash
        if mem.known_files:
            target = mem.known_files[0]
            mem.file_hashes[target] = "tampered_hash_value"
            changes = mem.detect_changes()
            assert target in changes["modified_files"]

    def test_refresh_from_scan(self):
        """完整刷新流程。"""
        mem = CodeMemory()
        changes = mem.refresh_from_scan()
        assert "new_files" in changes
        assert "deleted_files" in changes
        assert "modified_files" in changes
        assert "unchanged_files" in changes
        assert mem.tracked_file_count > 0

    def test_refresh_clears_stale_summaries(self):
        """刷新后，已修改文件的摘要被清除。"""
        mem = CodeMemory()
        mem.refresh_from_scan()

        # 手动设置一个摘要
        if mem.known_files:
            target = mem.known_files[0]
            mem.update_file_summary(target, "旧摘要")
            assert mem.file_summaries.get(target) == "旧摘要"

            # 篡改 hash 模拟文件被修改
            mem.file_hashes[target] = "fake_hash"

            # 刷新
            mem.refresh_from_scan()
            # 摘要应该被清除
            assert mem.file_summaries.get(target) is None

    def test_invalidate_stale_memories(self):
        """清理过期记忆。"""
        mem = CodeMemory()
        mem.file_summaries["ghost.py"] = "幽灵文件"
        mem.file_hashes["ghost.py"] = "abc"

        stale = mem.invalidate_stale_memories()
        assert "ghost.py" in stale
        assert "ghost.py" not in mem.file_summaries
