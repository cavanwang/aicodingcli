"""符号导航工具：定义查找、引用查找、import 链追踪。

基于 AST 的轻量实现，能力边界与 ast_analyzer.py 一致：
不处理嵌套作用域、闭包、动态属性访问（如 getattr(x, y)）。
"""

import ast
from pathlib import Path

import config
from agent.memory import _is_ignored_dir, _is_ignored_file

_MAX_RESULTS = 50


def _iter_py_files():
    """遍历 workspace 内未被忽略的 .py 文件，产出 (绝对路径, 相对路径字符串)。

    忽略规则检查相对路径上的所有层级（避免扫入 .venv/node_modules 等深层目录）。
    """
    root = config.WORKSPACE_DIR
    for py_file in root.rglob("*.py"):
        if not py_file.is_file():
            continue
        if _is_ignored_file(py_file.name):
            continue
        rel = py_file.relative_to(root)
        if any(_is_ignored_dir(part) for part in rel.parts[:-1]):
            continue
        yield py_file, str(rel)


def find_definition(symbol: str, file_path: str = "") -> str:
    """按符号名查找定义位置（函数/类/模块级变量）。

    Args:
        symbol: 符号名，如 "compress_history"、"Agent"
        file_path: 可选，限定在单个文件内查找（相对 workspace），默认全 workspace
    """
    if not symbol or not symbol.strip():
        return "错误: symbol 不能为空"

    candidates: list[tuple[Path, str]] = []
    if file_path:
        full = (config.WORKSPACE_DIR / file_path).resolve()
        if not str(full).startswith(str(config.WORKSPACE_DIR.resolve())):
            return f"错误: 路径越界: {file_path}"
        if not full.exists():
            return f"文件不存在: {file_path}"
        candidates.append((full, file_path))
    else:
        candidates = list(_iter_py_files())

    results: list[str] = []
    for path, rel in candidates:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == symbol:
                    results.append(f"{rel}:{node.lineno}  def {symbol} (函数)")
            elif isinstance(node, ast.ClassDef):
                if node.name == symbol:
                    results.append(f"{rel}:{node.lineno}  class {symbol}")
            elif isinstance(node, ast.Assign):
                # 仅模块级赋值（顶层常量/变量）
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == symbol:
                        results.append(f"{rel}:{node.lineno}  {symbol} = ... (赋值)")
        if len(results) >= _MAX_RESULTS:
            break

    if not results:
        scope = f"（范围: {file_path}）" if file_path else "（全 workspace）"
        return f"未找到符号 '{symbol}' 的定义{scope}"
    return "\n".join(results[:_MAX_RESULTS])


def find_references(symbol: str) -> str:
    """查找符号在 workspace 所有 Python 文件中的引用位置。

    同时匹配标识符引用（ast.Name）、属性引用（ast.Attribute，
    如 self.compress_history()）和 import 别名，覆盖方法调用与模块导入场景。

    Args:
        symbol: 标识符，如 "compress_history"、"Agent"
    """
    if not symbol or not symbol.strip():
        return "错误: symbol 不能为空"

    refs: list[str] = []
    for py_file, rel in _iter_py_files():
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id == symbol:
                    refs.append(f"{rel}:{node.lineno}")
            elif isinstance(node, ast.Attribute):
                if node.attr == symbol:
                    refs.append(f"{rel}:{node.lineno}")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if any(a.name == symbol for a in node.names):
                    refs.append(f"{rel}:{node.lineno}")

    if not refs:
        return f"未找到符号 '{symbol}' 的引用（仅扫描 Python 文件）"

    out = "\n".join(refs[:_MAX_RESULTS])
    if len(refs) > _MAX_RESULTS:
        out += f"\n... 共 {len(refs)} 处，仅显示前 {_MAX_RESULTS} 处"
    return out


def _module_names_for(rel_path: str) -> list[str]:
    """把相对文件路径转成可能的模块名。

    例: "agent/core.py" → ["agent.core", "core"]
        "agent/__init__.py" → ["agent"]
    """
    p = Path(rel_path)
    parts = list(p.parts)
    if parts and parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = p.stem
    if not parts:
        return []
    full = ".".join(parts)
    names = [full]
    if len(parts) > 1:
        names.append(parts[-1])  # 顶层模块名（sys.path 指向子目录时可能直接 import）
    return names


def get_import_tree(file_path: str) -> str:
    """查看一个 Python 文件的 import 关系：它导入谁（正链）+ 谁导入它（反链）。

    Args:
        file_path: 相对 workspace 的 Python 文件路径，如 "agent/core.py"
    """
    if not file_path or not file_path.strip():
        return "错误: file_path 不能为空"

    full = (config.WORKSPACE_DIR / file_path).resolve()
    if not str(full).startswith(str(config.WORKSPACE_DIR.resolve())):
        return f"错误: 路径越界: {file_path}"
    if not full.exists():
        return f"文件不存在: {file_path}"
    if full.suffix != ".py":
        return "仅支持 Python 文件"

    try:
        tree = ast.parse(full.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError) as e:
        return f"语法解析失败: {e}"

    # 正链：该文件的 import 语句
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            names = ", ".join(a.name for a in node.names)
            imports.append(f"from {node.module} import {names}")

    # 反链：哪些文件导入该文件的模块名
    target_names = set(_module_names_for(file_path))
    importers: list[str] = []
    for py_file, rel in _iter_py_files():
        if rel == file_path:
            continue
        try:
            other = ast.parse(py_file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(other):
            matched = False
            if isinstance(node, ast.Import):
                matched = any(a.name in target_names for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                matched = node.module in target_names
            if matched:
                importers.append(f"{rel}:{node.lineno}")
                break
        if len(importers) >= _MAX_RESULTS:
            break

    sections = [f"== {file_path} 的 import 关系 =="]
    sections.append(f"导入 {len(imports)} 个模块（正链）:")
    sections.extend(f"  {i}" for i in imports[:_MAX_RESULTS])
    if not imports:
        sections.append("  （无）")
    sections.append(f"被 {len(importers)} 个文件导入（反链）:")
    sections.extend(f"  {i}" for i in importers)
    if not importers:
        sections.append("  （无）")
    return "\n".join(sections)
