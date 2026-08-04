"""记忆与审查工具函数：供 Agent 工具注册表调用。

通过模块级引用访问 CodeMemory 实例，
由 Agent 初始化时通过 set_memory() 注入。
"""

from __future__ import annotations

from typing import Any

from agent.memory import CodeMemory

# 模块级 memory 引用，由 Agent 初始化时注入
_memory: CodeMemory | None = None


def set_memory(memory: CodeMemory) -> None:
    """注入 CodeMemory 实例（Agent 初始化时调用）。"""
    global _memory
    _memory = memory


def _get_memory() -> CodeMemory:
    if _memory is None:
        raise RuntimeError("CodeMemory 未初始化，请先调用 set_memory()")
    return _memory


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

def update_memory(
    action: str,
    key: str = "",
    value: str = "",
    file_path: str = "",
    interfaces: str = "",
    fact: str = "",
) -> str:
    """更新代码库记忆。

    Args:
        action: 操作类型，可选 "summary" | "interfaces" | "fact" | "remove"
        key: 文件路径（用于 summary/interfaces 操作）
        value: 摘要内容（用于 summary 操作）
        file_path: 文件路径（同 key，兼容不同参数名）
        interfaces: 接口列表，逗号分隔（用于 interfaces 操作）
        fact: 项目事实（用于 fact 操作）
    """
    memory = _get_memory()
    target_path = key or file_path

    if action == "summary":
        if not target_path or not value:
            return "❌ summary 操作需要 key(file_path) 和 value(摘要)"
        memory.update_file_summary(target_path, value)
        memory.save()
        return f"✓ 已更新 {target_path} 的摘要"

    if action == "interfaces":
        if not target_path:
            return "❌ interfaces 操作需要 key(file_path)"
        iface_list = [i.strip() for i in interfaces.split(",") if i.strip()]
        memory.update_key_interfaces(target_path, iface_list)
        memory.save()
        return f"✓ 已更新 {target_path} 的接口列表: {', '.join(iface_list)}"

    if action == "fact":
        if not fact:
            return "❌ fact 操作需要 fact 参数"
        memory.add_project_fact(fact)
        memory.save()
        return f"✓ 已添加项目事实: {fact}"

    if action == "remove":
        if not target_path:
            return "❌ remove 操作需要 key(file_path)"
        ok = memory.remove_file(target_path)
        if ok:
            memory.save()
            return f"✓ 已移除 {target_path} 的记忆"
        return f"⚠ {target_path} 不在记忆中"

    return f"❌ 未知操作: {action}，可选: summary, interfaces, fact, remove"


def review_changes() -> str:
    """审查当前变更质量：分析变更范围、运行测试、评估风险。"""
    # 延迟导入，避免循环依赖
    from agent.review import ChangeReviewer

    reviewer = ChangeReviewer()
    result = reviewer.review()
    return reviewer.format_report(result)
