"""macOS sandbox-exec 沙箱执行器。

通过内核级隔离确保 Agent 执行的命令只能：
- 读取工作目录 + Python/Node 运行时路径
- 写入工作目录
- 无法访问 $HOME 下其他文件（凭据、个人文件等）
- 无法进行网络通信

存储位置：无（profile 内联传递，不落盘）
"""

from __future__ import annotations

import platform
import re
import subprocess
from pathlib import Path

import config
from agent.logger import get_logger

logger = get_logger(__name__)


class SandboxExecutor:
    """macOS sandbox-exec 沙箱执行器。

    安全策略：
    - 读取：禁止 $HOME 下所有文件，仅放行项目目录和 Python 运行时
    - 写入：禁止一切，仅放行工作目录
    - 网络：完全禁止
    """

    def __init__(
        self,
        workspace_dir: Path | None = None,
        enabled: bool = True,
    ) -> None:
        self.workspace_dir = (workspace_dir or config.WORKSPACE_DIR).resolve()
        self.enabled = enabled
        self._is_macos = platform.system() == "Darwin"

    # ── Profile 生成 ──

    def build_profile(self) -> str:
        """动态生成 sandbox-exec profile（Scheme 语法）。

        规则（按匹配优先级从上到下）：
        1. allow default — 默认放行（读取系统库等）
        2. deny file-read* HOME — 禁止读取 $HOME 下所有文件
        3. allow file-read* 项目目录 — 放行工作目录
        4. allow file-read* Python 运行时 — 放行 Python/Node 路径
        5. deny file-read* /etc — 禁止读取系统配置
        6. deny file-write* — 禁止一切写入
        7. allow file-write* 工作目录 — 仅放行写入工作目录
        8. deny network* — 禁止网络
        """
        home = Path.home().resolve()
        workspace = str(self.workspace_dir)

        # 收集需要放行的 Python 运行时路径
        runtime_paths = self._collect_runtime_paths()

        lines = [
            "(version 1)",
            "(allow default)",
            "",
            "; ── 读取控制 ──",
            f"; 禁止读取 $HOME 下所有文件",
            f'(deny file-read* (regex #"{re.escape(str(home))}/.*"))',
            "",
            "; 放行工作目录（可能在 $HOME 外，如 /tmp/agent-test）",
            f'(allow file-read* (regex #"{re.escape(workspace)}/.*"))',
            "",
            "; 放行 Python/Node 运行时路径",
        ]

        for rp in runtime_paths:
            lines.append(f'(allow file-read* (regex #"{re.escape(rp)}/.*"))')

        lines.extend([
            "",
            "; 禁止读取系统配置",
            '(deny file-read* (subpath "/etc"))',
            '(deny file-read* (subpath "/private/etc"))',
            "",
            "; ── 写入控制 ──",
            "; 禁止一切写入",
            "(deny file-write*)",
            "; 仅放行写入工作目录",
            f'(allow file-write* (regex #"{re.escape(workspace)}/.*"))',
            "",
            "; ── 网络控制 ──",
            "; 完全禁止网络访问",
            "(deny network*)",
        ])

        return "\n".join(lines)

    def _collect_runtime_paths(self) -> list[str]:
        """收集 Python/Node 运行时需要的读取路径。"""
        import sys

        paths: list[str] = []

        # Python 可执行文件所在目录的父级（如 .venv 或 miniconda）
        python_home = Path(sys.executable).resolve()
        # 向上找到 venv 或 conda 根目录
        for parent in python_home.parents:
            if parent.name in (".venv", "venv"):
                paths.append(str(parent.parent))
                break
            # conda/miniconda/anaconda
            if parent.name.startswith(("miniconda", "anaconda", "conda")):
                paths.append(str(parent))
                break
            # 如果是系统 Python（/usr/bin/python3），放行 /usr
            if str(parent) == "/usr":
                paths.append("/usr")
                break

        # sys.path 中的额外路径
        for p in sys.path:
            if not p:
                continue
            rp = str(Path(p).resolve())
            # 只添加非工作目录的路径
            if rp.startswith(str(self.workspace_dir)):
                continue
            # 去重
            if rp not in paths:
                paths.append(rp)

        # 系统级路径
        for sys_path in ["/usr/lib", "/Library"]:
            if sys_path not in paths:
                paths.append(sys_path)

        return paths

    # ── 执行 ──

    def execute(
        self,
        command: str,
        timeout: int = 30,
        cwd: Path | None = None,
        preexec_fn: callable | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """在沙箱中执行命令。

        Args:
            command: 要执行的 shell 命令
            timeout: 超时秒数
            cwd: 工作目录（默认使用 workspace_dir）
            preexec_fn: 子进程启动前的回调函数（用于资源限制等）

        Returns:
            CompletedProcess 对象
        """
        if not self.enabled or not self._is_sandbox_available():
            return self._execute_normal(command, timeout, cwd, preexec_fn)

        profile = self.build_profile()
        sandboxed_cmd = f"sandbox-exec -p '{profile}' {command}"

        logger.debug("沙箱执行: %s", command[:100])

        try:
            result = subprocess.run(
                sandboxed_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(cwd or self.workspace_dir),
                preexec_fn=preexec_fn,
            )
            return result
        except subprocess.TimeoutExpired:
            # 返回一个超时的 CompletedProcess
            return subprocess.CompletedProcess(
                args=command,
                returncode=-1,
                stdout="",
                stderr=f"命令超时 ({timeout}s)",
            )
        except Exception as e:
            return subprocess.CompletedProcess(
                args=command,
                returncode=-1,
                stdout="",
                stderr=f"沙箱执行失败: {e}",
            )

    def _execute_normal(
        self,
        command: str,
        timeout: int,
        cwd: Path | None,
        preexec_fn: callable | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """非沙箱模式执行（降级或沙箱不可用时）。"""
        logger.debug("普通执行（无沙箱）: %s", command[:100])
        try:
            return subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(cwd or self.workspace_dir),
                preexec_fn=preexec_fn,
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                args=command,
                returncode=-1,
                stdout="",
                stderr=f"命令超时 ({timeout}s)",
            )
        except Exception as e:
            return subprocess.CompletedProcess(
                args=command,
                returncode=-1,
                stdout="",
                stderr=f"执行失败: {e}",
            )

    # ── 可用性检测 ──

    def _is_sandbox_available(self) -> bool:
        """检测 sandbox-exec 是否可用。"""
        if not self._is_macos:
            return False
        try:
            result = subprocess.run(
                ["sandbox-exec", "-p", "(version 1)(allow default)", "true"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @property
    def is_active(self) -> bool:
        """沙箱是否处于激活状态。"""
        return self.enabled and self._is_sandbox_available()
