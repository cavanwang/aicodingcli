"""记忆与审查工具函数：供 Agent 工具注册表调用。

通过模块级引用访问 CodeMemory 实例，
由 Agent 初始化时通过 set_memory() 注入。
"""

from __future__ import annotations

from typing import Any

from agent.memory import CodeMemory
from agent.project_memory import (
    save_project_memory as _save_project_memory,
    append_project_memory as _append_project_memory,
)

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


def review_changes(format: str = "text") -> str:
    """审查当前变更质量：分析变更范围、运行测试、评估风险。

    Args:
        format: 输出格式，"text"（默认）或 "json"
    """
    # 延迟导入，避免循环依赖
    from agent.review import ChangeReviewer

    reviewer = ChangeReviewer()
    result = reviewer.review()

    if format == "json":
        return result.to_json()
    return reviewer.format_report(result)


def save_memory(action: str, content: str = "", section: str = "") -> str:
    """保存或追加项目记忆到 .agent/memory.md 文件。

    项目记忆是跨会话持久化的 Markdown 文件，用于记录项目架构、模块职责、
    编码规范、踩坑经验等。下次会话启动时自动加载到 system prompt。

    Args:
        action: 操作类型，"save"（覆盖保存）或 "append"（追加/更新章节）
        content: 记忆内容（Markdown 格式）
        section: 章节标题（仅 append 模式使用），如 "## 模块职责"
    """
    if action == "save":
        if not content:
            return "❌ save 操作需要 content 参数"
        return _save_project_memory(content)

    if action == "append":
        if not section or not content:
            return "❌ append 操作需要 section 和 content 参数"
        return _append_project_memory(section, content)

    return f"❌ 未知操作: {action}，可选: save, append"
