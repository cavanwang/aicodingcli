"""精确编辑工具：搜索替换。"""

from pathlib import Path
import config
from agent.tools.file_ops import _safe_path


def edit_file(file_path: str, old_text: str, new_text: str) -> str:
    """在文件中找到 old_text，替换为 new_text。"""
    path = _safe_path(file_path)
    if not path.exists():
        return f"文件不存在: {file_path}"

    content = path.read_text(encoding="utf-8")

    count = content.count(old_text)
    if count == 0:
        return f"❌ 未找到要替换的文本。请确认 old_text 与文件内容完全一致（含缩进和换行）。"
    if count > 1:
        return f"❌ 匹配到 {count} 处，请提供更多上下文使 old_text 唯一。"

    new_content = content.replace(old_text, new_text, 1)
    path.write_text(new_content, encoding="utf-8")
    return f"✅ 已替换 {file_path} 中的 1 处内容"