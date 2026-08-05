# Auto-generated fallback for optional dependency: pandas
try:
    import pandas as pandas
except ImportError:  # pragma: no cover - optional dependency fallback
    pandas = None

"""错误自愈辅助模块。

提供轻量级错误分类与修复提示生成，供 Agent 在命令失败后自动进入
"分析 → 修复 → 重试"的循环。
"""

from __future__ import annotations

import re
from typing import Any

from agent.repair_executor import execute_repair


def _extract_file_path(text: str) -> str | None:
    """从报错文本中提取文件路径。"""
    # 匹配 File "xxx" 或 'xxx' 格式
    m = re.search(r'File\s+["\']([^"\']+)["\']', text)
    if m:
        return m.group(1)
    # 匹配带扩展名的路径引用
    m = re.search(
        r'["\']([A-Za-z0-9_./\\-]+\.(?:py|js|ts|go|rs|java|md|txt|json|yaml|yml|toml))["\']',
        text,
    )
    return m.group(1) if m else None


def _extract_line_number(text: str) -> int | None:
    """从报错文本中提取行号。"""
    m = re.search(r'line\s+(\d+)', text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _enrich_classification(result: dict[str, Any], details: str) -> dict[str, Any]:
    """为分类结果补充结构化字段。"""
    result["file_path"] = _extract_file_path(details)
    result["line_number"] = _extract_line_number(details)
    return result


def classify_error(output: str) -> dict[str, Any]:
    """根据命令输出内容判断失败类型，并提取结构化字段。"""
    text = (output or "").strip()
    lowered = text.lower()

    if (
        "syntaxerror" in lowered
        or "indentationerror" in lowered
        or "invalid syntax" in lowered
    ):
        return _enrich_classification({
            "error_type": "syntax",
            "summary": "发现语法错误",
            "details": text,
            "suggested_action": "fix_code",
            "confidence": "high",
        }, text)

    if (
        "modulenotfounderror" in lowered
        or "no module named" in lowered
        or "command not found" in lowered
    ):
        return _enrich_classification({
            "error_type": "dependency",
            "summary": "可能存在依赖或环境问题",
            "details": text,
            "suggested_action": "install_dependency",
            "confidence": "high",
        }, text)

    if (
        "no such file" in lowered
        or "filenotfounderror" in lowered
        or "not found" in lowered
    ):
        return _enrich_classification({
            "error_type": "file_not_found",
            "summary": "找不到目标文件或路径",
            "details": text,
            "suggested_action": "fix_path",
            "confidence": "medium",
        }, text)

    if "assertionerror" in lowered or "failed" in lowered and "test" in lowered:
        return _enrich_classification({
            "error_type": "test_failure",
            "summary": "测试或断言失败",
            "details": text,
            "suggested_action": "fix_test_or_logic",
            "confidence": "medium",
        }, text)

    if "permission denied" in lowered or "eacces" in lowered:
        return _enrich_classification({
            "error_type": "permission",
            "summary": "权限不足",
            "details": text,
            "suggested_action": "adjust_permissions_or_command",
            "confidence": "medium",
        }, text)

    return _enrich_classification({
        "error_type": "unknown",
        "summary": "未知错误",
        "details": text,
        "suggested_action": "inspect_output",
        "confidence": "low",
    }, text)


def build_recovery_prompt(
    tool_name: str,
    output: str,
    history: list[dict[str, Any]] | None = None,
    attempt_number: int = 1,
    max_attempts: int = 3,
) -> str:
    """基于错误分类结果生成给模型的修复提示。"""
    classification = classify_error(output)
    error_type = classification["error_type"]
    suggested_action = classification["suggested_action"]

    history_lines = []
    if history:
        for item in history[-3:]:
            summary = item.get("summary") or "未知错误"
            history_lines.append(f"- {summary}")

    history_block = (
        "\n历史失败记录:\n" + "\n".join(history_lines) if history_lines else ""
    )

    strategy = build_recovery_strategy(classification)

    repair_result = execute_repair(classification)

    return (
        "错误自愈：上一步工具执行失败。"
        f"工具: {tool_name}\n"
        f"错误类型: {error_type}\n"
        f"建议动作: {suggested_action}\n"
        f"修复策略: {strategy}\n"
        f"自动修复动作: {repair_result}\n"
        f"第 {attempt_number}/{max_attempts} 次重试\n"
        "请先分析报错内容，优先进行最小范围修复，然后重新执行验证。"
        f"{history_block}\n"
        f"原始输出:\n{output}"
    )


def build_recovery_strategy(classification: dict[str, Any]) -> str:
    """根据错误分类生成一个简短的下一步行动策略。"""
    error_type = classification.get("error_type", "unknown")

    strategies = {
        "syntax": "先读取相关源码，定位报错行，并修正语法问题。",
        "dependency": "先检查依赖文件并安装缺失依赖，然后重新执行命令。",
        "file_not_found": "先确认文件或路径是否存在，并修正引用。",
        "test_failure": "先查看测试输出，定位失败逻辑并修复。",
        "permission": "先确认当前环境权限和命令可用性，再调整执行方式。",
    }

    return strategies.get(error_type, "先查看报错输出，定位根因并进行最小修复。")
