"""项目级配置加载器。

加载两层配置并注入 system prompt：
- 全局配置：~/.aicoding/config.md（所有项目共享）
- 项目配置：{project}/.agent.md 或 {project}/AGENT.md（项目专属）

项目配置覆盖全局配置。
"""

from __future__ import annotations

from pathlib import Path

from agent.logger import get_logger

logger = get_logger(__name__)

# 配置文件名（按优先级查找）
PROJECT_CONFIG_NAMES = [".agent.md", "AGENT.md"]
GLOBAL_CONFIG_PATH = Path.home() / ".aicoding" / "config.md"


def find_project_config(project_dir: Path) -> Path | None:
    """在项目目录中查找配置文件。

    Args:
        project_dir: 项目根目录

    Returns:
        配置文件路径，未找到返回 None
    """
    for name in PROJECT_CONFIG_NAMES:
        path = project_dir / name
        if path.is_file():
            return path
    return None


def load_global_config() -> str:
    """加载全局配置内容。

    Returns:
        全局配置文本，不存在返回空字符串
    """
    if GLOBAL_CONFIG_PATH.is_file():
        try:
            content = GLOBAL_CONFIG_PATH.read_text(encoding="utf-8").strip()
            logger.info("已加载全局配置: %s (%d 字符)", GLOBAL_CONFIG_PATH, len(content))
            return content
        except Exception as e:
            logger.warning("读取全局配置失败: %s", e)
    return ""


def load_project_config(project_dir: Path) -> str:
    """加载项目配置内容。

    Args:
        project_dir: 项目根目录

    Returns:
        项目配置文本，不存在返回空字符串
    """
    config_path = find_project_config(project_dir)
    if config_path is None:
        return ""

    try:
        content = config_path.read_text(encoding="utf-8").strip()
        logger.info("已加载项目配置: %s (%d 字符)", config_path, len(content))
        return content
    except Exception as e:
        logger.warning("读取项目配置失败: %s", e)
        return ""


def build_project_prompt(project_dir: Path) -> str:
    """构建项目配置注入文本。

    规则：
    - 全局配置 + 项目配置都存在时，项目配置追加在全局配置之后
    - 只有项目配置时，只使用项目配置
    - 只有全局配置时，只使用全局配置
    - 都没有时，返回空字符串

    Returns:
        用于追加到 system prompt 的文本
    """
    global_content = load_global_config()
    project_content = load_project_config(project_dir)

    parts = []

    if global_content:
        parts.append("[全局项目配置]\n" + global_content)

    if project_content:
        parts.append("[项目专属配置]\n" + project_content)

    if not parts:
        return ""

    return "\n\n".join(parts)
