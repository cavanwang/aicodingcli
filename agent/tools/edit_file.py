"""精确编辑工具：搜索替换，编辑后自动回读改动区域上下文。"""

from pathlib import Path
import config
from agent.tools.file_ops import _safe_path

# 编辑后回读的上下文行数
_CONTEXT_LINES = 20


def edit_file(file_path: str, old_text: str, new_text: str) -> str:
    """在文件中找到 old_text，替换为 new_text，并回读改动区域上下文。"""
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

    # 回读改动区域上下文
    context = _build_context(file_path, new_content, old_text, new_text)
    return f"✅ 已替换 {file_path} 中的 1 处内容\n\n{context}"


def _build_context(file_path: str, content: str, old_text: str, new_text: str) -> str:
    """构建改动区域的上下文预览。"""
    lines = content.split("\n")

    # 找到新文本所在的行范围
    new_lines = new_text.split("\n")
    start_line = _find_line(lines, new_lines[0] if new_lines else "")

    if start_line is None:
        return "(无法定位改动区域)"

    end_line = start_line + len(new_lines) - 1

    # 计算上下文窗口
    window_start = max(0, start_line - _CONTEXT_LINES)
    window_end = min(len(lines) - 1, end_line + _CONTEXT_LINES)

    # 构建输出
    result = [f"📖 改动区域 (第 {window_start + 1}-{window_end + 1} 行):"]
    result.append("")

    for i in range(window_start, window_end + 1):
        line_num = i + 1
        line = lines[i]
        # 标记改动行
        if start_line <= i <= end_line:
            result.append(f"  {line_num:>4} → {line}")
        else:
            result.append(f"  {line_num:>4} │ {line}")

    return "\n".join(result)


def _find_line(lines: list[str], target: str) -> int | None:
    """找到目标文本首次出现的行号。"""
    if not target:
        return 0
    for i, line in enumerate(lines):
        if target in line:
            return i
    return None