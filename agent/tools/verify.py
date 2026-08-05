"""验证工具：修改后自动发现并运行相关测试。"""

import os
import subprocess
import sys
from pathlib import Path
import config


def verify_changes() -> str:
    """自动发现变更文件并运行相关测试。

    工作流程：
    1. 检测当前修改了哪些文件
    2. 根据文件命名规则找到相关测试
    3. 运行测试并返回结果
    """
    # 获取变更文件
    changed_files = _get_changed_files()
    if not changed_files:
        return "当前无文件变更，无需验证。"

    # 查找相关测试文件
    test_files = _find_related_tests(changed_files)
    if not test_files:
        return f"变更文件: {', '.join(changed_files)}\n\n未找到相关测试文件。"

    # 运行测试
    results = _run_tests(test_files)
    
    # 构建输出
    output = [f"📋 变更文件: {', '.join(changed_files)}"]
    output.append(f"🧪 相关测试: {', '.join(test_files)}")
    output.append("")
    output.append(results)
    
    return "\n".join(output)


def _get_changed_files() -> list[str]:
    """获取当前变更的文件列表（不包括测试文件本身）。"""
    try:
        result = subprocess.run(
            "git status --porcelain",
            shell=True, capture_output=True, text=True,
            timeout=10, cwd=str(config.WORKSPACE_DIR),
        )
        if result.returncode != 0:
            return []
        
        files = []
        for line in result.stdout.strip().split("\n"):
            if len(line) < 3:
                continue
            # 跳过删除的文件
            status = line[:2]
            if status in ("D ", " D"):
                continue
            
            file_path = line[2:].strip()
            # 排除测试文件本身
            if "/tests/" in file_path or file_path.startswith("tests/") or file_path.startswith("test_"):
                continue
            # 只包含源代码文件
            if file_path.endswith((".py", ".js", ".ts", ".jsx", ".tsx")):
                files.append(file_path)
        
        return files
    except Exception:
        return []


def _find_related_tests(changed_files: list[str]) -> list[str]:
    """根据变更文件查找相关测试文件。

    匹配规则：
    - core.py → test_core.py
    - agent/tools/file_ops.py → tests/test_file_ops.py
    - utils.py → test_utils.py 或 tests/test_utils.py
    """
    tests_dir = config.WORKSPACE_DIR / "tests"
    test_files = []
    
    for file_path in changed_files:
        path = Path(file_path)
        module_name = path.stem  # 不含扩展名的文件名
        
        # 可能的测试文件名模式
        patterns = [
            f"test_{module_name}.py",
            f"{module_name}_test.py",
        ]
        
        # 在 tests/ 目录下查找
        if tests_dir.exists():
            for pattern in patterns:
                test_path = tests_dir / pattern
                if test_path.exists():
                    rel_path = str(test_path.relative_to(config.WORKSPACE_DIR))
                    if rel_path not in test_files:
                        test_files.append(rel_path)
        
        # 也在同级目录查找
        parent = path.parent
        for pattern in patterns:
            test_path = config.WORKSPACE_DIR / parent / pattern
            if test_path.exists() and test_path != path:
                rel_path = str(test_path.relative_to(config.WORKSPACE_DIR))
                if rel_path not in test_files:
                    test_files.append(rel_path)
    
    return sorted(test_files)


def _run_tests(test_files: list[str]) -> str:
    """运行指定的测试文件。"""
    if not test_files:
        return "(无测试可运行)"
    
    # 构建 pytest 命令：必须用当前解释器（项目 venv），
    # 裸 python 可能解析到系统环境（无 pytest，导致误报失败）
    test_paths = " ".join(test_files)
    cmd = f"{sys.executable} -m pytest {test_paths} -v --tb=short"

    # 确保子进程 PATH 能找到同一解释器的可执行文件（venv 未激活场景）
    env = os.environ.copy()
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")

    try:
        result = subprocess.run(
            cmd,
            shell=True, capture_output=True, text=True,
            timeout=60, cwd=str(config.WORKSPACE_DIR), env=env,
        )
        
        output = result.stdout
        if result.returncode == 0:
            return f"✅ 测试通过\n\n{output}"
        else:
            # 测试失败，包含 stderr
            error_output = result.stderr if result.stderr else ""
            return f"❌ 测试失败\n\n{output}\n{error_output}"
    
    except subprocess.TimeoutExpired:
        return "⏱️ 测试运行超时（60秒）"
    except Exception as e:
        return f"❌ 测试运行出错: {e}"
