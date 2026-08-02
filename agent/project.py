"""启动时自动扫描项目结构，注入上下文。"""

from pathlib import Path
import config

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
IGNORE_FILES = {".DS_Store", "package-lock.json", "yarn.lock"}


def detect_project_type() -> str:
    """检测项目类型。"""
    base = config.WORKSPACE_DIR
    markers = {
        "package.json": "Node.js",
        "pyproject.toml": "Python",
        "setup.py": "Python",
        "go.mod": "Go",
        "Cargo.toml": "Rust",
        "pom.xml": "Java",
    }
    for filename, lang in markers.items():
        if (base / filename).exists():
            return lang
    return "未知"


def scan_project() -> str:
    """生成项目结构摘要（你原来的代码，不用改）。"""
    lines = []
    base = config.WORKSPACE_DIR
    # ... 你原来的逻辑 ...
    return "\n".join(lines) if lines else "(空项目)"


def build_context() -> str:
    """组装完整的项目上下文，给 system prompt 用。"""
    project_type = detect_project_type()
    tree = scan_project()
    return f"""## 当前项目
- 类型：{project_type}
- 工作目录：{config.WORKSPACE_DIR}

## 文件结构
{tree}
"""