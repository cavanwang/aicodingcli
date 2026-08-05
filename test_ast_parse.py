import ast
import sys
from pathlib import Path

def _extract_module_summary(file_path):
    try:
        source = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    summary = []

    if file_path.suffix == ".py":
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            summary.append(f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else ""))
                    else:
                        names = ", ".join([
                            alias.name + (f" as {alias.asname}" if alias.asname else "")
                            for alias in node.names
                        ])
                        summary.append(f"from {node.module} import {names}")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig = f"{'async ' if isinstance(node, ast.AsyncFunctionDef) else ''}def {node.name}"
                    params = []
                    for arg in node.args.args:
                        param = arg.arg
                        if arg.annotation:
                            ann_str = ast.unparse(arg.annotation) if hasattr(ast, 'unparse') else "Any"
                            param += f": {ann_str}"
                        params.append(param)
                    if node.args.vararg:
                        params.append(f"*{node.args.vararg.arg}")
                    if node.args.kwarg:
                        params.append(f"**{node.args.kwarg.arg}")
                    if node.returns:
                        ret_ann = ast.unparse(node.returns) if hasattr(ast, 'unparse') else "Any"
                        sig += f"({', '.join(params)}) -> {ret_ann}"
                    else:
                        sig += f"({', '.join(params)})"
                    summary.append(sig)
                    if ast.get_docstring(node):
                        doc = ast.get_docstring(node).strip().split("\n")[0]
                        if len(doc) > 60:
                            doc = doc[:57] + "..."
                        summary.append(f"    # {doc}")
                elif isinstance(node, ast.ClassDef):
                    bases = []
                    for base in node.bases:
                        bases.append(ast.unparse(base) if hasattr(ast, 'unparse') else str(base))
                    sig = f"class {node.name}" + (f"({', '.join(bases)})" if bases else "")
                    summary.append(sig)
                    if ast.get_docstring(node):
                        doc = ast.get_docstring(node).strip().split("\n")[0]
                        if len(doc) > 60:
                            doc = doc[:57] + "..."
                        summary.append(f"    # {doc}")
                if len(summary) >= 20:
                    summary.append("... (更多省略)")
                    break
            if summary:
                return summary
        except Exception as e:
            print(f"AST parse failed: {e}")
            pass

    # fallback
    lines = source.splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("import ") or stripped.startswith("from "):
            summary.append(stripped)
        elif stripped.startswith("def ") or stripped.startswith("class "):
            summary.append(stripped)
        if len(summary) >= 20:
            summary.append("... (更多省略)")
            break
    return summary

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python test_ast_parse.py <file_path>")
        sys.exit(1)
    result = _extract_module_summary(Path(sys.argv[1]))
    print("\n".join(result))
