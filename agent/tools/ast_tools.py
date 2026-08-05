'''AST 分析工具：注册为可调用 tool。
'''

import ast
from typing import Any, Dict, List, Optional

from agent.ast_analyzer import find_definition_in_file, find_references_in_workspace
from agent.tools.registry import TOOL_FUNCTIONS, TOOLS_SCHEMA


def find_definition(
    file_path: str,
    line: int,
    col: int,
) -> Dict[str, Any]:
    '''在指定 Python 文件中定位光标位置的符号定义（函数、类、import、变量赋值）。

    Args:
        file_path: 相对于 workspace 的 Python 文件路径，如 "src/main.py"
        line: 光标所在行号（1-indexed）
        col: 光标所在列号（0-indexed）
    '''
    result = find_definition_in_file(file_path, line, col)
    if result is None:
        return {"error": f"未在 {file_path}:{line}:{col} 找到定义"}
    return result


def find_references(
    symbol: str,
    exclude_files: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    '''在 workspace 所有 Python 文件中搜索 symbol 的所有引用位置。

    Args:
        symbol: 要搜索的标识符名称，如 "os", "my_func", "User"
        exclude_files: 可选，要排除的文件路径列表（相对路径），如 ["tests/"]
    '''
    if exclude_files is None:
        exclude_files = []
    return find_references_in_workspace(symbol, exclude_files)


# —————— Tool Registration ——————

TOOL_FUNCTIONS["find_definition"] = find_definition
TOOL_FUNCTIONS["find_references"] = find_references

TOOLS_SCHEMA.append({
    "type": "function",
    "function": {
        "name": "find_definition",
        "description": "在指定 Python 文件中定位光标位置的符号定义（函数、类、import、变量赋值）",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "相对于 workspace 的 Python 文件路径，如 \"src/main.py\""
                },
                "line": {
                    "type": "integer",
                    "description": "光标所在行号（1-indexed）"
                },
                "col": {
                    "type": "integer",
                    "description": "光标所在列号（0-indexed）"
                }
            },
            "required": ["file_path", "line", "col"]
        }
    }
})

TOOLS_SCHEMA.append({
    "type": "function",
    "function": {
        "name": "find_references",
        "description": "在 workspace 所有 Python 文件中搜索 symbol 的所有引用位置",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "要搜索的标识符名称，如 \"os\", \"my_func\", \"User\""
                },
                "exclude_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选，要排除的文件路径列表（相对路径），如 [\"tests/\"]"
                }
            },
            "required": ["symbol"]
        }
    }
})
