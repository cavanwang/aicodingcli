"""项目级配置加载器测试。"""

import pytest
from pathlib import Path
from unittest.mock import patch

from agent.project_config import (
    find_project_config,
    load_global_config,
    load_project_config,
    build_project_prompt,
    PROJECT_CONFIG_NAMES,
    GLOBAL_CONFIG_PATH,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture()
def project_dir(tmp_path):
    """临时项目目录。"""
    return tmp_path


@pytest.fixture()
def no_global_config():
    """确保全局配置不存在。"""
    with patch("agent.project_config.GLOBAL_CONFIG_PATH", Path("/nonexistent/config.md")):
        yield


# ──────────────────────────────────────────────
# find_project_config 测试
# ──────────────────────────────────────────────

class TestFindProjectConfig:
    """find_project_config() 测试。"""

    def test_find_agent_md(self, project_dir):
        """找到 .agent.md。"""
        config_file = project_dir / ".agent.md"
        config_file.write_text("# config")
        result = find_project_config(project_dir)
        assert result == config_file

    def test_find_AGENT_md(self, project_dir):
        """找到 AGENT.md。"""
        config_file = project_dir / "AGENT.md"
        config_file.write_text("# config")
        result = find_project_config(project_dir)
        assert result == config_file

    def test_prefer_agent_md_over_AGENT_md(self, project_dir):
        """.agent.md 优先于 AGENT.md。"""
        agent_md = project_dir / ".agent.md"
        agent_md.write_text("# .agent.md")
        AGENT_md = project_dir / "AGENT.md"
        AGENT_md.write_text("# AGENT.md")

        result = find_project_config(project_dir)
        assert result == agent_md

    def test_return_none_when_not_found(self, project_dir):
        """无配置文件时返回 None。"""
        result = find_project_config(project_dir)
        assert result is None

    def test_ignore_directory(self, project_dir):
        """目录不算配置文件。"""
        (project_dir / ".agent.md").mkdir()
        result = find_project_config(project_dir)
        assert result is None


# ──────────────────────────────────────────────
# load_global_config 测试
# ──────────────────────────────────────────────

class TestLoadGlobalConfig:
    """load_global_config() 测试。"""

    def test_load_existing(self, tmp_path):
        """加载存在的全局配置。"""
        config_file = tmp_path / "config.md"
        config_file.write_text("# 全局配置\n\n共用规则")

        with patch("agent.project_config.GLOBAL_CONFIG_PATH", config_file):
            content = load_global_config()
            assert "全局配置" in content
            assert "共用规则" in content

    def test_return_empty_when_missing(self):
        """不存在时返回空字符串。"""
        with patch("agent.project_config.GLOBAL_CONFIG_PATH", Path("/nonexistent")):
            content = load_global_config()
            assert content == ""

    def test_return_empty_on_read_error(self, tmp_path):
        """读取失败时返回空字符串。"""
        config_file = tmp_path / "config.md"
        config_file.write_text("content")

        with patch("agent.project_config.GLOBAL_CONFIG_PATH", config_file):
            with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
                content = load_global_config()
                assert content == ""


# ──────────────────────────────────────────────
# load_project_config 测试
# ──────────────────────────────────────────────

class TestLoadProjectConfig:
    """load_project_config() 测试。"""

    def test_load_existing(self, project_dir):
        """加载存在的项目配置。"""
        config_file = project_dir / ".agent.md"
        config_file.write_text("# 项目配置\n\n项目规则")

        content = load_project_config(project_dir)
        assert "项目配置" in content
        assert "项目规则" in content

    def test_return_empty_when_missing(self, project_dir):
        """不存在时返回空字符串。"""
        content = load_project_config(project_dir)
        assert content == ""

    def test_return_empty_on_read_error(self, project_dir):
        """读取失败时返回空字符串。"""
        config_file = project_dir / ".agent.md"
        config_file.write_text("content")

        with patch.object(Path, "read_text", side_effect=IOError("fail")):
            content = load_project_config(project_dir)
            assert content == ""


# ──────────────────────────────────────────────
# build_project_prompt 测试
# ──────────────────────────────────────────────

class TestBuildProjectPrompt:
    """build_project_prompt() 测试。"""

    def test_no_config_returns_empty(self, project_dir, no_global_config):
        """无配置时返回空。"""
        result = build_project_prompt(project_dir)
        assert result == ""

    def test_project_only(self, project_dir, no_global_config):
        """只有项目配置。"""
        (project_dir / ".agent.md").write_text("# 项目规则\n\n用 Python 3.12")

        result = build_project_prompt(project_dir)
        assert "项目专属配置" in result
        assert "Python 3.12" in result
        assert "全局项目配置" not in result

    def test_global_only(self, project_dir, tmp_path):
        """只有全局配置。"""
        global_config = tmp_path / "config.md"
        global_config.write_text("# 全局规则\n\n统一风格")

        with patch("agent.project_config.GLOBAL_CONFIG_PATH", global_config):
            result = build_project_prompt(project_dir)
            assert "全局项目配置" in result
            assert "统一风格" in result
            assert "项目专属配置" not in result

    def test_both_global_and_project(self, project_dir, tmp_path):
        """全局 + 项目配置都存在。"""
        global_config = tmp_path / "config.md"
        global_config.write_text("全局规则")
        (project_dir / ".agent.md").write_text("项目规则")

        with patch("agent.project_config.GLOBAL_CONFIG_PATH", global_config):
            result = build_project_prompt(project_dir)
            assert "全局项目配置" in result
            assert "全局规则" in result
            assert "项目专属配置" in result
            assert "项目规则" in result

    def test_project_after_global(self, project_dir, tmp_path):
        """项目配置在全局配置之后。"""
        global_config = tmp_path / "config.md"
        global_config.write_text("GLOBAL")
        (project_dir / ".agent.md").write_text("PROJECT")

        with patch("agent.project_config.GLOBAL_CONFIG_PATH", global_config):
            result = build_project_prompt(project_dir)
            global_pos = result.find("GLOBAL")
            project_pos = result.find("PROJECT")
            assert global_pos < project_pos
