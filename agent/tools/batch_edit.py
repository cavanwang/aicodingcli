"""多文件联合编辑工具：批量执行多个文件的编辑操作。"""

import json
from agent.tools.edit_file import edit_file
from agent.tools.git_ops import git_checkpoint


def batch_edit(edits: str) -> str:
    """批量编辑多个文件，自动创建 checkpoint 并汇总结果。

    参数:
        edits: JSON 数组字符串，每个元素包含 file_path, old_text, new_text
               例: '[{"file_path": "a.py", "old_text": "x", "new_text": "y"}, ...]'
    """
    # 解析编辑列表
    try:
        edit_list = json.loads(edits)
    except json.JSONDecodeError as e:
        return f"❌ edits 参数不是合法的 JSON: {e}"

    if not isinstance(edit_list, list):
        return "❌ edits 参数必须是 JSON 数组"

    if len(edit_list) == 0:
        return "❌ edits 数组不能为空"

    if len(edit_list) > 20:
        return f"❌ 单次最多支持 20 个编辑操作，当前 {len(edit_list)} 个"

    # 验证每个编辑操作的字段
    for i, edit in enumerate(edit_list):
        if not isinstance(edit, dict):
            return f"❌ 第 {i + 1} 个编辑操作不是 JSON 对象"
        for field in ("file_path", "old_text", "new_text"):
            if field not in edit:
                return f"❌ 第 {i + 1} 个编辑操作缺少 {field} 字段"

    # 创建 checkpoint
    checkpoint_result = git_checkpoint(message="batch_edit checkpoint")

    # 逐个执行编辑
    results = []
    success_count = 0
    fail_count = 0
    changed_files = []

    for i, edit in enumerate(edit_list):
        file_path = edit["file_path"]
        old_text = edit["old_text"]
        new_text = edit["new_text"]

        result = edit_file(file_path, old_text, new_text)

        if result.startswith("✅"):
            success_count += 1
            changed_files.append(file_path)
            results.append(f"  [{i + 1}] ✅ {file_path}")
        else:
            fail_count += 1
            results.append(f"  [{i + 1}] ❌ {file_path}: {result}")

    # 构建汇总报告
    total = len(edit_list)
    report = [f"📋 批量编辑完成: {success_count}/{total} 成功"]
    if checkpoint_result and not checkpoint_result.startswith("git 执行失败"):
        report.append(f"📌 Checkpoint: {checkpoint_result}")
    report.append("")

    if fail_count > 0:
        report.append(f"⚠️ {fail_count} 个编辑失败:")
        for r in results:
            if "❌" in r:
                report.append(r)
        report.append("")

    if success_count > 0:
        report.append(f"✅ 成功修改的文件: {', '.join(changed_files)}")

    return "\n".join(report)
