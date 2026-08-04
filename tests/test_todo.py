"""Todo 列表模块测试。"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.todo import TodoItem, TodoList, TODO_DIR


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture()
def todo_list():
    """返回一个干净的 TodoList。"""
    return TodoList(session_id="test")


@pytest.fixture()
def todo_dir(tmp_path):
    """临时 Todo 目录。"""
    d = tmp_path / "todos"
    d.mkdir(parents=True)
    return d


# ──────────────────────────────────────────────
# TodoItem 测试
# ──────────────────────────────────────────────

class TestTodoItem:
    def test_initial_state(self):
        item = TodoItem(id=1, content="测试任务")
        assert item.id == 1
        assert item.content == "测试任务"
        assert item.status == "pending"
        assert item.result == ""
        assert item.error == ""
        assert item.created_at != ""
        assert item.updated_at != ""

    def test_to_dict_and_from_dict(self):
        item = TodoItem(id=1, content="测试", status="in_progress")
        data = item.to_dict()
        restored = TodoItem.from_dict(data)
        assert restored.id == 1
        assert restored.content == "测试"
        assert restored.status == "in_progress"


# ──────────────────────────────────────────────
# TodoList 核心功能测试
# ──────────────────────────────────────────────

class TestTodoList:
    def test_add_item(self, todo_list):
        item = todo_list.add("任务一")
        assert item.id == 1
        assert item.content == "任务一"
        assert todo_list.item_count == 1

    def test_add_multiple_items(self, todo_list):
        todo_list.add("任务一")
        todo_list.add("任务二")
        todo_list.add("任务三")
        assert todo_list.item_count == 3
        items = todo_list.list_all()
        assert items[0].id == 1
        assert items[1].id == 2
        assert items[2].id == 3

    def test_update_content(self, todo_list):
        todo_list.add("原始内容")
        item = todo_list.update(1, content="新内容")
        assert item is not None
        assert item.content == "新内容"

    def test_update_status(self, todo_list):
        todo_list.add("任务")
        item = todo_list.update(1, status="in_progress")
        assert item is not None
        assert item.status == "in_progress"

    def test_update_invalid_status(self, todo_list):
        todo_list.add("任务")
        item = todo_list.update(1, status="invalid_status")
        assert item is None  # 无效状态返回 None

    def test_update_nonexistent_id(self, todo_list):
        item = todo_list.update(999, content="test")
        assert item is None

    def test_complete_item(self, todo_list):
        todo_list.add("任务")
        result = todo_list.complete(1, result="已完成")
        assert result is True
        item = todo_list.get(1)
        assert item.status == "complete"
        assert item.result == "已完成"

    def test_complete_nonexistent(self, todo_list):
        result = todo_list.complete(999)
        assert result is False

    def test_set_error(self, todo_list):
        todo_list.add("任务")
        todo_list.update(1, status="in_progress")
        result = todo_list.set_error(1, "出错了")
        assert result is True
        item = todo_list.get(1)
        assert item.error == "出错了"

    def test_set_error_nonexistent(self, todo_list):
        result = todo_list.set_error(999, "error")
        assert result is False

    def test_get_current(self, todo_list):
        todo_list.add("任务一")
        todo_list.add("任务二")
        todo_list.update(1, status="in_progress")
        current = todo_list.get_current()
        assert current is not None
        assert current.id == 1

    def test_get_current_none(self, todo_list):
        todo_list.add("任务")
        current = todo_list.get_current()
        assert current is None

    def test_clear(self, todo_list):
        todo_list.add("任务一")
        todo_list.add("任务二")
        todo_list.clear()
        assert todo_list.item_count == 0


# ──────────────────────────────────────────────
# 进度摘要测试
# ──────────────────────────────────────────────

class TestTodoSummary:
    def test_summary_empty(self, todo_list):
        summary = todo_list.summary()
        assert "无 Todo 项" in summary

    def test_summary_with_items(self, todo_list):
        todo_list.add("任务一")
        todo_list.add("任务二")
        todo_list.add("任务三")
        todo_list.complete(1, result="完成")
        todo_list.update(2, status="in_progress")

        summary = todo_list.summary()
        assert "1/3 完成" in summary
        assert "1 进行中" in summary
        assert "1 待办" in summary

    def test_summary_with_error(self, todo_list):
        todo_list.add("任务")
        todo_list.update(1, status="in_progress")
        todo_list.set_error(1, "执行失败")

        summary = todo_list.summary()
        assert "执行失败" in summary

    def test_progress_line_empty(self, todo_list):
        line = todo_list.progress_line()
        assert line == ""

    def test_progress_line_with_items(self, todo_list):
        todo_list.add("任务一")
        todo_list.add("任务二")
        todo_list.complete(1)

        line = todo_list.progress_line()
        assert "Todo: 1/2 完成" in line
        assert "1 待办" in line


# ──────────────────────────────────────────────
# 持久化测试
# ──────────────────────────────────────────────

class TestTodoPersistence:
    def test_save_no_items(self, todo_list):
        path = todo_list.save()
        assert path is None

    def test_save_and_load(self, todo_list, tmp_path):
        with patch("agent.todo.TODO_DIR", tmp_path):
            todo_list.add("任务一")
            todo_list.add("任务二")
            todo_list.complete(1, result="完成")

            path = todo_list.save()
            assert path is not None
            assert path.exists()

            # 加载到新列表
            new_list = TodoList(session_id="test")
            result = new_list.load()
            assert result is True
            assert new_list.item_count == 2
            items = new_list.list_all()
            assert items[0].status == "complete"
            assert items[1].status == "pending"

    def test_load_nonexistent(self, todo_list, tmp_path):
        with patch("agent.todo.TODO_DIR", tmp_path):
            result = todo_list.load()
            assert result is False


# ──────────────────────────────────────────────
# 工具函数测试
# ──────────────────────────────────────────────

class TestTodoTools:
    def test_add_todo(self, todo_list):
        from agent.tools import todo_tools
        todo_tools.set_todo_list(todo_list)

        result = todo_tools.add_todo("新任务")
        assert "已添加" in result
        assert "[1]" in result

    def test_add_todo_empty_content(self, todo_list):
        from agent.tools import todo_tools
        todo_tools.set_todo_list(todo_list)

        result = todo_tools.add_todo("")
        assert "不能为空" in result

    def test_update_todo(self, todo_list):
        from agent.tools import todo_tools
        todo_tools.set_todo_list(todo_list)

        todo_tools.add_todo("原始任务")
        result = todo_tools.update_todo(1, content="新内容")
        assert "已更新" in result

    def test_update_todo_nonexistent(self, todo_list):
        from agent.tools import todo_tools
        todo_tools.set_todo_list(todo_list)

        result = todo_tools.update_todo(999, content="test")
        assert "未找到" in result

    def test_list_todos_empty(self, todo_list):
        from agent.tools import todo_tools
        todo_tools.set_todo_list(todo_list)

        result = todo_tools.list_todos()
        assert "无待办" in result

    def test_list_todos_with_items(self, todo_list):
        from agent.tools import todo_tools
        todo_tools.set_todo_list(todo_list)

        todo_tools.add_todo("任务一")
        todo_tools.add_todo("任务二")
        result = todo_tools.list_todos()
        assert "任务一" in result
        assert "任务二" in result

    def test_complete_todo(self, todo_list):
        from agent.tools import todo_tools
        todo_tools.set_todo_list(todo_list)

        todo_tools.add_todo("任务")
        result = todo_tools.complete_todo(1, result="完成")
        assert "已完成" in result

    def test_complete_todo_nonexistent(self, todo_list):
        from agent.tools import todo_tools
        todo_tools.set_todo_list(todo_list)

        result = todo_tools.complete_todo(999)
        assert "未找到" in result
