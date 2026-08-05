"""项目记忆文件管理（类似 Claude Code 的 CLAUDE.md）。

存储位置：{workspace}/.agent/memory.md

功能：
- 读取/写入项目记忆文件（Markdown 格式，人类可读可编辑）
- 会话启动时自动加载，注入 system prompt
- Agent 可通过 save_project_memory 工具主动更新
- 记录项目架构、模块职责、编码规范、踩坑经验等
"""

from __future__ import annotations

from pathlib import Path

import config
from agent.logger import get_logger

logger = get_logger(__name__)

# 项目记忆文件路径：{workspace}/.agent/memory.md
MEMORY_DIR_NAME = ".agent"
MEMORY_FILE_NAME = "memory.md"


def get_memory_path(workspace: Path | None = None) -> Path:
    """获取项目记忆文件的完整路径。"""
    base = workspace or config.WORKSPACE_DIR
    return base / MEMORY_DIR_NAME / MEMORY_FILE_NAME


def load_project_memory(workspace: Path | None = None) -> str:
    """加载项目记忆文件内容。

    Returns:
        记忆文件文本内容，不存在返回空字符串
    """
    memory_path = get_memory_path(workspace)
    if not memory_path.is_file():
        logger.debug("项目记忆文件不存在: %s", memory_path)
        return ""

    try:
        content = memory_path.read_text(encoding="utf-8").strip()
        if content:
            logger.info("已加载项目记忆: %s (%d 字符)", memory_path, len(content))
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


def build_project_memory_prompt(workspace: Path | None = None) -> str:
    """构建项目记忆注入文本，用于追加到 system prompt。

    Returns:
        用于注入的文本，无记忆返回空字符串
    """
    content = load_project_memory(workspace)
    if not content:
        return ""

    return f"[项目记忆（跨会话持久化）]\n{content}"
