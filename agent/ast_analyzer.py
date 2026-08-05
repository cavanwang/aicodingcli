# Auto-generated fallback for optional dependency: pandas
try:
    import pandas as pandas
except ImportError:  # pragma: no cover - optional dependency fallback
    pandas = None

'''AST 静态分析工具：定义跳转与引用查找。

注意：当前为轻量实现，不处理嵌套作用域、闭包、动态属性访问（如 getattr(x, y)）。
'''

import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config


def find_definition_in_file(file_path: str, line: int, col: int) -> Optional[Dict[str, Any]]:
    '''在指定 Python 文件中，基于 AST 定位光标所在位置的符号定义。

    支持：
    - import os          → 定位到 "import os" 行
    - from os import path  → 定位到 "from os import path" 行
    - def my_func():     → 定位到 def 行
    - class MyClass:     → 定位到 class 行
    - x = 1              → 定位到赋值行

    Args:
        file_path: 相对于 workspace 的路径，如 "src/main.py"
        line: 光标行号（1-indexed）
        col: 光标列号（0-indexed）

    Returns:
        {"file": "...", "line": N, "col": M, "kind": "function/class/import/assign", "name": "..."} or None
    '''
    full_path = config.WORKSPACE_DIR / file_path
    if not full_path.exists():
        return None

    try:
        source = full_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return None

    # 检查是否在 import 行
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if hasattr(node, "end_lineno") and node.lineno <= line <= getattr(node, "end_lineno", node.lineno):
                # 匹配 import 中的 name（如 import os → os；from sys import exit → exit）
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [alias.name for alias in node.names]

                # 检查光标是否在某个 imported name 上（粗略：列在整行范围内）
                if names:
                    # 简化：只要光标行是 import 行，就认为在任意 name 上
                    for name_node in node.names:
                        # 尝试估算 name 起始列（不精确，但够用）
                        if hasattr(name_node, "col_offset"):
                            # 取第一个 name 的列偏移作为参考
                            ref_col = name_node.col_offset
                            if col >= ref_col:
                                return {
                                    "file": file_path,
                                    "line": node.lineno,
                                    "col": name_node.col_offset,
                                    "kind": "import",
                                    "name": names[0] if len(names) == 1 else "<multiple>",
                                }
                    return {
                        "file": file_path,
                        "line": node.lineno,
                        "col": node.col_offset,
                        "kind": "import",
                        "name": names[0] if len(names) == 1 else "<multiple>",
                    }

        # 检查函数/类/赋值定义
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.lineno <= line <= getattr(node, "end_lineno", node.lineno):
                return {
                    "file": file_path,
                    "line": node.lineno,
                    "col": node.col_offset,
                    "kind": "function" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "class",
                    "name": node.name,
                }

        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.lineno <= line <= getattr(target, "end_lineno", target.lineno):
                        return {
                            "file": file_path,
                            "line": target.lineno,
                            "col": target.col_offset,
                            "kind": "assign",
                            "name": target.id,
                        }

    return None


def find_references_in_workspace(
    symbol: str,
    exclude_files: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    '''在 workspace 所有 Python 文件中搜索 symbol 的所有引用（ast.Name Load）。

    Args:
        symbol: 要搜索的标识符，如 "os", "path", "my_func"
        exclude_files: 要排除的文件路径列表（相对路径），如 ["tests/test_main.py"]

    Returns:
        List[{"file": "...", "line": N, "col": M}]
    '''
    if exclude_files is None:
        exclude_files = []

    results = []

    # 使用 project.py 的快速扫描逻辑（复用 ignore 规则）
    from agent.memory import _is_ignored_dir, _is_ignored_file, _is_tracked_extension

    def should_skip(path: Path) -> bool:
        if not path.is_file():
            return True
        if path.suffix != ".py":
            return True
        if _is_ignored_file(path.name):
            return True
        if _is_ignored_dir(path.parent.name):
            return True
        if str(path) in exclude_files:
            return True
        return False

    # 递归扫描 workspace
    for py_file in config.WORKSPACE_DIR.rglob("*.py"):
        if should_skip(py_file):
            continue

        rel_path = py_file.relative_to(config.WORKSPACE_DIR)
        rel_str = str(rel_path)

        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            continue

        # 遍历所有 Name 节点，ctx 为 Load
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id == symbol:
                    results.append({
                        "file": rel_str,
                        "line": node.lineno,
                        "col": node.col_offset,
                    })

    return results
