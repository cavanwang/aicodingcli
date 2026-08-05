"""项目记忆文件管理（兼容 Claude Code / Codex 生态）。

搜索优先级（按顺序查找，找到第一个即返回）：
1. {workspace}/.agent/memory.md  — 本 Agent 原生格式
2. {workspace}/CLAUDE.md         — Claude Code 生态标准
3. {workspace}/AGENTS.md         — Codex / OpenAI 生态标准
4. {workspace}/.agent.md          — 通用项目配置

功能：
- 读取/写入项目记忆文件（Markdown 格式，人类可读可编辑）
- 兼容 CLAUDE.md / AGENTS.md，与主流智能体生态互通
- 会话启动时自动加载，注入 system prompt
- Agent 可通过 save_memory 工具主动更新
- 首次会话无记忆时，引导 Agent 自动探索并生成初始记忆
"""

from __future__ import annotations

from pathlib import Path

import config
from agent.logger import get_logger

logger = get_logger(__name__)

# 兼容的记忆文件名（按优先级排序）
_COMPATIBLE_FILE_NAMES = [
    ".agent/memory.md",   # 本 Agent 原生格式
    "CLAUDE.md",          # Claude Code 生态标准
    "AGENTS.md",          # Codex / OpenAI 生态标准
    ".agent.md",          # 通用项目配置
]

# 原生保存路径（save 时始终写入这里）
MEMORY_DIR_NAME = ".agent"
MEMORY_FILE_NAME = "memory.md"


def get_memory_path(workspace: Path | None = None) -> Path:
    """获取原生项目记忆文件的完整路径（.agent/memory.md）。"""
    base = workspace or config.WORKSPACE_DIR
    return base / MEMORY_DIR_NAME / MEMORY_FILE_NAME


def find_memory_file(workspace: Path | None = None) -> Path | None:
    """按优先级查找项目记忆文件，返回第一个存在的路径。

    搜索顺序：.agent/memory.md → CLAUDE.md → AGENTS.md → .agent.md
    都不存在时返回 None。
    """
    base = workspace or config.WORKSPACE_DIR
    for rel_path in _COMPATIBLE_FILE_NAMES:
        candidate = base / rel_path
        if candidate.is_file():
            return candidate
    return None


def load_project_memory(workspace: Path | None = None) -> str:
    """加载项目记忆文件内容（兼容 CLAUDE.md / AGENTS.md）。

    按优先级查找：.agent/memory.md → CLAUDE.md → AGENTS.md → .agent.md
    找到第一个存在的文件即返回其内容。

    Returns:
        记忆文件文本内容，不存在返回空字符串
    """
    memory_path = find_memory_file(workspace)
    if memory_path is None:
        logger.debug("项目记忆文件不存在（已搜索所有兼容路径）")
        return ""

    try:
        content = memory_path.read_text(encoding="utf-8").strip()
        if content:
            rel = memory_path.relative_to(workspace or config.WORKSPACE_DIR)
            logger.info("已加载项目记忆: %s (%d 字符)", rel, len(content))
        return content
    except Exception as e:
        logger.warning("读取项目记忆失败: %s", e)
        return ""


def save_project_memory(content: str, workspace: Path | None = None) -> str:
    """保存项目记忆到文件。

    Args:
        content: Markdown 格式的记忆内容
        workspace: 工作目录（默认使用 config.WORKSPACE_DIR）

    Returns:
        操作结果描述
    """
    if not content or not content.strip():
        return "❌ 记忆内容不能为空"

    memory_path = get_memory_path(workspace)

    try:
        # 确保目录存在
        memory_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入文件
        memory_path.write_text(content.strip() + "\n", encoding="utf-8")
        logger.info("项目记忆已保存: %s (%d 字符)", memory_path, len(content))
        return f"✅ 项目记忆已保存到 {memory_path.relative_to(config.WORKSPACE_DIR)}"
    except Exception as e:
        logger.error("保存项目记忆失败: %s", e)
        return f"❌ 保存失败: {e}"


def append_project_memory(section: str, content: str, workspace: Path | None = None) -> str:
    """向项目记忆追加内容（如果 section 已存在则替换，否则追加）。

    Args:
        section: 章节标题（如 "## 模块职责"）
        content: 章节内容
        workspace: 工作目录

    Returns:
        操作结果描述
    """
    memory_path = get_memory_path(workspace)

    try:
        # 读取现有内容
        existing = ""
        if memory_path.is_file():
            existing = memory_path.read_text(encoding="utf-8")

        # 检查 section 是否已存在
        section_header = section.strip()
        if section_header in existing:
            # 替换已有 section（简单实现：找到 section 开始到下一个同级 section）
            lines = existing.split("\n")
            new_lines = []
            skip = False
            section_level = section_header.count("#")

            for line in lines:
                if line.strip() == section_header:
                    skip = True
                    # 写入新 section
                    new_lines.append(section_header)
                    new_lines.append(content.strip())
                    new_lines.append("")
                    continue

                if skip:
                    # 检查是否到了下一个同级或更高级 section
                    if line.startswith("#" * section_level) and line.strip() != section_header:
                        skip = False
                    else:
                        continue

                new_lines.append(line)

            updated = "\n".join(new_lines)
        else:
            # 追加新 section
            if existing and not existing.endswith("\n"):
                existing += "\n"
            updated = existing + f"\n{section_header}\n{content.strip()}\n"

        # 写入
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_path.write_text(updated, encoding="utf-8")
        logger.info("项目记忆已追加: section=%s", section_header)
        return f"✅ 已更新章节: {section_header}"
    except Exception as e:
        logger.error("追加项目记忆失败: %s", e)
        return f"❌ 追加失败: {e}"


def _split_sections(content: str) -> list[tuple[str, str]]:
    """按 Markdown 标题（# / ## / ###）切分记忆为段落。

    返回 [(标题, 段落全文)]；标题前的前导文本归入 "<概述>" 段。
    """
    sections: list[tuple[str, str]] = []
    current_title = "<概述>"
    current_lines: list[str] = []
    for line in content.splitlines(keepends=True):
        if line.startswith("#"):
            if "".join(current_lines).strip():
                sections.append((current_title, "".join(current_lines)))
            current_title = line.strip().lstrip("#").strip() or "<标题>"
            current_lines = [line]
        else:
            current_lines.append(line)
    if "".join(current_lines).strip():
        sections.append((current_title, "".join(current_lines)))
    return sections


def _extract_keywords(text: str) -> set[str]:
    """从用户消息提取关键词：ASCII 单词（≥2字符）+ 中文二元组。"""
    import re
    words = set(w.lower() for w in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{1,}", text))
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = {cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)}
    return words | bigrams


def select_relevant_sections(content: str, user_message: str,
                             budget_chars: int) -> str:
    """按当前任务关键词筛选记忆段落（任务 D3 按需注入）。

    规则：
    - 首段（概述）始终保留
    - 其余段落按关键词命中得分降序，在预算内选取
    - 无任何命中时返回全文（宁多勿漏，避免错误过滤）
    """
    sections = _split_sections(content)
    if not sections:
        return content

    keywords = _extract_keywords(user_message or "")
    scored: list[tuple[int, int, str, str]] = []  # (score, idx, title, text)
    for idx, (title, text) in enumerate(sections):
        low = (title + "\n" + text).lower()
        score = sum(low.count(k) for k in keywords)
        scored.append((score, idx, title, text))

    if all(s[0] == 0 for s in scored):
        return content  # 无命中 → 全文注入兜底

    # 首段必留 + 其余按得分降序
    picked: list[tuple[int, str, str]] = [(0, scored[0][2], scored[0][3])]
    used = len(scored[0][3])
    for score, idx, title, text in sorted(scored[1:], key=lambda s: (-s[0], s[1])):
        if score <= 0:
            break
        if used + len(text) > budget_chars:
            continue
        picked.append((idx, title, text))
        used += len(text)

    picked.sort(key=lambda p: p[0])  # 恢复原文顺序
    return "".join(text for _, _, text in picked)


def build_project_memory_prompt(workspace: Path | None = None) -> str:
    """构建项目记忆注入文本，用于追加到 system prompt。

    如果记忆文件存在，直接返回内容。
    如果不存在，返回首次探索引导提示（让 Agent 主动生成初始记忆）。

    Returns:
        用于注入的文本
    """
    content = load_project_memory(workspace)
    if content:
        return f"[项目记忆（跨会话持久化）]\n{content}"

    # 无记忆文件 — 引导 Agent 首次探索
    return (
        "[项目记忆]\n"
        "当前项目尚无记忆文件。请在对话开始时：\n"
        "1. 用 list_directory 查看项目根目录结构\n"
        "2. 用 read_file 读取关键文件（如 README.md、main.py、package.json 等）\n"
        "3. 理解项目后，用 save_memory 工具保存初始项目记忆\n"
        "   内容包括：项目简介、技术栈、目录结构、核心模块职责、常用命令\n"
        "   保存后下次会话将自动加载，无需重复探索"
    )
