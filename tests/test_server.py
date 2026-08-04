"""Phase 10 方向一：Python --server 模式测试。"""

import json
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from main import _build_message, _emit, run_server


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


# ──────────────────────────────────────────────
# 编辑器感知测试（方向四）
# ──────────────────────────────────────────────

class TestBuildMessage:
    """_build_message 编辑器上下文 + @file 引用测试。"""

    def test_plain_message(self):
        """无上下文时原样返回。"""
        msg = {"type": "chat", "message": "你好"}
        assert _build_message(msg) == "你好"

    def test_active_file_context(self):
        """带 activeFile 时应注入文件路径。"""
        msg = {"type": "chat", "message": "重构这个函数", "activeFile": "/src/main.py"}
        result = _build_message(msg)
        assert "[当前编辑文件: /src/main.py]" in result
        assert "重构这个函数" in result

    def test_selection_context(self):
        """带 selection 时应注入选区内容。"""
        msg = {
            "type": "chat",
            "message": "优化这段代码",
            "selection": "def foo():\n    return 1",
        }
        result = _build_message(msg)
        assert "[选中内容]:" in result
        assert "def foo():" in result
        assert "优化这段代码" in result

    def test_full_context(self):
        """同时有 activeFile + selection 时应全部注入。"""
        msg = {
            "type": "chat",
            "message": "修复 bug",
            "activeFile": "/src/app.py",
            "selection": "x = 1 / 0",
        }
        result = _build_message(msg)
        assert "[当前编辑文件: /src/app.py]" in result
        assert "[选中内容]:" in result
        assert "x = 1 / 0" in result
        assert "修复 bug" in result

    def test_at_file_reference(self, tmp_path):
        """@file:path 应替换为文件内容。"""
        test_file = tmp_path / "hello.py"
        test_file.write_text("print('hello')")

        msg = {"type": "chat", "message": f"看看 @file:hello.py 的内容"}
        with patch.dict("os.environ", {"WORKSPACE_DIR": str(tmp_path)}):
            result = _build_message(msg)
        assert "[文件 hello.py 的内容]:" in result
        assert "print('hello')" in result
        assert "@file:" not in result

    def test_at_file_absolute_path(self, tmp_path):
        """@file 支持绝对路径。"""
        test_file = tmp_path / "app.py"
        test_file.write_text("x = 42")
        abs_path = str(test_file)

        msg = {"type": "chat", "message": f"看看 @file:{abs_path}"}
        result = _build_message(msg)
        assert "x = 42" in result

    def test_at_file_not_found(self):
        """@file 引用不存在的文件应返回错误提示。"""
        msg = {"type": "chat", "message": "看看 @file:not_exist.py"}
        with patch.dict("os.environ", {"WORKSPACE_DIR": "/tmp"}):
            result = _build_message(msg)
        assert "无法读取文件" in result

    def test_at_file_with_context(self, tmp_path):
        """@file 与编辑器上下文共存。"""
        test_file = tmp_path / "util.py"
        test_file.write_text("def util(): pass")

        msg = {
            "type": "chat",
            "message": "参考 @file:util.py 修改",
            "activeFile": "/src/main.py",
        }
        with patch.dict("os.environ", {"WORKSPACE_DIR": str(tmp_path)}):
            result = _build_message(msg)
        assert "[当前编辑文件: /src/main.py]" in result
        assert "def util(): pass" in result
        assert "参考" in result


# ──────────────────────────────────────────────
# Server 日志测试
# ──────────────────────────────────────────────

class TestServerLogging:
    """验证 server 模式关键节点有日志记录。"""

    def _run_and_capture_logs(self, input_lines: list[str]):
        """辅助函数：运行 server 并捕获 logger 调用。"""
        input_data = "\n".join(input_lines) + "\n"

        with patch("sys.stdin", StringIO(input_data)), \
             patch("sys.stdout", new_callable=StringIO), \
             patch("agent.create_agent") as mock_create, \
             patch("main.logger") as mock_logger:

            mock_agent = MagicMock()
            mock_agent._model = "test-model"
            mock_agent.tracer.event_count = 0
            mock_agent.memory.file_count = 0
            mock_agent.planner.current_plan = None
            mock_agent.usage.session.api_calls = 0
            mock_agent.chat.return_value = "测试回复"
            mock_create.return_value = mock_agent

            run_server()

            return mock_logger

    def test_server_startup_logged(self):
        """启动时应记录日志。"""
        mock_logger = self._run_and_capture_logs([])
        mock_logger.info.assert_any_call("[Server] 启动: workspace=%s", ".")
        mock_logger.info.assert_any_call("[Server] 就绪: model=%s", "test-model")

    def test_chat_logged(self):
        """chat 消息应记录日志。"""
        inputs = [json.dumps({"type": "chat", "message": "你好"})]
        mock_logger = self._run_and_capture_logs(inputs)
        # 检查有包含 "chat:" 的 info 调用
        chat_calls = [
            c for c in mock_logger.info.call_args_list
            if "chat:" in str(c)
        ]
        assert len(chat_calls) >= 1

    def test_chat_error_logged(self):
        """chat 异常时应记录 error 日志。"""
        input_data = json.dumps({"type": "chat", "message": "触发异常"}) + "\n"

        with patch("sys.stdin", StringIO(input_data)), \
             patch("sys.stdout", new_callable=StringIO), \
             patch("agent.create_agent") as mock_create, \
             patch("main.logger") as mock_logger:

            mock_agent = MagicMock()
            mock_agent._model = "test-model"
            mock_agent.tracer.event_count = 0
            mock_agent.memory.file_count = 0
            mock_agent.planner.current_plan = None
            mock_agent.usage.session.api_calls = 0
            mock_agent.chat.side_effect = RuntimeError("模拟异常")
            mock_create.return_value = mock_agent

            run_server()

            mock_logger.error.assert_called()
            error_call_args = str(mock_logger.error.call_args)
            assert "chat 异常" in error_call_args

    def test_quit_logged(self):
        """quit 消息应记录日志。"""
        inputs = [json.dumps({"type": "quit"})]
        mock_logger = self._run_and_capture_logs(inputs)
        quit_calls = [
            c for c in mock_logger.info.call_args_list
            if "quit" in str(c) or "退出" in str(c)
        ]
        assert len(quit_calls) >= 1

    def test_json_parse_error_logged(self):
        """JSON 解析失败应记录 warning 日志。"""
        inputs = ["这不是 JSON"]
        mock_logger = self._run_and_capture_logs(inputs)
        mock_logger.warning.assert_called()
        warning_call_args = str(mock_logger.warning.call_args)
        assert "解析失败" in warning_call_args
