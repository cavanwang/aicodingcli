"""文件操作工具：读取、写入、列目录。"""

from pathlib import Path
import config


def _safe_path(file_path: str) -> Path:
    """解析相对路径，防止路径穿越。"""
    resolved = (config.WORKSPACE_DIR / file_path).resolve()
    if not str(resolved).startswith(str(config.WORKSPACE_DIR)):
        raise PermissionError(f"路径越界: {file_path}")
    return resolved


def read_file(file_path: str, start_line: int = 1, end_line: int = 0) -> str:
    """读取文件内容，带行号。end_line=0 表示读到末尾。"""
    path = _safe_path(file_path)
    if not path.exists():
        return f"文件不存在: {file_path}"

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    total = len(lines)

    if end_line == 0:
        end_line = total
    end_line = min(end_line, total)

    selected = lines[start_line - 1 : end_line]

    # 带行号输出，方便模型定位
    numbered = "".join(
        f"{i + start_line:>5} | {line}" for i, line in enumerate(selected)
    )

    header = f"[{file_path}] 共 {total} 行，显示 {start_line}-{end_line}\n"
    content = header + numbered

    if len(content) > config.MAX_FILE_READ_CHARS:
        content = content[:config.MAX_FILE_READ_CHARS] + "\n...(截断)"
    return content


def write_file(file_path: str, content: str) -> str:
    """创建新文件或覆盖已有文件。"""
    path = _safe_path(file_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"✅ 已写入 {file_path} ({len(content)} 字符)"
    except Exception as e:
        return f"写入失败: {e}"


def list_directory(dir_path: str = ".") -> str:
    """列出目录下的文件和子目录。"""
    path = _safe_path(dir_path)
    if not path.exists():
        return f"目录不存在: {dir_path}"
    if not path.is_dir():
        return f"不是目录: {dir_path}"
    entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
    lines = [f"{'📁' if e.is_dir() else '📄'} {e.name}" for e in entries]
    return "\n".join(lines) if lines else "(空目录)"
