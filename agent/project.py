"""启动时自动扫描项目结构，注入上下文。"""

from pathlib import Path
import config

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
IGNORE_FILES = {".DS_Store", "package-lock.json", "yarn.lock"}


def scan_project() -> str:
    """生成项目结构摘要，作为 system prompt 的补充。"""
    lines = []
    base = config.WORKSPACE_DIR

    for p in sorted(base.rglob("*")):
        if any(part in IGNORE_DIRS for part in p.relative_to(base).parts):
            continue
        if p.name in IGNORE_FILES:
            continue
        rel = p.relative_to(base)
        if p.is_dir():
            lines.append(f"📁 {rel}/")
        else:
            lines.append(f"📄 {rel}")
        if len(lines) > 100:
            lines.append("... (更多文件省略)")
            break

    return "\n".join(lines) if lines else "(空项目)"