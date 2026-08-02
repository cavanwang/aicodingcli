"""执行轨迹记录模块测试。"""

import json
from pathlib import Path

import pytest

from agent.tracer import ExecutionTracer


class TestExecutionTracer:
    """ExecutionTracer 测试。"""

    def test_tracer_initial_empty(self):
        tracer = ExecutionTracer()
        assert tracer.event_count == 0
        assert tracer.round_count == 0

    def test_record_round(self):
        tracer = ExecutionTracer()
        tracer.record_round(1, 5)
        tracer.record_round(2, 7)

        assert tracer.round_count == 2
        assert tracer.event_count == 2

    def test_record_tool_call_success(self):
        tracer = ExecutionTracer()
        tracer.record_tool_call(
            name="read_file",
            args={"path": "test.py"},
            result="file content",
            duration_ms=15.5,
            success=True,
        )

        assert tracer.event_count == 1
        events = tracer._events
        assert events[0]["type"] == "tool_call"
        assert events[0]["tool"] == "read_file"
        assert events[0]["args"] == {"path": "test.py"}
        assert events[0]["success"] is True
        assert events[0]["duration_ms"] == 15.5

    def test_record_tool_call_failure(self):
        tracer = ExecutionTracer()
        tracer.record_tool_call(
            name="run_command",
            args={"command": "invalid_cmd"},
            result="error: command not found",
            duration_ms=100.0,
            success=False,
        )

        events = tracer._events
        assert events[0]["success"] is False

    def test_record_tool_call_truncates_long_result(self):
        tracer = ExecutionTracer()
        long_result = "x" * 1000
        tracer.record_tool_call("test", {}, long_result, 10.0)

        events = tracer._events
        assert len(events[0]["result_preview"]) == 500
        assert events[0]["result_length"] == 1000

    def test_record_recovery(self):
        tracer = ExecutionTracer()
        tracer.record_recovery(
            tool_name="run_command",
            error_type="dependency",
            classification={"error_type": "dependency", "details": "ModuleNotFoundError"},
            attempt=1,
            max_attempts=3,
            exhausted=False,
        )

        assert tracer.event_count == 1
        events = tracer._events
        assert events[0]["type"] == "recovery"
        assert events[0]["tool"] == "run_command"
        assert events[0]["error_type"] == "dependency"
        assert events[0]["attempt"] == 1
        assert events[0]["exhausted"] is False

    def test_record_recovery_exhausted(self):
        tracer = ExecutionTracer()
        tracer.record_recovery(
            tool_name="run_command",
            error_type="syntax",
            classification={"error_type": "syntax"},
            attempt=3,
            max_attempts=3,
            exhausted=True,
        )

        events = tracer._events
        assert events[0]["exhausted"] is True

    def test_record_rollback(self):
        tracer = ExecutionTracer()
        tracer.record_rollback("run_command", "已回滚到 checkpoint-abc")

        events = tracer._events
        assert events[0]["type"] == "rollback"
        assert events[0]["tool"] == "run_command"
        assert "checkpoint-abc" in events[0]["result"]

    def test_record_user_rejected(self):
        tracer = ExecutionTracer()
        tracer.record_user_rejected("write_file")

        events = tracer._events
        assert events[0]["type"] == "user_rejected"
        assert events[0]["tool"] == "write_file"

    def test_save_creates_file(self, tmp_path, monkeypatch):
        # 使用临时目录
        trace_dir = tmp_path / "traces"
        monkeypatch.setattr("agent.tracer.TRACE_DIR", trace_dir)

        tracer = ExecutionTracer()
        tracer.record_round(1, 3)
        tracer.record_tool_call("test", {}, "result", 10.0)

        path = tracer.save()

        assert path.exists()
        assert path.suffix == ".json"
        assert path.parent == trace_dir

        # 验证文件内容
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["total_rounds"] == 1
        assert data["total_events"] == 2
        assert len(data["events"]) == 2

    def test_summary(self):
        tracer = ExecutionTracer()
        tracer.record_round(1, 3)
        tracer.record_tool_call("read_file", {}, "content", 10.0, success=True)
        tracer.record_tool_call("run_command", {}, "error", 50.0, success=False)
        tracer.record_recovery("run_command", "dependency", {}, 1, 3, False)
        tracer.record_rollback("run_command", "rolled back")

        summary = tracer.summary()
        assert summary["total_rounds"] == 1
        assert summary["total_tool_calls"] == 2
        assert summary["total_recoveries"] == 1
        assert summary["total_rollbacks"] == 1
        assert summary["avg_tool_duration_ms"] == 30.0  # (10 + 50) / 2

    def test_summary_empty(self):
        tracer = ExecutionTracer()
        summary = tracer.summary()
        assert summary["total_rounds"] == 0
        assert summary["total_tool_calls"] == 0
        assert summary["avg_tool_duration_ms"] == 0

    def test_reset(self):
        tracer = ExecutionTracer()
        tracer.record_round(1, 3)
        tracer.record_tool_call("test", {}, "result", 10.0)
        assert tracer.event_count == 2
        assert tracer.round_count == 1

        tracer.reset()
        assert tracer.event_count == 0
        assert tracer.round_count == 0

    def test_multiple_events_ordering(self):
        tracer = ExecutionTracer()
        tracer.record_round(1, 2)
        tracer.record_tool_call("tool1", {}, "r1", 5.0)
        tracer.record_tool_call("tool2", {}, "r2", 10.0)
        tracer.record_recovery("tool2", "syntax", {}, 1, 3, False)
        tracer.record_round(2, 5)

        events = tracer._events
        assert len(events) == 5
        assert events[0]["type"] == "round"
        assert events[1]["type"] == "tool_call"
        assert events[2]["type"] == "tool_call"
        assert events[3]["type"] == "recovery"
        assert events[4]["type"] == "round"
