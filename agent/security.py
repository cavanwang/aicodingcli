"""危险命令检测与资源限制。

安全机制：
1. 危险命令黑名单：正则匹配高危命令模式
2. 资源限制：通过 resource.setrlimit 限制子进程内存

存储位置：无（纯逻辑模块，无状态）
"""

from __future__ import annotations

import re
import resource
import sys
from dataclasses import dataclass

import config
from agent.logger import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# 危险命令黑名单
# ──────────────────────────────────────────────

@dataclass
class SecurityCheckResult:
    """安全检查结果。"""

    passed: bool
    reason: str = ""
    pattern: str = ""

    @property
    def blocked(self) -> bool:
        return not self.passed


# 内置危险命令模式（正则表达式）
BUILTIN_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    # (正则模式, 说明)
    (r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+/", "rm -rf 根目录或绝对路径"),
    (r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+\*", "rm -rf 通配符"),
    (r"sudo\s+", "sudo 提权执行"),
    (r"chmod\s+777\s+", "chmod 777 全权限"),
    (r"chmod\s+\+s\s+", "chmod +s SUID 位"),
    (r"dd\s+if=", "dd 磁盘写入"),
    (r"mkfs\.", "mkfs 格式化文件系统"),
    (r"fdisk\s+", "fdisk 磁盘分区"),
    (r">\s*/dev/sd", "写入磁盘设备"),
    (r">\s*/dev/nvme", "写入 NVMe 设备"),
    (r"curl.*\|\s*(bash|sh|zsh)", "管道执行远程脚本 (curl)"),
    (r"wget.*\|\s*(bash|sh|zsh)", "管道执行远程脚本 (wget)"),
    (r":\(\)\s*\{", "fork bomb"),
    (r"kill\s+-9\s+0", "kill 所有进程"),
    (r"killall\s+-9", "killall 强制终止"),
    (r"mkfs\s+", "mkfs 格式化"),
    (r"format\s+[a-zA-Z]:", "Windows 格式化"),
    (r"reg\s+delete", "Windows 注册表删除"),
    (r"powershell.*-enc", "PowerShell 编码命令"),
    (r"eval\s+.*\$\(.*\)", "eval 嵌套命令替换"),
]


class CommandGuard:
    """危险命令检测器。

    检查命令是否匹配危险模式，支持自定义黑名单扩展。
    """

    def __init__(self, extra_patterns: list[str] | None = None) -> None:
        """初始化命令守卫。

        Args:
            extra_patterns: 额外的危险命令正则模式列表
        """
        self._patterns: list[tuple[re.Pattern, str]] = []

        # 加载内置模式
        for pattern, description in BUILTIN_DANGEROUS_PATTERNS:
            self._patterns.append((re.compile(pattern, re.IGNORECASE), description))

        # 加载用户自定义模式
        if extra_patterns:
            for pattern in extra_patterns:
                self._patterns.append((re.compile(pattern, re.IGNORECASE), "自定义规则"))

        # 从配置加载额外模式
        if hasattr(config, "DANGEROUS_COMMANDS_EXTRA"):
            for pattern in config.DANGEROUS_COMMANDS_EXTRA:
                self._patterns.append((re.compile(pattern, re.IGNORECASE), "配置规则"))

    def check(self, command: str) -> SecurityCheckResult:
        """检查命令是否安全。

        Args:
            command: 要检查的命令字符串

        Returns:
            SecurityCheckResult: 检查结果
        """
        if not command or not command.strip():
            return SecurityCheckResult(passed=True)

        cmd = command.strip()

        for pattern, description in self._patterns:
            if pattern.search(cmd):
                logger.warning("危险命令被拦截: %s (匹配: %s)", cmd[:100], description)
                return SecurityCheckResult(
                    passed=False,
                    reason=f"🚨 危险命令被拦截: {description}\n   命令: {cmd[:100]}",
                    pattern=pattern.pattern,
                )

        return SecurityCheckResult(passed=True)

    @property
    def pattern_count(self) -> int:
        """当前加载的模式数量。"""
        return len(self._patterns)


# ──────────────────────────────────────────────
# 资源限制
# ──────────────────────────────────────────────

# 默认内存限制：1GB
DEFAULT_MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024


def set_memory_limit(limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES) -> None:
    """设置当前进程的虚拟内存限制。

    用于 subprocess 的 preexec_fn，限制子进程内存使用。

    Args:
        limit_bytes: 内存上限（字节），默认 1GB
    """
    try:
        resource.setrlimit(
            resource.RLIMIT_AS,
            (limit_bytes, limit_bytes),
        )
    except (ValueError, resource.error) as e:
        logger.debug("设置内存限制失败: %s", e)


def set_resource_limits(
    memory_limit: int = DEFAULT_MEMORY_LIMIT_BYTES,
) -> callable | None:
    """获取资源限制的 preexec_fn。

    用于 subprocess.run 的 preexec_fn 参数。

    Args:
        memory_limit: 内存上限（字节）

    Returns:
        可调用对象，或 None（不支持的平台）
    """
    # Windows 不支持 resource 模块
    if sys.platform == "win32":
        logger.debug("Windows 不支持 resource 限制")
        return None

    def _preexec():
        set_memory_limit(memory_limit)

    return _preexec


def get_memory_limit_info() -> dict[str, str]:
    """获取当前内存限制信息。

    Returns:
        包含 soft/hard 限制的字典
    """
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        return {
            "soft": f"{soft / (1024**3):.1f}GB" if soft != resource.RLIM_INFINITY else "unlimited",
            "hard": f"{hard / (1024**3):.1f}GB" if hard != resource.RLIM_INFINITY else "unlimited",
        }
    except (ValueError, resource.error):
        return {"soft": "unknown", "hard": "unknown"}


# ──────────────────────────────────────────────
# 模块级单例
# ──────────────────────────────────────────────

_guard: CommandGuard | None = None


def get_command_guard() -> CommandGuard:
    """获取全局命令守卫实例（延迟初始化）。"""
    global _guard
    if _guard is None:
        _guard = CommandGuard()
    return _guard


def check_command(command: str) -> SecurityCheckResult:
    """检查命令是否安全（便捷函数）。

    Args:
        command: 要检查的命令字符串

    Returns:
        SecurityCheckResult: 检查结果
    """
    return get_command_guard().check(command)
