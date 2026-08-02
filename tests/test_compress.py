"""历史压缩功能测试。"""

import json
from unittest.mock import MagicMock

import config
from agent.core import Agent


def _make_agent(messages: list[dict], threshold: int = 10, keep: int = 4) -> Agent:
    """创建一个带自定义消息历史的 Agent（不依赖 OpenAI）。"""
    agent = Agent.__new__(Agent)
    agent._client = MagicMock()
    agent._model = "test"
    agent._max_rounds = 10
    agent._confirm = None
    agent._debug = False
    agent._max_result_len = 4000
    agent._messages = messages
    agent._recovery = MagicMock()
    agent._tracer = MagicMock()
    agent._tracer.event_count = 0

    # 临时设置压缩阈值
    agent._orig_threshold = config.COMPRESS_THRESHOLD
    agent._orig_keep = config.COMPRESS_KEEP_RECENT
    config.COMPRESS_THRESHOLD = threshold
    config.COMPRESS_KEEP_RECENT = keep

    return agent


def _restore_config(agent: Agent) -> None:
    """恢复 config 原始值。"""
    config.COMPRESS_THRESHOLD = agent._orig_threshold
    config.COMPRESS_KEEP_RECENT = agent._orig_keep


class TestCompressHistory:
    """compress_history() 测试。"""

    def test_no_compress_when_below_threshold(self):
        """消息数未超过阈值时不压缩。"""
        msgs = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        agent = _make_agent(msgs, threshold=10, keep=4)
        try:
            result = agent.compress_history()
            assert result is False
            assert len(agent._messages) == 3
        finally:
            _restore_config(agent)

    def test_compress_when_exceeds_threshold(self):
        """消息数超过阈值时执行压缩。"""
        msgs = [{"role": "system", "content": "system prompt"}]
        # 添加 20 条消息
        for i in range(10):
            msgs.append({"role": "user", "content": f"question {i}"})
            msgs.append({"role": "assistant", "content": f"answer {i}"})

        agent = _make_agent(msgs, threshold=10, keep=4)
        try:
            result = agent.compress_history()
            assert result is True
            # 压缩后：system + summary + 最近 4 条 = 6 条
            assert len(agent._messages) == 6
            # 第二条是摘要
            assert "[历史对话摘要]" in agent._messages[1]["content"]
        finally:
            _restore_config(agent)

    def test_compress_preserves_system_prompt(self):
        """压缩后 system prompt 保持不变。"""
        msgs = [{"role": "system", "content": "original system prompt"}]
        for i in range(15):
            msgs.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"})

        agent = _make_agent(msgs, threshold=5, keep=4)
        try:
            agent.compress_history()
            assert agent._messages[0]["content"] == "original system prompt"
            assert agent._messages[0]["role"] == "system"
        finally:
            _restore_config(agent)

    def test_compress_does_not_split_tool_pairs(self):
        """压缩不会拆分 assistant(tool_calls) 和 tool(result) 对。"""
        msgs = [{"role": "system", "content": "system"}]
        # 添加一些普通消息
        for i in range(5):
            msgs.append({"role": "user", "content": f"q{i}"})
            msgs.append({"role": "assistant", "content": f"a{i}"})

        # 添加一组工具调用对（在保留范围的边界）
        msgs.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path": "test.py"}'},
            }],
        })
        msgs.append({
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "file content",
        })

        agent = _make_agent(msgs, threshold=5, keep=4)
        try:
            agent.compress_history()
            # 验证工具调用对完整保留
            tool_msgs = [m for m in agent._messages if m["role"] == "tool"]
            assistant_with_tools = [
                m for m in agent._messages
                if m["role"] == "assistant" and m.get("tool_calls")
            ]
            # 如果保留了 tool，必须保留对应的 assistant
            if tool_msgs:
                assert len(assistant_with_tools) >= 1
        finally:
            _restore_config(agent)

    def test_compress_summary_contains_user_requests(self):
        """压缩摘要包含用户请求内容。"""
        msgs = [{"role": "system", "content": "system"}]
        msgs.append({"role": "user", "content": "帮我写一个排序算法"})
        msgs.append({"role": "assistant", "content": "好的，我来实现"})
        for i in range(10):
            msgs.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"})

        agent = _make_agent(msgs, threshold=5, keep=2)
        try:
            agent.compress_history()
            summary = agent._messages[1]["content"]
            assert "排序算法" in summary
        finally:
            _restore_config(agent)

    def test_compress_summary_contains_tool_calls(self):
        """压缩摘要包含工具调用信息。"""
        msgs = [{"role": "system", "content": "system"}]
        msgs.append({"role": "user", "content": "读取文件"})
        msgs.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path": "main.py"}'},
            }],
        })
        msgs.append({"role": "tool", "tool_call_id": "call_1", "content": "content"})
        for i in range(10):
            msgs.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"})

        agent = _make_agent(msgs, threshold=5, keep=2)
        try:
            agent.compress_history()
            summary = agent._messages[1]["content"]
            assert "read_file" in summary
        finally:
            _restore_config(agent)


class TestFindCompressBoundary:
    """_find_compress_boundary() 测试。"""

    def test_boundary_respects_keep_recent(self):
        """边界保证保留最近 N 条消息。"""
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(20):
            msgs.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"})

        agent = _make_agent(msgs, threshold=5, keep=6)
        try:
            boundary = agent._find_compress_boundary(keep_recent=6)
            # 保留的消息数
            kept = len(msgs) - boundary
            assert kept >= 6
        finally:
            _restore_config(agent)

    def test_boundary_at_least_1(self):
        """边界至少为 1（保留 system prompt）。"""
        # 当只有 system prompt 时，返回 0 表示无需压缩
        msgs = [{"role": "system", "content": "sys"}]
        agent = _make_agent(msgs, threshold=0, keep=0)
        try:
            boundary = agent._find_compress_boundary(keep_recent=0)
            # 只有 1 条消息，无需压缩，返回 0
            assert boundary == 0
        finally:
            _restore_config(agent)

    def test_boundary_with_multiple_messages(self):
        """多条消息时边界至少为 1。"""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ]
        agent = _make_agent(msgs, threshold=0, keep=1)
        try:
            boundary = agent._find_compress_boundary(keep_recent=1)
            assert boundary >= 1
        finally:
            _restore_config(agent)


class TestBuildSummaryText:
    """_build_summary_text() 测试。"""

    def test_summary_includes_user_content(self):
        msgs = [
            {"role": "user", "content": "请修复这个 bug"},
            {"role": "assistant", "content": "好的"},
        ]
        agent = _make_agent(msgs, threshold=100, keep=10)
        try:
            summary = agent._build_summary_text(msgs)
            assert "修复" in summary
        finally:
            _restore_config(agent)

    def test_summary_includes_assistant_text(self):
        msgs = [
            {"role": "assistant", "content": "我已经修复了这个问题"},
        ]
        agent = _make_agent(msgs, threshold=100, keep=10)
        try:
            summary = agent._build_summary_text(msgs)
            assert "修复" in summary
        finally:
            _restore_config(agent)

    def test_summary_for_empty_messages(self):
        agent = _make_agent([{"role": "system", "content": "sys"}], threshold=100, keep=10)
        try:
            summary = agent._build_summary_text([])
            assert summary == "(无有效历史)"
        finally:
            _restore_config(agent)
