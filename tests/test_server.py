"""Phase 10 方向一：Python --server 模式测试。"""

import json
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from main import _emit, run_server


# ──────────────────────────────────────────────
# _emit 测试
# ──────────────────────────────────────────────

class TestEmit:
    """_emit 函数测试。"""

    def test_emit_writes_json_line(self, capsys):
        """验证 _emit 输出 JSON 并换行。"""
        _emit({"type": "test", "value": 42})
        captured = capsys.readouterr()
        assert captured.out == '{"type": "test", "value": 42}\n'

    def test_emit_chinese_content(self, capsys):
        """验证中文字符不被转义。"""
        _emit({"type": "done", "reply": "你好世界"})
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["reply"] == "你好世界"
        # ensure_ascii=False 应该保留中文
        assert "你好" in captured.out
        assert "\\u" not in captured.out

    def test_emit_flushes(self):
        """验证 _emit 会刷新缓冲区。"""
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            _emit({"type": "test"})
            # flush 后应该立即可读
            assert mock_stdout.getvalue() == '{"type": "test"}\n'


# ──────────────────────────────────────────────
# run_server 测试
# ──────────────────────────────────────────────

class TestRunServer:
    """run_server 函数测试。"""

    def _run_server_with_input(self, input_lines: list[str]) -> list[dict]:
        """辅助函数：模拟 stdin 输入，捕获 stdout 输出。"""
        input_data = "\n".join(input_lines) + "\n"
        
        with patch("sys.stdin", StringIO(input_data)), \
             patch("sys.stdout", new_callable=StringIO) as mock_stdout, \
             patch("agent.create_agent") as mock_create:
            
            # 创建模拟 Agent
            mock_agent = MagicMock()
            mock_agent._model = "test-model"
            mock_agent.tracer.event_count = 0
            mock_agent.memory.file_count = 0
            mock_agent.planner.current_plan = None
            mock_agent.usage.session.api_calls = 0
            mock_agent.chat.return_value = "测试回复"
            mock_create.return_value = mock_agent

            run_server()

            # 解析输出
            output_lines = mock_stdout.getvalue().strip().split("\n")
            return [json.loads(line) for line in output_lines if line.strip()]

    def test_ready_message_on_start(self):
        """启动时应发送 ready 消息。"""
        outputs = self._run_server_with_input([])
        assert len(outputs) >= 1
        assert outputs[0]["type"] == "ready"
        assert outputs[0]["model"] == "test-model"

    def test_chat_message(self):
        """收到 chat 消息后调用 agent.chat 并返回 done。"""
        inputs = [
            json.dumps({"type": "chat", "message": "你好"}),
        ]
        outputs = self._run_server_with_input(inputs)
        
        # ready + done
        assert outputs[0]["type"] == "ready"
        assert outputs[1]["type"] == "done"
        assert outputs[1]["reply"] == "测试回复"

    def test_multi_turn_conversation(self):
        """多轮对话应保持上下文（agent.chat 被多次调用）。"""
        inputs = [
            json.dumps({"type": "chat", "message": "第一轮"}),
            json.dumps({"type": "chat", "message": "第二轮"}),
            json.dumps({"type": "chat", "message": "第三轮"}),
        ]
        outputs = self._run_server_with_input(inputs)
        
        # ready + 3 * done
        assert outputs[0]["type"] == "ready"
        done_msgs = [o for o in outputs if o["type"] == "done"]
        assert len(done_msgs) == 3

    def test_ping_pong(self):
        """ping 消息应回复 pong。"""
        inputs = [json.dumps({"type": "ping"})]
        outputs = self._run_server_with_input(inputs)
        
        assert outputs[0]["type"] == "ready"
        assert outputs[1]["type"] == "pong"

    def test_quit_message(self):
        """quit 消息应回复 bye 并退出。"""
        inputs = [json.dumps({"type": "quit"})]
        outputs = self._run_server_with_input(inputs)
        
        assert outputs[0]["type"] == "ready"
        assert outputs[1]["type"] == "bye"

    def test_invalid_json(self):
        """无效 JSON 应返回 error 但继续运行。"""
        inputs = [
            "这不是 JSON",
            json.dumps({"type": "ping"}),  # 之后还能继续处理
        ]
        outputs = self._run_server_with_input(inputs)
        
        # ready + error + pong
        assert outputs[0]["type"] == "ready"
        assert outputs[1]["type"] == "error"
        assert "解析失败" in outputs[1]["message"]
        assert outputs[2]["type"] == "pong"

    def test_unknown_message_type(self):
        """未知消息类型应返回 error。"""
        inputs = [json.dumps({"type": "unknown_type"})]
        outputs = self._run_server_with_input(inputs)
        
        assert outputs[1]["type"] == "error"
        assert "未知消息类型" in outputs[1]["message"]

    def test_empty_message(self):
        """空消息内容应返回 error。"""
        inputs = [json.dumps({"type": "chat", "message": ""})]
        outputs = self._run_server_with_input(inputs)
        
        assert outputs[1]["type"] == "error"
        assert "为空" in outputs[1]["message"]

    def test_chat_exception_handling(self):
        """agent.chat 抛异常时应返回 error。"""
        input_data = json.dumps({"type": "chat", "message": "触发异常"}) + "\n"
        
        with patch("sys.stdin", StringIO(input_data)), \
             patch("sys.stdout", new_callable=StringIO) as mock_stdout, \
             patch("agent.create_agent") as mock_create:
            
            mock_agent = MagicMock()
            mock_agent._model = "test-model"
            mock_agent.tracer.event_count = 0
            mock_agent.memory.file_count = 0
            mock_agent.planner.current_plan = None
            mock_agent.usage.session.api_calls = 0
            mock_agent.chat.side_effect = RuntimeError("模拟异常")
            mock_create.return_value = mock_agent

            run_server()

            outputs = [json.loads(l) for l in mock_stdout.getvalue().strip().split("\n")]
            assert outputs[1]["type"] == "error"
            assert "模拟异常" in outputs[1]["message"]


# ──────────────────────────────────────────────
# 协议格式测试
# ──────────────────────────────────────────────

class TestProtocol:
    """消息协议格式验证。"""

    def test_input_protocol(self):
        """验证输入消息格式。"""
        msg = {"type": "chat", "message": "重构这个函数"}
        serialized = json.dumps(msg)
        parsed = json.loads(serialized)
        assert parsed["type"] == "chat"
        assert parsed["message"] == "重构这个函数"

    def test_output_done_protocol(self):
        """验证 done 输出格式。"""
        msg = {"type": "done", "reply": "已完成重构，修改了 3 个文件"}
        serialized = json.dumps(msg, ensure_ascii=False)
        parsed = json.loads(serialized)
        assert parsed["type"] == "done"
        assert "已完成" in parsed["reply"]

    def test_output_error_protocol(self):
        """验证 error 输出格式。"""
        msg = {"type": "error", "message": "API 调用失败: 401 Unauthorized"}
        serialized = json.dumps(msg, ensure_ascii=False)
        parsed = json.loads(serialized)
        assert parsed["type"] == "error"
        assert "401" in parsed["message"]

    def test_output_ready_protocol(self):
        """验证 ready 输出格式。"""
        msg = {"type": "ready", "model": "qwen-plus", "workspace": "/path/to/project"}
        serialized = json.dumps(msg, ensure_ascii=False)
        parsed = json.loads(serialized)
        assert parsed["type"] == "ready"
        assert parsed["model"] == "qwen-plus"
        assert parsed["workspace"] == "/path/to/project"
