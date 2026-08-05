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
from agent.tools.symbol_nav import find_definition, find_references, get_import_tree
from agent.tools.semantic_tools import semantic_search
from agent.tools.verify import verify_changes
from agent.tools.generate_tests import generate_tests
from agent.tools.task_tools import create_plan, next_step, complete_step, plan_status
from agent.tools.memory_tools import update_memory, review_changes, save_memory
from agent.tools.todo_tools import add_todo, update_todo, list_todos, complete_todo
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
            "description": "读取指定文件的内容（带行号）。可通过 start_line/end_line 指定范围。用于精读 find_files/search_in_files 定位到的文件；大文件先读关键范围再扩展",
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
            "description": "列出指定目录下的文件和子目录。了解目录布局的第一步，配合 read_file/find_files 逐层深入探索",
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
            "description": "按 glob 模式查找文件，如 '*.py'、'*test*'、'config*'。不知道文件在哪时的第一步；找到候选后用 read_file 精读",
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
            "description": "在工作目录的文件中搜索关键词（类似 grep -rn）。已知关键词/符号名时用于定位具体位置，配合 file_pattern 缩小范围；无结果时换同义词或符号变体再试",
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
    # 符号导航
    # ──────────────────────────────────────────────
    {
        "function": find_definition,
        "requires_confirm": False,
        "schema": {
            "name": "find_definition",
            "description": "按符号名查找定义位置（函数/类/模块级变量），基于 AST 精确匹配。需要修改某符号前先用它定位定义处；轻量实现，不处理动态属性访问",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "符号名，如 'compress_history'、'Agent'",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "可选，限定在单个文件内查找（相对路径），默认全项目",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "function": find_references,
        "requires_confirm": False,
        "schema": {
            "name": "find_references",
            "description": "查找符号在所有 Python 文件中的引用位置。修改函数/类前先用它评估影响面（有哪些调用方）；轻量实现，仅匹配标识符引用",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "标识符，如 'compress_history'、'Agent'",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "function": get_import_tree,
        "requires_confirm": False,
        "schema": {
            "name": "get_import_tree",
            "description": "查看一个 Python 文件的 import 关系：它导入哪些模块（正链）+ 哪些文件导入它（反链）。理解模块边界和影响面时使用",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "相对路径的 Python 文件，如 'agent/core.py'",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "function": semantic_search,
        "requires_confirm": False,
        "schema": {
            "name": "semantic_search",
            "description": "用自然语言语义检索代码（如'分页处理逻辑'），基于函数/类级向量索引，支持中英跨模态。大仓库中关键词搜索不理想时的补充手段；首次调用自动建索引，API 不可用时自动提示降级到关键词搜索",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "自然语言查询，如'用户登录失败处理'、'分页处理逻辑'",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量上限，默认 5，最大 20",
                    },
                },
                "required": ["query"],
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
            "description": "查找与指定文件相关的其他文件：引用关系 + git 共现历史（经常一起提交的文件），用于评估修改影响范围和发现隐含耦合",
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
    # ──────────────────────────────────────────────
    # 任务规划
    # ──────────────────────────────────────────────
    {
        "function": create_plan,
        "requires_confirm": False,
        "schema": {
            "name": "create_plan",
            "description": (
                "创建任务执行计划：将复杂任务拆解为有序子任务。"
                "适用于涉及 3 个以上步骤的复杂任务。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "任务目标描述",
                    },
                    "subtasks": {
                        "type": "string",
                        "description": (
                            "子任务列表，JSON 数组格式。"
                            '示例: \'["分析需求", "修改代码", "运行测试"]\''
                        ),
                    },
                },
                "required": ["goal", "subtasks"],
            },
        },
    },
    {
        "function": next_step,
        "requires_confirm": False,
        "schema": {
            "name": "next_step",
            "description": "获取下一个待执行子任务，并标记为进行中",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "function": complete_step,
        "requires_confirm": False,
        "schema": {
            "name": "complete_step",
            "description": "标记指定子任务为完成状态",
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {
                        "type": "integer",
                        "description": "子任务序号（从 1 开始）",
                    },
                    "result": {
                        "type": "string",
                        "description": "执行结果摘要，默认空",
                    },
                },
                "required": ["step_id"],
            },
        },
    },
    {
        "function": plan_status,
        "requires_confirm": False,
        "schema": {
            "name": "plan_status",
            "description": "查看当前任务计划的进度详情",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    # ──────────────────────────────────────────────
    # 记忆与审查
    # ──────────────────────────────────────────────
    {
        "function": update_memory,
        "requires_confirm": False,
        "schema": {
            "name": "update_memory",
            "description": (
                "更新代码库记忆：记录文件职责、关键接口或项目事实。"
                "用于跨会话保持对代码库的理解。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "操作类型: summary | interfaces | fact | remove",
                    },
                    "key": {
                        "type": "string",
                        "description": "文件路径（用于 summary/interfaces 操作）",
                    },
                    "value": {
                        "type": "string",
                        "description": "摘要内容（用于 summary 操作）",
                    },
                    "interfaces": {
                        "type": "string",
                        "description": "接口列表，逗号分隔（用于 interfaces 操作）",
                    },
                    "fact": {
                        "type": "string",
                        "description": "项目事实（用于 fact 操作）",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "function": review_changes,
        "requires_confirm": False,
        "schema": {
            "name": "review_changes",
            "description": (
                "审查当前变更质量：分析变更范围、运行相关测试、评估风险等级。"
                "适用于一批修改完成后做最终检查。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "description": "输出格式：'text'（默认，可读报告）或 'json'（结构化数据）",
                        "enum": ["text", "json"],
                    },
                },
                "required": [],
            },
        },
    },
    {
        "function": save_memory,
        "requires_confirm": False,
        "schema": {
            "name": "save_memory",
            "description": (
                "保存项目记忆到 .agent/memory.md 文件（跨会话持久化）。"
                "用于记录项目架构、模块职责、编码规范、踩坑经验等。"
                "下次会话启动时自动加载到 system prompt。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "操作类型: save（覆盖保存）或 append（追加/更新章节）",
                    },
                    "content": {
                        "type": "string",
                        "description": "记忆内容（Markdown 格式）",
                    },
                    "section": {
                        "type": "string",
                        "description": "章节标题（仅 append 模式使用），如 '## 模块职责'",
                    },
                    "source": {
                        "type": "string",
                        "description": (
                            "记忆来源。'chat'=从用户聊天中识别的约束/偏好（将触发用户确认），"
                            "'explicit'=用户明确要求保存（直接执行）。默认 'chat'"
                        ),
                        "enum": ["chat", "explicit"],
                    },
                },
                "required": ["action"],
            },
        },
    },
    # ──────────────────────────────────────────────
    # Todo 待办管理
    # ──────────────────────────────────────────────
    {
        "function": add_todo,
        "requires_confirm": False,
        "schema": {
            "name": "add_todo",
            "description": (
                "添加一个待办事项到 Todo 列表。"
                "用于追踪复杂任务中的细粒度步骤。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "待办事项的描述内容",
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "function": update_todo,
        "requires_confirm": False,
        "schema": {
            "name": "update_todo",
            "description": (
                "更新指定待办事项的内容或状态。"
                "状态可选: pending | in_progress | complete"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "integer",
                        "description": "待办事项 ID",
                    },
                    "content": {
                        "type": "string",
                        "description": "新的描述内容（可选）",
                    },
                    "status": {
                        "type": "string",
                        "description": "新状态: pending | in_progress | complete（可选）",
                    },
                },
                "required": ["todo_id"],
            },
        },
    },
    {
        "function": list_todos,
        "requires_confirm": False,
        "schema": {
            "name": "list_todos",
            "description": "列出所有待办事项及当前进度",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "function": complete_todo,
        "requires_confirm": False,
        "schema": {
            "name": "complete_todo",
            "description": "标记指定待办事项为完成",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "integer",
                        "description": "待办事项 ID",
                    },
                    "result": {
                        "type": "string",
                        "description": "完成结果摘要（可选）",
                    },
                },
                "required": ["todo_id"],
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
