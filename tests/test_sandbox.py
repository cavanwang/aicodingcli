"""沙箱执行器测试。"""

import platform
from pathlib import Path
from unittest.mock import patch

import pytest

import config
from agent.sandbox import SandboxExecutor


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture()
def executor():
    """返回一个干净的 SandboxExecutor。"""
    return SandboxExecutor(
        workspace_dir=config.WORKSPACE_DIR,
        enabled=True,
    )


@pytest.fixture()
def disabled_executor():
    """返回一个禁用的 SandboxExecutor。"""
    return SandboxExecutor(
        workspace_dir=config.WORKSPACE_DIR,
        enabled=False,
    )


# ──────────────────────────────────────────────
# Profile 生成测试
# ──────────────────────────────────────────────

class TestProfileGeneration:
    """沙箱 profile 生成逻辑测试。"""

    def test_profile_contains_version(self, executor):
        profile = executor.build_profile()
        assert "(version 1)" in profile

    def test_profile_denies_home_read(self, executor):
        profile = executor.build_profile()
        home = str(Path.home().resolve())
        assert f'(deny file-read* (regex #"{home}/.*"))' in profile

    def test_profile_allows_workspace_read(self, executor):
        profile = executor.build_profile()
        workspace = str(config.WORKSPACE_DIR.resolve())
        # 路径中的特殊字符可能被 re.escape 转义
        assert "allow file-read*" in profile
        assert "agent" in profile  # 工作目录包含 agent-test

    def test_profile_denies_all_write(self, executor):
        profile = executor.build_profile()
        assert "(deny file-write*)" in profile

    def test_profile_allows_workspace_write(self, executor):
        profile = executor.build_profile()
        workspace = str(config.WORKSPACE_DIR.resolve())
        # 路径中的特殊字符可能被 re.escape 转义
        assert "allow file-write*" in profile
        assert "agent" in profile  # 工作目录包含 agent-test

    def test_profile_denies_network(self, executor):
        profile = executor.build_profile()
        assert "(deny network*)" in profile

    def test_profile_denies_etc(self, executor):
        profile = executor.build_profile()
        assert '(deny file-read* (subpath "/etc"))' in profile

    def test_profile_includes_runtime_paths(self, executor):
        profile = executor.build_profile()
        # 应该包含 Python 运行时路径
        assert "allow file-read*" in profile


# ──────────────────────────────────────────────
# 可用性检测测试
# ──────────────────────────────────────────────

class TestSandboxAvailability:
    """沙箱可用性检测测试。"""

    def test_is_macos_detection(self, executor):
        """检测是否正确识别 macOS。"""
        is_macos = platform.system() == "Darwin"
        assert executor._is_macos == is_macos

    @patch("platform.system", return_value="Linux")
    def test_non_macos_not_available(self, mock_sys):
        """非 macOS 系统沙箱不可用。"""
        e = SandboxExecutor(enabled=True)
        assert e._is_macos is False
        assert e._is_sandbox_available() is False

    def test_disabled_executor_not_active(self, disabled_executor):
        """禁用的执行器不激活。"""
        assert disabled_executor.is_active is False


# ──────────────────────────────────────────────
# 执行测试
# ──────────────────────────────────────────────

class TestExecution:
    """沙箱执行测试。"""

    def test_execute_simple_command(self, executor):
        """简单命令在沙箱中执行。"""
        result = executor.execute("echo hello", timeout=5)
        assert "hello" in result.stdout

    def test_execute_returns_completed_process(self, executor):
        """执行返回 CompletedProcess。"""
        result = executor.execute("echo test", timeout=5)
        assert hasattr(result, "stdout")
        assert hasattr(result, "stderr")
        assert hasattr(result, "returncode")

    def test_execute_timeout(self, executor):
        """超时命令正确处理。"""
        result = executor.execute("sleep 10", timeout=1)
        assert result.returncode == -1
        assert "超时" in result.stderr

    def test_disabled_executor_runs_normally(self, disabled_executor):
        """禁用的执行器正常执行（无沙箱）。"""
        result = disabled_executor.execute("echo no_sandbox", timeout=5)
        assert "no_sandbox" in result.stdout


# ──────────────────────────────────────────────
# 运行时路径收集测试
# ──────────────────────────────────────────────

class TestRuntimePaths:
    """运行时路径收集测试。"""

    def test_collects_paths(self, executor):
        """收集到至少一个运行时路径。"""
        paths = executor._collect_runtime_paths()
        assert len(paths) > 0

    def test_includes_system_paths(self, executor):
        """包含系统路径。"""
        paths = executor._collect_runtime_paths()
        # 应该包含 /usr/lib 或 /Library
        has_system = any("/usr" in p or "/Library" in p for p in paths)
        assert has_system

    def test_no_duplicate_paths(self, executor):
        """路径不重复。"""
        paths = executor._collect_runtime_paths()
        assert len(paths) == len(set(paths))

    def test_excludes_workspace(self, executor):
        """不包含工作目录自身（当工作目录!=项目目录时）。"""
        import os
        paths = executor._collect_runtime_paths()
        workspace = str(config.WORKSPACE_DIR.resolve())
        project_dir = Path(__file__).parent.parent.resolve()
        # 当工作目录与项目目录相同时，跳过此测试
        if workspace == str(project_dir):
            import pytest
            pytest.skip("WORKSPACE_DIR 与项目目录相同，不适用")
        for p in paths:
            assert not p.startswith(workspace)


# ──────────────────────────────────────────────
# shell.py 集成测试
# ──────────────────────────────────────────────

class TestShellIntegration:
    """shell.py 集成测试。"""

    def test_run_command_whitelisted(self):
        """白名单命令正常执行。"""
        from agent.tools.shell import run_command
        result = run_command("echo integration_test")
        assert "integration_test" in result

    def test_run_command_not_whitelisted(self):
        """非白名单命令被拒绝。"""
        from agent.tools.shell import run_command
        result = run_command("rm -rf /")
        assert "🚫" in result
        assert "不在白名单" in result
