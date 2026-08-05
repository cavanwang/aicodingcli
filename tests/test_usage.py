"""Token 用量统计测试。"""

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.usage import UsageStats, UsageTracker


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture()
def tracker(monkeypatch, tmp_path):
    """返回一个干净的 UsageTracker（使用临时目录）。"""
    usage_dir = tmp_path / "usage"
    usage_dir.mkdir()
    monkeypatch.setattr("agent.usage.USAGE_DIR", usage_dir)
    return UsageTracker()


@pytest.fixture()
def usage_dir(tmp_path):
    """临时用量目录。"""
    d = tmp_path / "usage"
    d.mkdir(parents=True)
    return d


# ──────────────────────────────────────────────
# UsageStats 单元测试
# ──────────────────────────────────────────────

class TestUsageStats:
    def test_initial_state(self):
        stats = UsageStats(started_at="2026-08-04T10:00:00")
        assert stats.prompt_tokens == 0
        assert stats.completion_tokens == 0
        assert stats.total_tokens == 0
        assert stats.api_calls == 0
        assert stats.tool_calls == 0

    def test_record_single_call(self):
        stats = UsageStats(started_at="2026-08-04T10:00:00")
        stats.record(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        assert stats.prompt_tokens == 100
        assert stats.completion_tokens == 50
        assert stats.total_tokens == 150
        assert stats.api_calls == 1

    def test_record_multiple_calls(self):
        stats = UsageStats(started_at="2026-08-04T10:00:00")
        stats.record(100, 50, 150)
        stats.record(200, 100, 300)
        assert stats.prompt_tokens == 300
        assert stats.completion_tokens == 150
        assert stats.total_tokens == 450
        assert stats.api_calls == 2

    def test_record_tool_call(self):
        stats = UsageStats(started_at="2026-08-04T10:00:00")
        stats.record_tool_call()
        stats.record_tool_call()
        assert stats.tool_calls == 2

    def test_summary_no_calls(self):
        stats = UsageStats(started_at="2026-08-04T10:00:00")
        summary = stats.summary()
        assert "无 API 调用" in summary

    def test_summary_with_calls(self):
        stats = UsageStats(started_at="2026-08-04T10:00:00")
        stats.record(100, 50, 150)
        stats.record_tool_call()
        summary = stats.summary()
        assert "API 调用: 1 次" in summary
        assert "工具调用: 1 次" in summary
        assert "输入 Token: 100" in summary
        assert "输出 Token: 50" in summary
        assert "总计 Token: 150" in summary

    def test_to_dict_and_from_dict(self):
        stats = UsageStats(started_at="2026-08-04T10:00:00")
        stats.record(100, 50, 150)
        stats.record_tool_call()

        data = stats.to_dict()
        restored = UsageStats.from_dict(data)

        assert restored.prompt_tokens == 100
        assert restored.completion_tokens == 50
        assert restored.total_tokens == 150
        assert restored.api_calls == 1
        assert restored.tool_calls == 1


# ──────────────────────────────────────────────
# UsageTracker 单元测试
# ──────────────────────────────────────────────

class TestUsageTracker:
    def test_session_property(self, tracker):
        assert tracker.session is not None
        assert tracker.session.api_calls == 0

    def test_record_usage(self, tracker):
        tracker.record_usage(100, 50, 150)
        assert tracker.session.prompt_tokens == 100
        assert tracker.session.api_calls == 1

    def test_record_tool_call(self, tracker):
        tracker.record_tool_call()
        assert tracker.session.tool_calls == 1

    def test_summary(self, tracker):
        tracker.record_usage(100, 50, 150)
        summary = tracker.summary()
        assert "API 调用: 1 次" in summary

    def test_save_no_api_calls(self, tracker):
        path = tracker.save()
        assert path is None

    def test_save_creates_file(self, tracker, tmp_path):
        with patch("agent.usage.USAGE_DIR", tmp_path):
            tracker.record_usage(100, 50, 150)
            path = tracker.save()
            assert path is not None
            assert path.exists()
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["prompt_tokens"] == 100
            assert data["api_calls"] == 1

    def test_save_merges_existing(self, tracker, tmp_path):
        with patch("agent.usage.USAGE_DIR", tmp_path):
            today = date.today().isoformat()
            existing_file = tmp_path / f"{today}.json"
            existing_data = {
                "prompt_tokens": 200,
                "completion_tokens": 100,
                "total_tokens": 300,
                "api_calls": 2,
                "tool_calls": 1,
                "started_at": "2026-08-04T09:00:00",
                "last_updated": "2026-08-04T09:30:00",
            }
            existing_file.write_text(json.dumps(existing_data), encoding="utf-8")

            tracker.record_usage(100, 50, 150)
            path = tracker.save()

            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["prompt_tokens"] == 300  # 200 + 100
            assert data["api_calls"] == 3  # 2 + 1
            assert data["started_at"] == "2026-08-04T09:00:00"  # 保留最早的

    def test_load_history_empty(self, tracker):
        history = tracker.load_history(days=7)
        assert history == []

    def test_load_history_with_files(self, tmp_path):
        usage_dir = tmp_path / "usage"
        usage_dir.mkdir()

        for i in range(3):
            d = (date.today() - timedelta(days=i)).isoformat()
            file_path = usage_dir / f"{d}.json"
            data = {
                "prompt_tokens": 100 * (i + 1),
                "completion_tokens": 50 * (i + 1),
                "total_tokens": 150 * (i + 1),
                "api_calls": i + 1,
                "tool_calls": i,
            }
            file_path.write_text(json.dumps(data), encoding="utf-8")

        with patch("agent.usage.USAGE_DIR", usage_dir):
            history = UsageTracker.load_history(days=3)
            assert len(history) == 3
            assert all("date" in entry for entry in history)

    def test_format_history_empty(self, tracker):
        formatted = tracker.format_history([])
        assert "无用量记录" in formatted

    def test_format_history_with_entries(self, tracker):
        history = [
            {"date": "2026-08-04", "total_tokens": 150, "api_calls": 1},
            {"date": "2026-08-03", "total_tokens": 300, "api_calls": 2},
        ]
        formatted = tracker.format_history(history)
        assert "最近用量:" in formatted
        assert "合计: 450 tokens, 3 次调用" in formatted
