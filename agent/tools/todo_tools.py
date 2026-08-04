"""Todo 工具函数：供 Agent 管理待办事项。

提供 4 个工具函数：
- add_todo: 添加待办项
- update_todo: 更新待办项内容或状态
- list_todos: 列出所有待办项
- complete_todo: 标记待办项为完成
"""

from agent.todo import TodoList

# 模块级 TodoList，延迟初始化
_todo_list: TodoList | None = None


def set_todo_list(todo_list: TodoList) -> None:
    """注入 TodoList 实例（由 Agent 初始化时调用）。"""
    global _todo_list
    _todo_list = todo_list


def _get_todo() -> TodoList:
    """获取当前 TodoList。"""
    global _todo_list
    if _todo_list is None:
        _todo_list = TodoList()
    return _todo_list


def add_todo(content: str) -> str:
    """添加一个待办事项。

    Args:
        content: 待办事项的描述内容

    Returns:
        新建待办的 ID 和确认信息
    """
    if not content or not content.strip():
        return "❌ 待办内容不能为空"

    todo = _get_todo()
    item = todo.add(content.strip())
    return f"✅ 已添加待办 [{item.id}]: {item.content}"


def update_todo(
    todo_id: int,
    content: str = "",
    status: str = "",
) -> str:
    """更新指定待办事项的内容或状态。

    Args:
        todo_id: 待办事项 ID
        content: 新的描述内容（可选，空字符串表示不修改）
        status: 新状态: pending | in_progress | complete（可选，空字符串表示不修改）

    Returns:
        更新结果确认
    """
    todo = _get_todo()

    content_val = content.strip() if content else None
    status_val = status.strip() if status else None

    if content_val is None and status_val is None:
        return "❌ 请提供要更新的内容或状态"

    item = todo.update(todo_id, content=content_val, status=status_val)
    if item is None:
        return f"❌ 未找到 ID 为 {todo_id} 的待办事项"

    parts = [f"✅ 已更新待办 [{item.id}]"]
    if content_val:
        parts.append(f"内容: {item.content}")
    if status_val:
        parts.append(f"状态: {item.status}")
    return ", ".join(parts)


def list_todos() -> str:
    """列出所有待办事项及状态。

    Returns:
        格式化的待办列表，含状态图标
    """
    todo = _get_todo()
    if todo.item_count == 0:
        return "📝 当前无待办事项"
    return todo.summary()


def complete_todo(todo_id: int, result: str = "") -> str:
    """标记指定待办事项为完成。

    Args:
        todo_id: 待办事项 ID
        result: 完成结果摘要（可选）

    Returns:
        完成确认信息
    """
    todo = _get_todo()
    if todo.complete(todo_id, result=result.strip() if result else ""):
        item = todo.get(todo_id)
        return f"✅ 待办 [{todo_id}] 已完成: {item.content}"
    return f"❌ 未找到 ID 为 {todo_id} 的待办事项"
