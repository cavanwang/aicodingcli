"""按文件名/glob 模式查找文件。"""

from pathlib import Path
import config

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".idea"}


def find_files(pattern: str, dir_path: str = ".") -> str:
    """按 glob 模式查找文件，如 '*.py'、'*test*'。"""
    base = (config.WORKSPACE_DIR / dir_path).resolve()
    if not str(base).startswith(str(config.WORKSPACE_DIR)):
        return "🚫 路径越界"

    matches = []
    for p in base.rglob(pattern):
        # 跳过忽略目录
        if any(part in IGNORE_DIRS for part in p.parts):
            continue
        if p.is_file():
            matches.append(str(p.relative_to(config.WORKSPACE_DIR)))
        if len(matches) >= 50:
            break

    if not matches:
        return f"未找到匹配 '{pattern}' 的文件"
    return "\n".join(matches)