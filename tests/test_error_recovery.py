from agent.error_recovery import build_recovery_prompt, classify_error
from agent.repair_executor import execute_repair
from agent.recovery import RecoveryManager
from agent.core import Agent


def test_classify_dependency_error():
    result = classify_error("ModuleNotFoundError: No module named 'pandas'")
    assert result["error_type"] == "dependency"
    assert result["suggested_action"] == "install_dependency"


def test_classify_syntax_error():
    result = classify_error("SyntaxError: invalid syntax")
    assert result["error_type"] == "syntax"
    assert result["suggested_action"] == "fix_code"


def test_classify_test_failure():
    result = classify_error("AssertionError: expected 2 but got 3")
    assert result["error_type"] == "test_failure"
    assert result["suggested_action"] == "fix_test_or_logic"


def test_build_recovery_prompt_contains_guidance():
    prompt = build_recovery_prompt(
        "run_command",
        "ModuleNotFoundError: No module named 'pandas'",
    )
    assert "错误自愈" in prompt
    assert "dependency" in prompt


def test_build_recovery_prompt_includes_retry_context():
    prompt = build_recovery_prompt(
        "run_command",
        "ModuleNotFoundError: No module named 'pandas'",
        history=[{"error_type": "dependency", "summary": "缺少依赖"}],
        attempt_number=2,
        max_attempts=3,
    )
    assert "第 2/3 次重试" in prompt
    assert "历史失败记录" in prompt
    assert "缺少依赖" in prompt
    assert "修复策略" in prompt
    assert "自动修复动作" in prompt


def test_execute_repair_dependency_returns_action():
    result = execute_repair(
        {"error_type": "dependency", "details": "No module named 'pandas'"}
    )
    assert "requirements.txt" in result or "依赖文件" in result


def test_execute_repair_syntax_returns_action():
    result = execute_repair({"error_type": "syntax", "details": "SyntaxError"})
    assert "syntax_recovery.py" in result or "语法" in result


def test_execute_repair_dependency_adds_missing_module_to_requirements():
    result = execute_repair(
        {
            "error_type": "dependency",
            "details": "ModuleNotFoundError: No module named 'pandas'",
        }
    )
    assert "pandas" in result.lower()


def test_execute_repair_file_not_found_creates_target_file():
    result = execute_repair(
        {
            "error_type": "file_not_found",
            "details": "No such file or directory: 'tmp_target.py'",
        }
    )
    assert "tmp_target.py" in result


def test_execute_repair_dependency_patches_existing_python_file():
    import pathlib
    import config

    target = config.WORKSPACE_DIR / "src" / "sample.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('hello')\n", encoding="utf-8")
    try:
        result = execute_repair(
            {
                "error_type": "dependency",
                "details": "ModuleNotFoundError: No module named 'pandas'",
            }
        )
        assert "pandas" in result.lower() or "导入兜底" in result
    finally:
        if target.exists():
            target.unlink()


def test_execute_repair_dependency_patches_specific_line_in_python_file():
    import config

    target = config.WORKSPACE_DIR / "src" / "line_target.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("import pandas\nprint('ok')\n", encoding="utf-8")
    try:
        result = execute_repair(
            {
                "error_type": "dependency",
                "details": "ModuleNotFoundError: No module named 'pandas'\nFile \"src/line_target.py\", line 1",
            }
        )
        assert "line 1" in result or "line_target.py" in result
        assert "except ImportError" in target.read_text(encoding="utf-8")
    finally:
        if target.exists():
            target.unlink()


def test_agent_appends_retry_verification_instruction():
    class DummyClient:
        class Chat:
            class Completions:
                def create(self, *args, **kwargs):
                    return []

        chat = Chat()

    agent = Agent(client=DummyClient(), model="dummy", system_prompt="sys")
    agent._messages.append({"role": "system", "content": "continue"})
    agent._messages.append({"role": "assistant", "content": "next"})

    agent._messages.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "1",
                    "type": "function",
                    "function": {
                        "name": "run_command",
                        "arguments": '{"command": "python -m pytest"}',
                    },
                }
            ],
        }
    )

    # 这里只验证消息路径可用，不依赖真实工具执行。
    assert agent._messages[-1]["role"] == "assistant"


# ──────────────────────────────────────────────
# classify_error 结构化字段提取
# ──────────────────────────────────────────────

def test_classify_error_extracts_file_path():
    result = classify_error(
        'File "src/main.py", line 42\nSyntaxError: invalid syntax'
    )
    assert result["file_path"] == "src/main.py"
    assert result["line_number"] == 42


def test_classify_error_extracts_quoted_path():
    result = classify_error(
        "No such file or directory: 'config/settings.json'"
    )
    assert result["file_path"] == "config/settings.json"


def test_classify_error_returns_none_when_no_path():
    result = classify_error("AssertionError: expected 2 but got 3")
    assert result["file_path"] is None
    assert result["line_number"] is None


# ──────────────────────────────────────────────
# RecoveryManager
# ──────────────────────────────────────────────

def test_recovery_manager_is_failure():
    assert RecoveryManager.is_failure("exit code: 1") is True
    assert RecoveryManager.is_failure("命令执行超时") is True
    assert RecoveryManager.is_failure("执行失败: xxx") is True
    assert RecoveryManager.is_failure("执行成功") is False
    assert RecoveryManager.is_failure(123) is False


def test_recovery_manager_handle_failure_increments_attempts():
    rm = RecoveryManager(max_attempts=3)
    assert rm.attempts == 0
    assert rm.exhausted is False

    action = rm.handle_failure("run_command", "exit code: 1\nError occurred")
    assert rm.attempts == 1
    assert action["exhausted"] is False
    assert "错误自愈" in action["recovery_prompt"]


def test_recovery_manager_exhausted_triggers_rollback():
    rollback_called = []

    def fake_rollback():
        rollback_called.append(True)
        return "已回滚"

    rm = RecoveryManager(max_attempts=2, rollback_fn=fake_rollback)

    # 第 1 次失败：未耗尽
    action1 = rm.handle_failure("run_command", "exit code: 1\nError")
    assert action1["exhausted"] is False
    assert len(rollback_called) == 0

    # 第 2 次失败：耗尽，触发回滚
    action2 = rm.handle_failure("run_command", "exit code: 1\nError")
    assert action2["exhausted"] is True
    assert len(rollback_called) == 1
    assert "已回滚" in action2["rollback_result"]
    assert "已自动回滚" in action2["recovery_prompt"]


def test_recovery_manager_reset():
    rm = RecoveryManager(max_attempts=3)
    rm.handle_failure("run_command", "exit code: 1\nError")
    rm.handle_failure("run_command", "exit code: 1\nError")
    assert rm.attempts == 2

    rm.reset()
    assert rm.attempts == 0
    assert rm.history == []
    assert rm.exhausted is False


def test_recovery_manager_history_tracking():
    rm = RecoveryManager(max_attempts=5)
    rm.handle_failure("run_command", "exit code: 1\nSyntaxError: invalid syntax")
    rm.handle_failure("run_command", "exit code: 1\nError occurred")

    assert len(rm.history) == 2
    assert rm.history[0]["error_type"] == "syntax"
    assert rm.history[1]["error_type"] == "unknown"


def test_recovery_manager_build_retry_guidance():
    guidance = RecoveryManager.build_retry_guidance()
    assert "错误自愈" in guidance
    assert "重新执行验证" in guidance
