"""启动时自动扫描项目结构，注入上下文。"""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
import config

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".pytest_cache", ".aicoding_recovery"}
IGNORE_FILES = {".DS_Store", "package-lock.json", "yarn.lock", ".gitignore"}

# 最大遍历深度
_MAX_DEPTH = 3
# 文件树最多显示条目数
_MAX_TREE_ENTRIES = 100

# 关键文件识别表
_KEY_FILES: dict[str, str] = {
    "README.md": "项目说明",
    "README": "项目说明",
    "CHANGELOG.md": "变更日志",
    "LICENSE": "许可证",
    "requirements.txt": "Python 依赖配置",
    "pyproject.toml": "Python 项目配置",
    "setup.py": "Python 安装配置",
    "setup.cfg": "Python 项目配置",
    "Pipfile": "Python 依赖配置",
    "package.json": "Node.js 依赖配置",
    "tsconfig.json": "TypeScript 配置",
    "webpack.config.js": "Webpack 配置",
    "vite.config.js": "Vite 配置",
    "vite.config.ts": "Vite 配置",
    "go.mod": "Go 模块配置",
    "Cargo.toml": "Rust 项目配置",
    "pom.xml": "Maven 配置",
    "build.gradle": "Gradle 配置",
    "Dockerfile": "Docker 配置",
    "docker-compose.yml": "Docker Compose 配置",
    "docker-compose.yaml": "Docker Compose 配置",
    ".env": "环境变量配置",
    ".env.example": "环境变量示例",
    "Makefile": "Make 构建配置",
    "main.py": "Python 入口文件",
    "app.py": "Python 入口文件",
    "manage.py": "Django 管理入口",
    "wsgi.py": "WSGI 入口",
    "index.js": "Node.js 入口文件",
    "index.ts": "TypeScript 入口文件",
    "server.js": "Node.js 服务端入口",
    "server.ts": "TypeScript 服务端入口",
}

# 扩展名到语言名映射
_EXT_LANGUAGE: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".jsx": "JSX",
    ".tsx": "TSX",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".cs": "C#",
    ".swift": "Swift",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".less": "Less",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".xml": "XML",
    ".md": "Markdown",
    ".txt": "Text",
    ".sh": "Shell",
    ".bash": "Shell",
    ".sql": "SQL",
    ".graphql": "GraphQL",
    ".proto": "Protobuf",
    ".ini": "INI",
    ".cfg": "Config",
    ".conf": "Config",
}


def detect_project_type() -> str:
    """检测项目语言类型。"""
    base = config.WORKSPACE_DIR
    markers = {
        "package.json": "Node.js",
        "pyproject.toml": "Python",
        "setup.py": "Python",
        "requirements.txt": "Python",
        "go.mod": "Go",
        "Cargo.toml": "Rust",
        "pom.xml": "Java",
        "build.gradle": "Java",
    }
    for filename, lang in markers.items():
        if (base / filename).exists():
            return lang
    return "未知"


# ──────────────────────────────────────────────
# 框架检测
# ──────────────────────────────────────────────

# Python 框架 → 依赖包名映射
_PYTHON_FRAMEWORKS: dict[str, list[str]] = {
    "Django": ["django"],
    "Flask": ["flask"],
    "FastAPI": ["fastapi"],
    "Tornado": ["tornado"],
    "Starlette": ["starlette"],
    "Sanic": ["sanic"],
    "Celery": ["celery"],
    "Scrapy": ["scrapy"],
    "Pytest": ["pytest"],
    "NumPy": ["numpy"],
    "Pandas": ["pandas"],
}

# Node.js 框架 → 依赖包名映射
_NODE_FRAMEWORKS: dict[str, list[str]] = {
    "React": ["react", "react-dom"],
    "Vue": ["vue"],
    "Next.js": ["next"],
    "Nuxt": ["nuxt"],
    "Express": ["express"],
    "Koa": ["koa"],
    "Fastify": ["fastify"],
    "NestJS": ["@nestjs/core"],
    "Svelte": ["svelte"],
    "Angular": ["@angular/core"],
    "Tailwind CSS": ["tailwindcss"],
    "Vite": ["vite"],
    "Webpack": ["webpack"],
    "Jest": ["jest"],
    "Vitest": ["vitest"],
}


def _read_requirements() -> set[str]:
    """从 requirements.txt 读取已安装的包名集合（小写）。"""
    req_file = config.WORKSPACE_DIR / "requirements.txt"
    if not req_file.exists():
        return set()
    packages: set[str] = set()
    for line in req_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 提取包名（去掉版本约束）
        name = re.split(r'[\[>=<!]', line, maxsplit=1)[0].strip().lower()
        if name:
            packages.add(name)
    return packages


def _read_pyproject_deps() -> set[str]:
    """从 pyproject.toml 读取依赖包名集合（小写，简易解析）。"""
    toml_file = config.WORKSPACE_DIR / "pyproject.toml"
    if not toml_file.exists():
        return set()
    packages: set[str] = set()
    in_deps = False
    for line in toml_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("dependencies"):
            in_deps = True
            continue
        if in_deps:
            if stripped.startswith("]"):
                in_deps = False
                continue
            # 提取 "package_name>=1.0" 格式
            pkg = re.split(r'[\[>=<!]', stripped.strip('"').strip("'"), maxsplit=1)[0].strip().lower()
            if pkg:
                packages.add(pkg)
    return packages


def _read_package_json_deps() -> set[str]:
    """从 package.json 读取 dependencies + devDependencies 的包名集合。"""
    pkg_file = config.WORKSPACE_DIR / "package.json"
    if not pkg_file.exists():
        return set()
    try:
        data = json.loads(pkg_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return set()
    packages: set[str] = set()
    for section in ("dependencies", "devDependencies"):
        deps = data.get(section, {})
        if isinstance(deps, dict):
            packages.update(k.lower() for k in deps.keys())
    return packages


def detect_frameworks() -> list[str]:
    """检测项目使用的框架和工具链，返回识别到的框架名列表。"""
    base = config.WORKSPACE_DIR
    frameworks: list[str] = []

    # Python 项目
    py_deps = _read_requirements() | _read_pyproject_deps()
    if py_deps:
        for fw, markers in _PYTHON_FRAMEWORKS.items():
            if any(m in py_deps for m in markers):
                frameworks.append(fw)

    # Node.js 项目
    node_deps = _read_package_json_deps()
    if node_deps:
        for fw, markers in _NODE_FRAMEWORKS.items():
            if any(m in node_deps for m in markers):
                frameworks.append(fw)

    # Go 项目（通过 go.mod 检测）
    go_mod = base / "go.mod"
    if go_mod.exists():
        frameworks.append("Go Modules")

    # Rust 项目
    cargo = base / "Cargo.toml"
    if cargo.exists():
        frameworks.append("Cargo")

    # Docker
    if (base / "Dockerfile").exists():
        frameworks.append("Docker")
    if (base / "docker-compose.yml").exists() or (base / "docker-compose.yaml").exists():
        frameworks.append("Docker Compose")

    return frameworks


def scan_project() -> str:
    """扫描项目目录，生成文件树、类型统计和关键文件识别结果。"""
    base = config.WORKSPACE_DIR
    if not base.exists():
        return "(工作目录不存在)"

    tree_lines: list[str] = []
    ext_counter: Counter[str] = Counter()
    key_files: list[tuple[str, str]] = []  # (path_str, description)
    total_files = 0
    truncated = False

    def _scan_dir(dir_path: Path, prefix: str, depth: int) -> None:
        nonlocal total_files, truncated

        if depth > _MAX_DEPTH or truncated:
            return

        try:
            entries = sorted(
                dir_path.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except PermissionError:
            return

        # 过滤忽略项
        entries = [
            e for e in entries
            if not (e.is_dir() and e.name in IGNORE_DIRS)
            and not (e.is_file() and e.name in IGNORE_FILES)
        ]

        for i, entry in enumerate(entries):
            if truncated:
                return

            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "

            if entry.is_dir():
                tree_lines.append(f"{prefix}{connector}{entry.name}/")
                total_files += 1
                if total_files >= _MAX_TREE_ENTRIES:
                    truncated = True
                    return
                extension = "└── " if is_last else "│   "
                _scan_dir(entry, prefix + extension, depth + 1)
            else:
                tree_lines.append(f"{prefix}{connector}{entry.name}")
                total_files += 1
                if total_files >= _MAX_TREE_ENTRIES:
                    truncated = True
                    return

                # 统计扩展名
                ext = entry.suffix.lower()
                if ext:
                    ext_counter[ext] += 1

                # 识别关键文件
                if entry.name in _KEY_FILES:
                    rel = str(entry.relative_to(base))
                    key_files.append((rel, _KEY_FILES[entry.name]))

    _scan_dir(base, "", 1)

    if truncated:
        remaining = _count_total_files(base) - total_files
        if remaining > 0:
            tree_lines.append(f"... 及其他 {remaining} 个文件")

    # ── 组装输出 ──
    sections: list[str] = []

    # 1. 文件树
    if tree_lines:
        sections.append("\n".join(tree_lines))
    else:
        sections.append("(空项目)")

    # 2. 文件类型统计
    if ext_counter:
        stats_lines = ["## 文件统计"]
        for ext, count in ext_counter.most_common(15):
            lang = _EXT_LANGUAGE.get(ext, ext)
            stats_lines.append(f"- {lang} ({ext}): {count} 个")
        sections.append("\n".join(stats_lines))

    # 3. 关键文件
    if key_files:
        key_lines = ["## 关键文件"]
        for path_str, desc in key_files:
            key_lines.append(f"- {path_str} ({desc})")
        sections.append("\n".join(key_lines))

    return "\n\n".join(sections)


def _count_total_files(base: Path) -> int:
    """粗略统计工作区文件总数（用于截断提示）。"""
    count = 0
    for path in base.rglob("*"):
        if path.is_file() and path.name not in IGNORE_FILES:
            # 检查是否在忽略目录下
            if not any(part in IGNORE_DIRS for part in path.parts):
                count += 1
    return count


# ──────────────────────────────────────────────
# 项目类型提示词生成
# ──────────────────────────────────────────────

# 框架 → 常用命令提示
_FRAMEWORK_TIPS: dict[str, list[str]] = {
    "Django": [
        "运行服务: python manage.py runserver",
        "运行测试: python manage.py test",
        "数据库迁移: python manage.py migrate",
    ],
    "Flask": [
        "运行服务: flask run 或 python app.py",
        "运行测试: pytest",
    ],
    "FastAPI": [
        "运行服务: uvicorn main:app --reload",
        "API 文档: http://localhost:8000/docs",
        "运行测试: pytest",
    ],
    "React": [
        "启动开发: npm start 或 npm run dev",
        "构建: npm run build",
        "运行测试: npm test",
    ],
    "Vue": [
        "启动开发: npm run dev",
        "构建: npm run build",
    ],
    "Next.js": [
        "启动开发: npm run dev",
        "构建: npm run build",
    ],
    "Express": [
        "启动服务: node server.js 或 npm start",
    ],
    "NestJS": [
        "启动开发: npm run start:dev",
        "构建: npm run build",
    ],
    "Go Modules": [
        "运行: go run .",
        "构建: go build",
        "测试: go test ./...",
    ],
    "Cargo": [
        "运行: cargo run",
        "构建: cargo build",
        "测试: cargo test",
    ],
    "Docker": [
        "构建镜像: docker build -t <name> .",
        "运行容器: docker run <name>",
    ],
}

# 语言 → 通用提示（无框架时使用）
_LANGUAGE_TIPS: dict[str, list[str]] = {
    "Python": [
        "运行脚本: python <file.py>",
        "运行测试: pytest",
        "安装依赖: pip install -r requirements.txt",
    ],
    "Node.js": [
        "运行脚本: node <file.js>",
        "安装依赖: npm install",
    ],
    "Go": [
        "运行: go run .",
        "测试: go test ./...",
    ],
    "Rust": [
        "运行: cargo run",
        "测试: cargo test",
    ],
    "Java": [
        "构建: mvn package 或 gradle build",
    ],
}


def generate_project_tips(project_type: str, frameworks: list[str]) -> list[str]:
    """根据项目类型和框架生成常用命令提示。"""
    tips: list[str] = []

    # 优先使用框架级提示
    for fw in frameworks:
        if fw in _FRAMEWORK_TIPS:
            tips.extend(_FRAMEWORK_TIPS[fw])

    # 如果没有框架级提示，使用语言级提示
    if not tips and project_type in _LANGUAGE_TIPS:
        tips.extend(_LANGUAGE_TIPS[project_type])

    return tips


def build_context() -> str:
    """组装完整的项目上下文，给 system prompt 用。"""
    project_type = detect_project_type()
    frameworks = detect_frameworks()
    scan_result = scan_project()
    tips = generate_project_tips(project_type, frameworks)

    type_line = f"- 类型：{project_type}"
    if frameworks:
        type_line += f" ({', '.join(frameworks)})"

    sections = [
        f"""## 当前项目
{type_line}
- 工作目录：{config.WORKSPACE_DIR}""",
        scan_result,
    ]

    if tips:
        tips_lines = ["## 常用命令参考"]
        for tip in tips:
            tips_lines.append(f"- {tip}")
        sections.append("\n".join(tips_lines))

    return "\n\n".join(sections) + "\n"