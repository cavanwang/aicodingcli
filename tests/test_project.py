"""项目上下文扫描模块测试。"""

import json
import shutil
from pathlib import Path

import config
from agent.project import scan_project, detect_project_type, detect_frameworks, generate_project_tips, build_context


TEST_DIR = config.WORKSPACE_DIR / "_test_scan_project"


def _setup_test_project():
    """创建一个临时测试项目结构。"""
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    TEST_DIR.mkdir(parents=True)

    # 创建文件结构
    (TEST_DIR / "src").mkdir()
    (TEST_DIR / "src" / "main.py").write_text("print('hello')\n")
    (TEST_DIR / "src" / "utils.py").write_text("def helper(): pass\n")
    (TEST_DIR / "tests").mkdir()
    (TEST_DIR / "tests" / "test_main.py").write_text("def test_ok(): pass\n")
    (TEST_DIR / "requirements.txt").write_text("flask\n")
    (TEST_DIR / "README.md").write_text("# Test Project\n")
    (TEST_DIR / ".env").write_text("KEY=value\n")

    # 创建应被忽略的目录
    (TEST_DIR / "__pycache__").mkdir()
    (TEST_DIR / "__pycache__" / "cached.pyc").write_text("")
    (TEST_DIR / ".git").mkdir()
    (TEST_DIR / ".git" / "config").write_text("")


def _cleanup_test_project():
    """清理临时测试项目。"""
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)


def test_scan_project_returns_tree_structure(monkeypatch):
    _setup_test_project()
    try:
        monkeypatch.setattr(config, "WORKSPACE_DIR", TEST_DIR)
        result = scan_project()

        # 应包含目录和文件
        assert "src/" in result
        assert "main.py" in result
        assert "utils.py" in result
        assert "tests/" in result
        assert "README.md" in result
    finally:
        _cleanup_test_project()


def test_scan_project_ignores_pycache_and_git(monkeypatch):
    _setup_test_project()
    try:
        monkeypatch.setattr(config, "WORKSPACE_DIR", TEST_DIR)
        result = scan_project()

        assert "__pycache__" not in result
        assert ".git" not in result
    finally:
        _cleanup_test_project()


def test_scan_project_includes_file_stats(monkeypatch):
    _setup_test_project()
    try:
        monkeypatch.setattr(config, "WORKSPACE_DIR", TEST_DIR)
        result = scan_project()

        assert "文件统计" in result
        assert "Python" in result
        assert ".py" in result
    finally:
        _cleanup_test_project()


def test_scan_project_identifies_key_files(monkeypatch):
    _setup_test_project()
    try:
        monkeypatch.setattr(config, "WORKSPACE_DIR", TEST_DIR)
        result = scan_project()

        assert "关键文件" in result
        assert "README.md" in result
        assert "项目说明" in result
        assert "requirements.txt" in result
        assert "依赖配置" in result
    finally:
        _cleanup_test_project()


def test_scan_project_empty_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
    result = scan_project()
    assert "空项目" in result


def test_detect_project_type_python(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
    assert detect_project_type() == "Python"


def test_detect_project_type_nodejs(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text("{}")
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
    assert detect_project_type() == "Node.js"


def test_detect_project_type_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
    assert detect_project_type() == "未知"


def test_build_context_contains_all_sections(monkeypatch):
    _setup_test_project()
    try:
        monkeypatch.setattr(config, "WORKSPACE_DIR", TEST_DIR)
        result = build_context()

        assert "当前项目" in result
        assert "工作目录" in result
        assert "src/" in result
        assert "文件统计" in result
        assert "关键文件" in result
    finally:
        _cleanup_test_project()


# ──────────────────────────────────────────────
# 框架检测
# ──────────────────────────────────────────────

def test_detect_frameworks_python_flask(monkeypatch, tmp_path):
    (tmp_path / "requirements.txt").write_text("flask>=2.0\nrequests\n")
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
    frameworks = detect_frameworks()
    assert "Flask" in frameworks


def test_detect_frameworks_python_django(monkeypatch, tmp_path):
    (tmp_path / "requirements.txt").write_text("Django==4.2\ncelery\n")
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
    frameworks = detect_frameworks()
    assert "Django" in frameworks
    assert "Celery" in frameworks


def test_detect_frameworks_nodejs_react(monkeypatch, tmp_path):
    pkg = {"dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
    frameworks = detect_frameworks()
    assert "React" in frameworks


def test_detect_frameworks_nodejs_express(monkeypatch, tmp_path):
    pkg = {"dependencies": {"express": "^4.18.0"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
    frameworks = detect_frameworks()
    assert "Express" in frameworks


def test_detect_frameworks_docker(monkeypatch, tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.11\n")
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
    frameworks = detect_frameworks()
    assert "Docker" in frameworks


def test_detect_frameworks_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
    assert detect_frameworks() == []


def test_build_context_includes_frameworks(monkeypatch, tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n")
    (tmp_path / "main.py").write_text("print('hello')\n")
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
    result = build_context()
    assert "FastAPI" in result


# ──────────────────────────────────────────────
# 项目提示词生成
# ──────────────────────────────────────────────

def test_generate_project_tips_flask():
    tips = generate_project_tips("Python", ["Flask"])
    assert any("flask run" in t for t in tips)
    assert any("pytest" in t for t in tips)


def test_generate_project_tips_react():
    tips = generate_project_tips("Node.js", ["React"])
    assert any("npm start" in t or "npm run dev" in t for t in tips)


def test_generate_project_tips_fallback_to_language():
    tips = generate_project_tips("Python", [])
    assert any("python" in t.lower() for t in tips)
    assert any("pytest" in t for t in tips)


def test_generate_project_tips_empty_for_unknown():
    tips = generate_project_tips("未知", [])
    assert tips == []


def test_build_context_includes_tips(monkeypatch, tmp_path):
    (tmp_path / "requirements.txt").write_text("flask\n")
    (tmp_path / "app.py").write_text("from flask import Flask\n")
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
    result = build_context()
    assert "常用命令参考" in result
    assert "flask run" in result
