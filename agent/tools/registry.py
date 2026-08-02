"""
工具注册表：
- TOOL_FUNCTIONS:  name → callable（供 agent loop 调用）
- TOOLS_SCHEMA:    OpenAI function calling 的 JSON schema（传给 API）
- CONFIRM_TOOLS:   需要用户确认的工具名集合（从注册表自动生成）

新增工具时，只需：
1. 在对应模块写函数
2. 在下方 _REGISTRY 中注册（加 "requires_confirm": True 如需确认）
"""

from agent.tools.file_ops import read_file, write_file, list_directory
from agent.tools.edit_file import edit_file
from agent.tools.batch_edit import batch_edit
from agent.tools.shell import run_command
from agent.tools.search import search_in_files
from agent.tools.find_files import find_files
from agent.tools.verify import verify_changes
from agent.tools.generate_tests import generate_tests
from agent.tools.git_ops import (
    git_checkpoint,
    git_diff,
    git_log,
    git_rollback,
    git_status,
    analyze_changes,
    get_related_files,
)

# ============================================================
# 注册表（唯一需要维护的地方）
# ============================================================
_REGISTRY: list[dict] = [
    # ──────────────────────────────────────────────
    # 文件操作
    # ──────────────────────────────────────────────
    {
        "function": read_file,
        "requires_confirm": False,
        "schema": {
            "name": "read_file",
            "description": "读取指定文件的内容（带行号）。可通过 start_line/end_line 指定范围。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "相对于工作目录的文件路径，如 'src/main.py'",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "起始行号（从 1 开始），默认 1",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "结束行号，0 表示读到末尾，默认 0",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "function": write_file,
        "requires_confirm": True,
        "schema": {
            "name": "write_file",
            "description": "创建新文件或覆盖已有文件的全部内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "相对于工作目录的文件路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的完整文件内容",
                    },
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "function": edit_file,
        "requires_confirm": True,
        "schema": {
            "name": "edit_file",
            "description": (
                "精确修改文件：在文件中搜索 old_text 并替换为 new_text。"
                "old_text 必须与文件中的内容完全一致（含缩进和换行）。"
                "优先使用此工具而非 write_file。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "相对于工作目录的文件路径",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "要被替换的原始文本（必须与文件内容完全匹配）",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "替换后的新文本",
                    },
                },
                "required": ["file_path", "old_text", "new_text"],
            },
        },
    },
    {
        "function": batch_edit,
        "requires_confirm": True,
        "schema": {
            "name": "batch_edit",
            "description": (
                "批量编辑多个文件：一次提交多个文件的修改操作。"
                "自动创建 checkpoint，逐个执行编辑，汇总结果。"
                "适用于跨文件重构、关联修改等场景。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "edits": {
                        "type": "string",
                        "description": (
                            "JSON 数组字符串，每个元素包含 file_path, old_text, new_text。"
                            '示例: \'[{"file_path": "a.py", "old_text": "x", "new_text": "y"}, ...]\''
                        ),
                    }
                },
                "required": ["edits"],
            },
        },
    },
    {
        "function": list_directory,
        "requires_confirm": False,
        "schema": {
            "name": "list_directory",
            "description": "列出指定目录下的文件和子目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_path": {
                        "type": "string",
                        "description": "相对于工作目录的目录路径，默认 '.'",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "function": find_files,
        "requires_confirm": False,
        "schema": {
            "name": "find_files",
            "description": "按 glob 模式查找文件，如 '*.py'、'*test*'、'config*'",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "glob 匹配模式，如 '*.py'、'*test*'",
                    },
                    "dir_path": {
                        "type": "string",
                        "description": "搜索的起始目录，默认 '.'",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    # ──────────────────────────────────────────────
    # 搜索
    # ──────────────────────────────────────────────
    {
        "function": search_in_files,
        "requires_confirm": False,
        "schema": {
            "name": "search_in_files",
            "description": "在工作目录的文件中搜索关键词（类似 grep -rn）",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "要搜索的关键词或正则表达式",
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "文件名匹配模式，如 '*.py'，默认 '*'",
                    },
                },
                "required": ["keyword"],
            },
        },
    },
    # ──────────────────────────────────────────────
    # Shell
    # ──────────────────────────────────────────────
    {
        "function": run_command,
        "requires_confirm": True,
        "schema": {
            "name": "run_command",
            "description": "在工作目录中执行一条 shell 命令（如运行测试、启动服务）",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的命令，如 'python main.py'、'npm test'",
                    }
                },
                "required": ["command"],
            },
        },
    },
    # ──────────────────────────────────────────────
    # Git
    # ──────────────────────────────────────────────
    {
        "function": git_diff,
        "requires_confirm": False,
        "schema": {
            "name": "git_diff",
            "description": "查看当前工作区未提交的改动（git diff）。可按文件过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "可选，指定文件路径查看该文件的 diff",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "function": git_status,
        "requires_confirm": False,
        "schema": {
            "name": "git_status",
            "description": "查看工作区状态（哪些文件被修改/新增/删除）",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "function": git_log,
        "requires_confirm": False,
        "schema": {
            "name": "git_log",
            "description": "查看最近的提交记录",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "显示最近几条提交，默认 10",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "function": git_checkpoint,
        "requires_confirm": False,
        "schema": {
            "name": "git_checkpoint",
            "description": "为当前工作区创建一个 checkpoint 提交，便于后续回滚",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "checkpoint 的说明信息，默认 'auto-checkpoint'",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "function": git_rollback,
        "requires_confirm": True,
        "schema": {
            "name": "git_rollback",
            "description": "回滚到上一个 checkpoint，丢弃当前未提交改动",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "function": analyze_changes,
        "requires_confirm": False,
        "schema": {
            "name": "analyze_changes",
            "description": "分析当前未提交变更的影响范围：变更文件列表、变更类型、行数统计",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "function": get_related_files,
        "requires_confirm": False,
        "schema": {
            "name": "get_related_files",
            "description": "查找引用了指定文件的其他文件，用于评估修改影响范围",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "要分析的文件路径（含扩展名），如 'agent/core.py'",
                    }
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "function": verify_changes,
        "requires_confirm": False,
        "schema": {
            "name": "verify_changes",
            "description": "自动发现变更文件并运行相关测试，验证修改的正确性",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "function": generate_tests,
        "requires_confirm": True,
        "schema": {
            "name": "generate_tests",
            "description": (
                "分析当前变更的 Python 文件，自动生成冒烟测试并执行。"
                "通过 AST 提取函数/类签名，生成导入检查和调用测试。"
                "适用于修改代码后快速生成验证测试。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

# ============================================================
# 对外暴露
# ============================================================
TOOL_FUNCTIONS: dict[str, callable] = {
    item["schema"]["name"]: item["function"] for item in _REGISTRY
}

TOOLS_SCHEMA: list[dict] = [
    {"type": "function", "function": item["schema"]} for item in _REGISTRY
]

# 需要用户确认的工具名集合（自动从注册表生成，无需手动维护）
CONFIRM_TOOLS: set[str] = {
    item["schema"]["name"] for item in _REGISTRY if item.get("requires_confirm", False)
}
