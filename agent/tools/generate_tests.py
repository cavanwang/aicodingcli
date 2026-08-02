"""测试自动生成工具：分析变更文件，生成冒烟测试并执行。"""

import ast
import re
import subprocess
from pathlib import Path

import config


def generate_tests() -> str:
    """分析当前变更的 Python 文件，自动生成冒烟测试并执行。

    工作流程：
    1. 检测当前变更的 Python 文件
    2. 用 AST 提取函数/类签名
    3. 生成冒烟测试（导入检查 + 函数签名验证）
    4. 写入测试文件（新建或追加）
    5. 运行测试并返回结果
    """
    changed_files = _get_changed_python_files()
    if not changed_files:
        return "当前无 Python 文件变更，无需生成测试。"

    results = []
    generated_tests = []

    for file_path in changed_files:
        # 提取函数/类签名
        signatures = _extract_signatures(file_path)
        if not signatures:
            results.append(f"  ⏭️ {file_path}: 无可测试的函数/类")
            continue

        # 确定测试文件路径
        test_file = _get_test_file_path(file_path)

        # 生成测试代码
        test_code = _generate_test_code(file_path, signatures, test_file)
        if not test_code:
            results.append(f"  ⏭️ {file_path}: 测试已存在，跳过")
            continue

        # 写入测试文件
        _write_test(test_file, test_code)
        generated_tests.append(test_file)
        results.append(
            f"  ✅ {file_path}: 生成 {len(signatures['functions']) + len(signatures['classes'])} "
            f"个测试 → {test_file}"
        )

    # 运行生成的测试
    if generated_tests:
        test_result = _run_tests(generated_tests)
        output = ["📋 测试生成结果:"]
        output.extend(results)
        output.append("")
        output.append(test_result)
        return "\n".join(output)

    return "📋 测试生成结果:\n" + "\n".join(results)


def _get_changed_python_files() -> list[str]:
    """获取当前变更的 Python 文件（排除测试文件）。"""
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
            status = line[:2]
            if status in ("D ", " D"):
                continue

            file_path = line[2:].strip()
            # 排除测试文件
            if "/tests/" in file_path or file_path.startswith("tests/") or file_path.startswith("test_"):
                continue
            # 只包含 .py 文件
            if file_path.endswith(".py"):
                files.append(file_path)

        return files
    except Exception:
        return []


def _extract_signatures(file_path: str) -> dict | None:
    """用 AST 提取文件中的函数和类签名。"""
    full_path = config.WORKSPACE_DIR / file_path
    if not full_path.exists():
        return None

    try:
        source = full_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return None

    functions = []
    classes = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            # 跳过私有函数（以 _ 开头的）和 __init__
            if node.name.startswith("_"):
                continue
            params = _extract_params(node)
            functions.append({
                "name": node.name,
                "params": params,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            })
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                methods = [
                    n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not n.name.startswith("_")
                ]
                classes.append({
                    "name": node.name,
                    "methods": methods,
                })

    return {"functions": functions, "classes": classes}


def _extract_params(func_node: ast.FunctionDef) -> list[dict]:
    """提取函数参数信息。"""
    params = []
    args = func_node.args

    for arg in args.args:
        name = arg.arg
        if name == "self" or name == "cls":
            continue
        params.append({"name": name, "has_default": False})

    # 标记有默认值的参数
    defaults_count = len(args.defaults)
    if defaults_count > 0:
        for i in range(defaults_count):
            idx = len(params) - defaults_count + i
            if 0 <= idx < len(params):
                params[idx]["has_default"] = True

    return params


def _get_test_file_path(source_file: str) -> str:
    """根据源文件路径确定测试文件路径。"""
    path = Path(source_file)
    module_name = path.stem
    return f"tests/test_{module_name}.py"


def _generate_test_code(
    file_path: str,
    signatures: dict,
    test_file: str,
) -> str | None:
    """生成冒烟测试代码。如果测试已存在则返回 None。"""
    full_test_path = config.WORKSPACE_DIR / test_file
    module_path = file_path.replace("/", ".").replace(".py", "")

    # 检查测试文件是否已存在
    existing_content = ""
    if full_test_path.exists():
        existing_content = full_test_path.read_text(encoding="utf-8")

    test_lines = []

    # 生成函数导入测试
    for func in signatures["functions"]:
        test_name = f"test_auto_{func['name']}"
        if test_name in existing_content:
            continue

        # 构建参数调用
        call_args = _build_call_args(func["params"])
        test_lines.append(
            f"def {test_name}():\n"
            f'    """自动生成的冒烟测试: {func["name"]}"""\n'
            f"    from {module_path} import {func['name']}\n"
            f"    result = {func['name']}({call_args})\n"
            f"    # 冒烟测试：函数能正常执行即可\n"
            f"\n"
        )

    # 生成类实例化测试
    for cls in signatures["classes"]:
        test_name = f"test_auto_{cls['name']}_init"
        if test_name in existing_content:
            continue

        test_lines.append(
            f"def {test_name}():\n"
            f'    """自动生成的冒烟测试: {cls["name"]} 实例化"""\n'
            f"    from {module_path} import {cls['name']}\n"
            f"    obj = {cls['name']}()\n"
            f"    assert obj is not None\n"
            f"\n"
        )

        # 为公开方法生成调用测试
        for method in cls["methods"]:
            method_test = f"test_auto_{cls['name']}_{method}"
            if method_test in existing_content:
                continue
            test_lines.append(
                f"def {method_test}():\n"
                f'    """自动生成的冒烟测试: {cls["name"]}.{method}"""\n'
                f"    from {module_path} import {cls['name']}\n"
                f"    obj = {cls['name']}()\n"
                f"    # 验证方法存在且可调用\n"
                f"    assert callable(getattr(obj, '{method}', None))\n"
                f"\n"
            )

    if not test_lines:
        return None

    # 构建完整测试文件内容
    if existing_content:
        # 追加到已有文件
        return "\n\n# ──── 自动生成的冒烟测试 ────\n\n" + "\n".join(test_lines)
    else:
        # 创建新文件
        header = f'"""自动生成的冒烟测试: {file_path}"""\n\n'
        return header + "\n".join(test_lines)


def _build_call_args(params: list[dict]) -> str:
    """为函数参数生成合理的调用值。"""
    if not params:
        return ""

    args = []
    for p in params:
        if p["has_default"]:
            break  # 有默认值的参数不需要传
        # 根据参数名猜测类型
        name = p["name"].lower()
        if "path" in name or "file" in name or "dir" in name or "name" in name:
            args.append('""')
        elif "count" in name or "num" in name or "size" in name or "index" in name:
            args.append("0")
        elif "flag" in name or "enable" in name or "is_" in name:
            args.append("True")
        elif "items" in name or "list" in name or "data" in name:
            args.append("[]")
        elif "config" in name or "options" in name or "params" in name:
            args.append("{}")
        else:
            args.append("None")

    return ", ".join(args)


def _write_test(test_file: str, test_code: str) -> None:
    """写入测试代码到文件。"""
    full_path = config.WORKSPACE_DIR / test_file
    full_path.parent.mkdir(parents=True, exist_ok=True)

    if full_path.exists():
        # 追加模式
        existing = full_path.read_text(encoding="utf-8")
        full_path.write_text(existing + "\n" + test_code, encoding="utf-8")
    else:
        full_path.write_text(test_code, encoding="utf-8")


def _run_tests(test_files: list[str]) -> str:
    """运行指定的测试文件。"""
    test_paths = " ".join(test_files)
    cmd = f"python -m pytest {test_paths} -v --tb=short"

    try:
        result = subprocess.run(
            cmd,
            shell=True, capture_output=True, text=True,
            timeout=60, cwd=str(config.WORKSPACE_DIR),
        )

        output = result.stdout
        if result.returncode == 0:
            return f"✅ 测试通过\n\n{output}"
        else:
            error_output = result.stderr if result.stderr else ""
            return f"❌ 测试失败\n\n{output}\n{error_output}"

    except subprocess.TimeoutExpired:
        return "⏱️ 测试运行超时（60秒）"
    except Exception as e:
        return f"❌ 测试运行出错: {e}"
