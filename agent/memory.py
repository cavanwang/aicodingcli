"""跨会话代码记忆：维护对代码库的心理模型。

存储位置：~/.aicoding/memory/project_memory.json

支持文件变更检测：
- 记录文件内容哈希（MD5）和修改时间戳
- 维护已知项目文件列表（过滤构建产物等无关文件）
- 启动时快速扫描，检测新增/删除/修改的文件
- 自动清理过期记忆
"""

from __future__ import annotations

import hashlib
import fnmatch
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import config

MEMORY_DIR = Path.home() / ".aicoding" / "memory"
MEMORY_FILE = MEMORY_DIR / "project_memory.json"

# 最大跟踪文件数
_MAX_TRACKED_FILES = 500

# ──────────────────────────────────────────────
# 文件过滤规则
# ──────────────────────────────────────────────

# 排除的目录
IGNORE_DIRS: set[str] = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".idea", ".pytest_cache", ".aicoding_recovery", ".aicoding",
    "dist", "build", ".next", "target", "bin", "obj",
    ".tox", ".eggs", "*.egg-info", ".mypy_cache", ".ruff_cache",
}

# 排除的文件名/模式
IGNORE_FILE_PATTERNS: set[str] = {
    "*.pyc", "*.pyo", "*.o", "*.so", "*.dll", "*.exe", "*.a", "*.lib",
    "*.class",                                      # Java 编译产物
    "*.wasm",                                       # WebAssembly
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",  # 锁文件
    ".DS_Store", "*.log", "*.tmp", "*.bak", "*.swp",      # 临时文件
    "*.min.js", "*.min.css",                          # 压缩文件
    "*.map",                                          # Source maps
}

# 只跟踪有意义的源码/配置文件扩展名
TRACKED_EXTENSIONS: set[str] = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs",
    ".java", ".kt", ".kts", ".rb", ".php", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".swift", ".scala", ".lua", ".r",
    ".html", ".css", ".scss", ".sass", ".less", ".vue", ".svelte",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".ini", ".cfg", ".conf",
    ".md", ".txt", ".rst",
    ".sh", ".bash", ".zsh", ".fish",
    ".sql", ".graphql", ".proto",
    ".env", ".gitignore", ".dockerignore",
    "Dockerfile", "Makefile", "CMakeLists.txt",
}


# ──────────────────────────────────────────────
# 文件过滤工具函数
# ──────────────────────────────────────────────

def _is_ignored_dir(dir_name: str) -> bool:
    """判断目录是否应被忽略。"""
    return dir_name in IGNORE_DIRS or any(
        fnmatch.fnmatch(dir_name, pat) for pat in IGNORE_DIR_PATTERNS
    )


# 额外的目录 glob 模式
IGNORE_DIR_PATTERNS: set[str] = {"*.egg-info"}


def _is_ignored_file(file_name: str) -> bool:
    """判断文件是否应被忽略。"""
    return any(
        fnmatch.fnmatch(file_name, pat) for pat in IGNORE_FILE_PATTERNS
    )


def _is_tracked_extension(file_name: str) -> bool:
    """判断文件扩展名是否在跟踪列表中。"""
    suffix = Path(file_name).suffix.lower()
    if suffix:
        return suffix in TRACKED_EXTENSIONS
    # 无扩展名的特殊文件（如 Makefile, Dockerfile）
    return file_name in TRACKED_EXTENSIONS


def _compute_file_hash(file_path: Path) -> str:
    """计算文件的 MD5 哈希值。"""
    try:
        content = file_path.read_bytes()
        return hashlib.md5(content).hexdigest()
    except (OSError, PermissionError):
        return ""


def _get_file_mtime(file_path: Path) -> float:
    """获取文件的修改时间戳。"""
    try:
        return file_path.stat().st_mtime
    except (OSError, PermissionError):
        return 0.0


# ──────────────────────────────────────────────
# 快速扫描
# ──────────────────────────────────────────────

def quick_scan(workspace: Path | None = None) -> dict[str, dict[str, Any]]:
    """快速扫描工作区，返回符合条件的项目文件信息。

    返回: {file_path: {"mtime": float, "hash": str}}
    只收集文件路径、mtime 和 hash，不读取内容。
    """
    base = workspace or config.WORKSPACE_DIR
    if not base.exists():
        return {}

    result: dict[str, dict[str, Any]] = {}
    count = 0

    for path in sorted(base.rglob("*")):
        if count >= _MAX_TRACKED_FILES:
            break

        # 跳过目录
        if path.is_dir():
            continue

        # 过滤忽略项
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if _is_ignored_file(path.name):
            continue
        if not _is_tracked_extension(path.name):
            continue

        # 计算相对路径
        try:
            rel_path = str(path.relative_to(base))
        except ValueError:
            continue

        mtime = _get_file_mtime(path)
        file_hash = _compute_file_hash(path)

        if file_hash:  # 只记录可读的文件
            result[rel_path] = {"mtime": mtime, "hash": file_hash}
            count += 1

    return result


# ──────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────

@dataclass
class CodeMemory:
    """代码库记忆：文件摘要、关键接口、项目事实、文件追踪。"""

    file_summaries: dict[str, str] = field(default_factory=dict)
    key_interfaces: dict[str, list[str]] = field(default_factory=dict)
    project_facts: list[str] = field(default_factory=list)
    last_updated: str = ""

    # 文件追踪字段
    file_hashes: dict[str, str] = field(default_factory=dict)
    file_mtimes: dict[str, float] = field(default_factory=dict)
    known_files: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.last_updated:
            self.last_updated = datetime.now().isoformat()

    # ── 持久化 ──

    def save(self) -> Path:
        """保存记忆到磁盘。"""
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self.last_updated = datetime.now().isoformat()
        MEMORY_FILE.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return MEMORY_FILE

    @classmethod
    def load(cls) -> CodeMemory:
        """从磁盘加载记忆，不存在则返回空实例。"""
        if not MEMORY_FILE.exists():
            return cls()
        try:
            data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return cls()

    # ── 序列化 ──

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_summaries": self.file_summaries,
            "key_interfaces": self.key_interfaces,
            "project_facts": self.project_facts,
            "last_updated": self.last_updated,
            "file_hashes": self.file_hashes,
            "file_mtimes": self.file_mtimes,
            "known_files": self.known_files,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CodeMemory:
        return cls(
            file_summaries=data.get("file_summaries", {}),
            key_interfaces=data.get("key_interfaces", {}),
            project_facts=data.get("project_facts", []),
            last_updated=data.get("last_updated", ""),
            file_hashes=data.get("file_hashes", {}),
            file_mtimes=data.get("file_mtimes", {}),
            known_files=data.get("known_files", []),
        )

    # ── 文件变更检测 ──

    def detect_changes(
        self, workspace: Path | None = None
    ) -> dict[str, list[str]]:
        """检测代码库相对于记忆的变更。

        返回: {
            "new_files": [...],       # 新增的文件
            "deleted_files": [...],   # 已删除的文件
            "modified_files": [...],  # 内容已修改的文件
            "unchanged_files": [...], # 未变化的文件
        }
        """
        current_files = quick_scan(workspace)
        known_set = set(self.known_files)
        current_set = set(current_files.keys())

        new_files = sorted(current_set - known_set)
        deleted_files = sorted(known_set - current_set)

        # 检测修改：对比 hash
        modified_files = []
        unchanged_files = []
        for fp in sorted(current_set & known_set):
            current_hash = current_files[fp]["hash"]
            saved_hash = self.file_hashes.get(fp, "")
            if current_hash != saved_hash:
                modified_files.append(fp)
            else:
                unchanged_files.append(fp)

        return {
            "new_files": new_files,
            "deleted_files": deleted_files,
            "modified_files": modified_files,
            "unchanged_files": unchanged_files,
        }

    def refresh_from_scan(
        self, workspace: Path | None = None
    ) -> dict[str, list[str]]:
        """执行完整刷新：扫描文件、检测变更、清理过期记忆、更新追踪。

        返回变更报告。
        """
        changes = self.detect_changes(workspace)
        current_files = quick_scan(workspace)

        # 清理已删除文件的记忆
        for fp in changes["deleted_files"]:
            self.remove_file(fp)
            self.file_hashes.pop(fp, None)
            self.file_mtimes.pop(fp, None)

        # 清理已修改文件的摘要（需要重新理解）
        for fp in changes["modified_files"]:
            self.file_summaries.pop(fp, None)
            self.key_interfaces.pop(fp, None)

        # 更新追踪信息
        self.known_files = sorted(current_files.keys())
        self.file_hashes = {fp: info["hash"] for fp, info in current_files.items()}
        self.file_mtimes = {fp: info["mtime"] for fp, info in current_files.items()}

        self.last_updated = datetime.now().isoformat()
        return changes

    def invalidate_stale_memories(self) -> list[str]:
        """清理过期记忆（文件不存在或 hash 不匹配）。

        返回被清理的文件列表。
        """
        base = config.WORKSPACE_DIR
        stale = []

        for fp in list(self.file_summaries.keys()):
            file_path = base / fp
            if not file_path.exists():
                self.remove_file(fp)
                self.file_hashes.pop(fp, None)
                self.file_mtimes.pop(fp, None)
                stale.append(fp)
            else:
                current_hash = _compute_file_hash(file_path)
                saved_hash = self.file_hashes.get(fp, "")
                if saved_hash and current_hash != saved_hash:
                    self.file_summaries.pop(fp, None)
                    self.key_interfaces.pop(fp, None)
                    self.file_hashes[fp] = current_hash
                    self.file_mtimes[fp] = _get_file_mtime(file_path)
                    stale.append(fp)

        if stale:
            self.last_updated = datetime.now().isoformat()
        return stale

    # ── 更新操作 ──

    def update_file_summary(self, file_path: str, summary: str) -> None:
        """更新单个文件的职责摘要，同时刷新哈希和 mtime。"""
        self.file_summaries[file_path] = summary

        # 同步更新追踪信息
        abs_path = config.WORKSPACE_DIR / file_path
        if abs_path.exists():
            self.file_hashes[file_path] = _compute_file_hash(abs_path)
            self.file_mtimes[file_path] = _get_file_mtime(abs_path)
            if file_path not in self.known_files:
                self.known_files.append(file_path)
                self.known_files.sort()

        self.last_updated = datetime.now().isoformat()

    def update_key_interfaces(
        self, file_path: str, interfaces: list[str]
    ) -> None:
        """更新文件的关键接口列表。"""
        self.key_interfaces[file_path] = interfaces
        self.last_updated = datetime.now().isoformat()

    def add_project_fact(self, fact: str) -> None:
        """添加一条项目级事实。"""
        if fact not in self.project_facts:
            self.project_facts.append(fact)
            self.last_updated = datetime.now().isoformat()

    def remove_file(self, file_path: str) -> bool:
        """移除文件相关记忆。"""
        removed = False
        if file_path in self.file_summaries:
            del self.file_summaries[file_path]
            removed = True
        if file_path in self.key_interfaces:
            del self.key_interfaces[file_path]
            removed = True
        if file_path in self.known_files:
            self.known_files.remove(file_path)
            removed = True
        if removed:
            self.last_updated = datetime.now().isoformat()
        return removed

    def update_from_scan(self, scan_result: dict[str, str]) -> None:
        """从项目扫描结果批量更新文件摘要。"""
        for file_path, summary in scan_result.items():
            self.file_summaries[file_path] = summary
        self.last_updated = datetime.now().isoformat()

    # ── 查询 ──

    def get_context(self) -> str:
        """生成记忆上下文字符串，用于注入 system prompt。"""
        sections = []

        if self.file_summaries:
            lines = ["## 代码库记忆"]
            for path, summary in sorted(self.file_summaries.items())[:20]:
                lines.append(f"- {path}: {summary}")
            if len(self.file_summaries) > 20:
                lines.append(f"... 及其他 {len(self.file_summaries) - 20} 个文件")
            sections.append("\n".join(lines))

        if self.key_interfaces:
            lines = ["## 关键接口"]
            for path, interfaces in sorted(self.key_interfaces.items())[:10]:
                if interfaces:
                    lines.append(f"- {path}: {', '.join(interfaces[:5])}")
            sections.append("\n".join(lines))

        if self.project_facts:
            lines = ["## 项目事实"]
            for fact in self.project_facts[:10]:
                lines.append(f"- {fact}")
            sections.append("\n".join(lines))

        if not sections:
            return ""

        return "\n\n".join(sections)

    def should_refresh(self, file_paths: list[str]) -> bool:
        """判断指定文件是否需要重新摘要（不在记忆中或已过期）。"""
        for fp in file_paths:
            if fp not in self.file_summaries:
                return True
            # 检查 hash 是否匹配
            abs_path = config.WORKSPACE_DIR / fp
            if abs_path.exists():
                current_hash = _compute_file_hash(abs_path)
                saved_hash = self.file_hashes.get(fp, "")
                if saved_hash and current_hash != saved_hash:
                    return True
        return False

    def get_file_summary(self, file_path: str) -> str | None:
        """获取指定文件的摘要。"""
        return self.file_summaries.get(file_path)

    def get_file_interfaces(self, file_path: str) -> list[str]:
        """获取指定文件的关键接口列表。"""
        return self.key_interfaces.get(file_path, [])

    def clear(self) -> None:
        """清空所有记忆。"""
        self.file_summaries.clear()
        self.key_interfaces.clear()
        self.project_facts.clear()
        self.file_hashes.clear()
        self.file_mtimes.clear()
        self.known_files.clear()
        self.last_updated = datetime.now().isoformat()

    @property
    def file_count(self) -> int:
        """已记忆的文件数。"""
        return len(self.file_summaries)

    @property
    def tracked_file_count(self) -> int:
        """已追踪的项目文件数。"""
        return len(self.known_files)
