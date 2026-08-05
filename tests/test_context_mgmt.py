"""任务 D 上下文智能管理测试：预算护栏(D2)、git 共现(D1)、记忆按需注入(D3)。"""

import subprocess
from unittest.mock import MagicMock

import pytest

import config
import agent.core as core_module
from agent.core import Agent
from agent.context import ContextBudget, estimate_messages_tokens, estimate_text_tokens
from agent.project_memory import (
    _extract_keywords,
    _split_sections,
    select_relevant_sections,
)
from agent.tools.git_ops import _git_co_occurrence, get_related_files


# ──────────────────────────────────────────────
# D2: token 估算与预算
# ──────────────────────────────────────────────
class TestTokenEstimation:
    def test_empty_text(self):
        assert estimate_text_tokens("") == 0

    def test_monotonic(self):
        assert estimate_text_tokens("x" * 100) < estimate_text_tokens("x" * 1000)

    def test_messages_include_tool_calls(self):
        msgs_plain = [{"role": "assistant", "content": "ok"}]
        msgs_tool = [{
            "role": "assistant", "content": None,
            "tool_calls": [{"function": {"name": "read_file", "arguments": '{"p": "x"}'}}],
        }]
        assert estimate_messages_tokens(msgs_tool) > estimate_messages_tokens(msgs_plain)

    def test_budget_threshold(self):
        b = ContextBudget(max_tokens=1000, ratio=0.8)
        assert b.threshold == 800
        small = [{"role": "user", "content": "hi"}]
        big = [{"role": "user", "content": "x" * 5000}]
        assert not b.is_over_budget(small)
        assert b.is_over_budget(big)


def _make_agent(messages: list[dict]) -> Agent:
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
    return agent


class TestBudgetGuard:
    @pytest.fixture(autouse=True)
    def budget_config(self, monkeypatch):
        monkeypatch.setattr(config, "CONTEXT_MAX_TOKENS", 300)
        monkeypatch.setattr(config, "CONTEXT_BUDGET_RATIO", 0.8)
        monkeypatch.setattr(config, "COMPRESS_THRESHOLD", 8)
        monkeypatch.setattr(config, "COMPRESS_KEEP_RECENT", 2)

    def test_force_compress_when_over_budget(self):
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(12):
            msgs.append({"role": "user" if i % 2 == 0 else "assistant",
                         "content": f"很长的消息内容占位符 {i} " * 10})
        agent = _make_agent(msgs)
        before = len(agent._messages)
        agent._ensure_context_budget()
        # 强制压缩生效：消息数减少且插入摘要
        assert len(agent._messages) < before
        assert any("[历史对话摘要]" in (m.get("content") or "")
                   for m in agent._messages)

    def test_no_action_within_budget(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        agent = _make_agent(msgs)
        agent._ensure_context_budget()
        assert len(agent._messages) == 2

    def test_truncate_old_tool_results(self, monkeypatch):
        """压缩无法解决时，截断保留窗口外的旧 tool 大块结果。"""
        big = "A" * 5000
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "read_file", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": big},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "q2 " * 500},
            {"role": "assistant", "content": "a2"},
        ]
        agent = _make_agent(msgs)
        # 模拟压缩无效，验证截断分支
        monkeypatch.setattr(agent, "compress_history", lambda force=False: False)
        agent._ensure_context_budget()
        tool_msg = next(m for m in agent._messages if m["role"] == "tool")
        assert len(tool_msg["content"]) < 300
        assert "已截断" in tool_msg["content"]
        assert "5000" in tool_msg["content"]


# ──────────────────────────────────────────────
# D1: git 共现历史（真实 git 仓库）
# ──────────────────────────────────────────────
def _git_cmd(repo, args):
    subprocess.run(f"git {args}", shell=True, cwd=str(repo),
                   capture_output=True, text=True, check=True)


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
    _git_cmd(tmp_path, "init -q")
    _git_cmd(tmp_path, "config user.email t@t.com")
    _git_cmd(tmp_path, "config user.name tester")

    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text("import a\n")
    (tmp_path / "c.py").write_text("y = 2\n")

    # 提交 1、2: a.py 与 b.py 一起（2 次）
    for _ in range(2):
        _git_cmd(tmp_path, "add -A")
        _git_cmd(tmp_path, "commit -q -m pair-ab")
        (tmp_path / "a.py").write_text((tmp_path / "a.py").read_text() + "z = 9\n")
        (tmp_path / "b.py").write_text((tmp_path / "b.py").read_text() + "# n\n")
    _git_cmd(tmp_path, "add -A")
    _git_cmd(tmp_path, "commit -q -m pair-ab2")

    # 提交 3: a.py 与 c.py 一起（1 次）
    (tmp_path / "a.py").write_text((tmp_path / "a.py").read_text() + "w = 3\n")
    (tmp_path / "c.py").write_text((tmp_path / "c.py").read_text() + "# c\n")
    _git_cmd(tmp_path, "add -A")
    _git_cmd(tmp_path, "commit -q -m pair-ac")
    return tmp_path


class TestGitCoOccurrence:
    def test_co_occurrence_ranking(self, git_repo):
        result = _git_co_occurrence("a.py")
        names = [f for f, _ in result]
        counts = dict(result)
        assert "b.py" in names and "c.py" in names
        assert "a.py" not in names  # 排除自身
        assert counts["b.py"] > counts["c.py"]  # 高频共现排前
        assert result[0][0] == "b.py"

    def test_get_related_files_includes_co_occurrence(self, git_repo):
        out = get_related_files("a.py")
        assert "git 共现历史" in out
        assert "b.py" in out
        # 引用关系：b.py 中 import a
        assert "引用关系" in out

    def test_no_history(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
        assert _git_co_occurrence("nonexistent.py") == []


# ──────────────────────────────────────────────
# D3: 记忆按需注入
# ──────────────────────────────────────────────
MEMORY_MD = """# 项目记忆

本项目是一个 AI 编程助手 CLI。

## 沙箱与安全
沙箱使用 sandbox-exec 实现命令隔离，安全边界严格。

## 会话管理
会话历史支持压缩与摘要，防止上下文溢出。

## 部署说明
部署时使用 pip 安装依赖并配置 .env 文件。
"""


class TestMemorySelection:
    def test_split_sections(self):
        sections = _split_sections(MEMORY_MD)
        titles = [t for t, _ in sections]
        assert titles[0] == "项目记忆"
        assert "沙箱与安全" in titles and "部署说明" in titles

    def test_extract_keywords(self):
        kw = _extract_keywords("修复 sandbox_exec 的沙箱问题")
        assert "sandbox_exec" in kw
        assert "沙箱" in kw

    def test_select_relevant_section(self):
        out = select_relevant_sections(MEMORY_MD, "沙箱命令为什么被拦截", 4000)
        assert "沙箱与安全" in out
        assert "项目记忆" in out  # 首段始终保留
        assert "部署说明" not in out  # 无关段落被过滤

    def test_no_match_fallback_full(self):
        out = select_relevant_sections(MEMORY_MD, "zzz qqq xxx", 4000)
        assert out == MEMORY_MD  # 无命中 → 全文兜底

    def test_budget_limit(self):
        out = select_relevant_sections(MEMORY_MD, "沙箱 会话 部署", 80)
        # 预算极小：只保留首段
        assert "项目记忆" in out
        assert "部署说明" not in out


class TestInjectRelevantMemory:
    def _agent(self):
        agent = Agent.__new__(Agent)
        agent._messages = [{"role": "system", "content": "sys"}]
        return agent

    def test_inject_when_memory_large(self, monkeypatch):
        monkeypatch.setattr(config, "MEMORY_FULL_INJECT_CHARS", 100)
        monkeypatch.setattr(config, "MEMORY_INJECT_BUDGET_CHARS", 4000)
        monkeypatch.setattr(core_module, "load_project_memory",
                            lambda workspace=None: MEMORY_MD)
        agent = self._agent()
        agent._inject_relevant_memory("沙箱命令被拦截了")
        assert len(agent._messages) == 2
        assert "与当前任务相关段落" in agent._messages[1]["content"]
        assert "沙箱" in agent._messages[1]["content"]

    def test_skip_when_memory_small(self, monkeypatch):
        monkeypatch.setattr(config, "MEMORY_FULL_INJECT_CHARS", 100000)
        monkeypatch.setattr(core_module, "load_project_memory",
                            lambda workspace=None: "小记忆")
        agent = self._agent()
        agent._inject_relevant_memory("任意问题")
        assert len(agent._messages) == 1  # 未注入

    def test_skip_when_no_memory(self, monkeypatch):
        monkeypatch.setattr(config, "MEMORY_FULL_INJECT_CHARS", 100)
        monkeypatch.setattr(core_module, "load_project_memory",
                            lambda workspace=None: "")
        agent = self._agent()
        agent._inject_relevant_memory("任意问题")
        assert len(agent._messages) == 1
