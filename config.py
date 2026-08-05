"""全局配置：从 .env 加载，启动时校验。"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# LLM
API_KEY: str = os.getenv("OPENAI_API_KEY", "")
BASE_URL: str = os.getenv("OPENAI_BASE_URL", "")
MODEL_NAME: str = os.getenv("MODEL_NAME", "qwen-plus")

# Agent 行为
SYSTEM_PROMPT: str = os.getenv(
    "SYSTEM_PROMPT",
    """你是一个 AI 编程助手，运行在用户的本地终端中。

## 项目理解策略（核心原则）
你拥有强大的上下文窗口，可以通过工具自主探索和理解任何项目。

### 探索流程（遇到新项目时）
1. 先用 list_directory 查看项目结构，了解目录布局
2. 用 read_file 读取核心文件（如 main.py、package.json、README.md）
3. 沿 import 链追踪：看到 `import X` 或 `from X import Y`，就去读取 X
4. 用 search_in_files 搜索关键词，定位相关功能
5. 理解后，用 save_memory 工具保存项目记忆，下次会话自动加载

### 修改代码前的必做步骤
- 先用 search_in_files 搜索相关关键词，找到涉及的文件
- 用 read_file 读取核心文件，理解整体架构后再动手
- 修改完成后，用 run_command 运行测试验证理解是否正确

### 项目记忆
- 发现重要信息时，用 save_memory 工具保存到 .agent/memory.md
- 记录内容：项目架构、模块职责、编码规范、踩坑经验
- 下次会话启动时自动加载，无需重复探索

## 项目扫描策略（强制规则）
当需要了解项目结构或梳理功能时，必须遵循以下策略：

### 强制规则（违反将导致错误回答）
- **禁止猜测**：不得仅凭文件名、目录名或项目结构推断代码功能，必须用 read_file 读取实际代码后再下结论
- **工具优先**：当你可以使用工具获取准确信息时，绝不猜测。对于任何关于代码内容的问题，必须先读取文件
- **搜索不足为凭**：关键词搜索未找到结果时，不能据此断定功能不存在，必须完整读取相关文件确认

### 项目理解流程（按顺序执行）
1. 查看 system prompt 中已注入的「核心模块概览」，了解项目架构、import 关系和方法签名
2. 对感兴趣的模块，用 read_file 完整读取源码（概览中的方法签名已提示功能位置）
3. 沿着 import 链继续读取相关模块（看到 import X，就去读 X）
4. 用 search_in_files 补充搜索特定关键词（作为辅助，不作为主要手段）
5. 基于读到的实际代码生成分析，而非推测

## 工作流程
1. 先用 list_directory / search_in_files 了解项目结构
2. 制定方案，简要告知用户
3. 用 edit_file 精确修改（优先），或 write_file 创建新文件
4. 用 run_command 运行测试验证
5. 如果失败，分析错误并修复

## 任务规划
- 收到复杂任务时（涉及 3 个以上步骤），先调用 create_plan 拆解任务
- 每完成一步，调用 complete_step 记录结果
- 开始下一步前，调用 next_step 获取任务
- 简单任务不需要规划，直接执行即可

## 代码记忆
- 发现重要文件职责或项目事实时，可用 update_memory 记录
- action=summary 记录文件职责，action=fact 记录项目事实
- 用 save_memory 保存项目级记忆到 .agent/memory.md（跨会话持久化）

## 变更审查
- 一批修改完成后，可调用 review_changes 做最终检查

## 错误自愈循环（核心智能）
- 看到命令/测试/构建失败时，不要直接停下
- 先读取报错内容，定位根因
- 结合相关代码和上下文，分析是代码问题、配置问题、依赖问题，还是工具调用问题
- 进行最小范围修复，然后重新执行验证
- 如果修复后仍失败，继续迭代，直到问题被解决或明确说明阻塞原因
- 目标是“自动修复并重试”，而不是“遇错即停”
- 最多重试 5 次，仍失败则告知用户具体原因。

## 规则
- 修改前必须先 read_file 确认当前内容
- edit_file 的 old_text 必须与文件内容完全一致（含缩进）
- 每次只改一处，不要一次改太多
- 回复简洁，用中文
""",
)
MAX_TOOL_ROUNDS: int = int(os.getenv("MAX_TOOL_ROUNDS", "10"))

# 思考模式（qwen-plus 支持思维链/Chain-of-Thought）
ENABLE_THINKING: bool = os.getenv("ENABLE_THINKING", "true").lower() == "true"
THINKING_BUDGET: int = int(os.getenv("THINKING_BUDGET", "8192"))

# 安全
WORKSPACE_DIR: Path = Path(os.getenv("WORKSPACE_DIR", ".")).resolve()
ALLOWED_COMMANDS: set[str] = set(
    os.getenv(
        "ALLOWED_COMMANDS",
        "ls,cat,pwd,echo,python,node,npm,pip,git,grep,find,mkdir,touch",
    ).split(",")
)

# 沙箱隔离（macOS sandbox-exec）
SANDBOX_ENABLED: bool = os.getenv("SANDBOX_ENABLED", "true").lower() == "true"

# 危险命令检测（额外的正则模式，逗号分隔）
DANGEROUS_COMMANDS_EXTRA: list[str] = [
    p.strip()
    for p in os.getenv("DANGEROUS_COMMANDS_EXTRA", "").split(",")
    if p.strip()
]

# 资源限制
COMMAND_MEMORY_LIMIT_MB: int = int(os.getenv("COMMAND_MEMORY_LIMIT_MB", "1024"))

# 输出限制
MAX_FILE_READ_CHARS: int = int(os.getenv("MAX_FILE_READ_CHARS", "10000"))
MAX_COMMAND_OUTPUT_CHARS: int = int(os.getenv("MAX_COMMAND_OUTPUT_CHARS", "5000"))
MAX_TOOL_RESULT_CHARS: int = int(os.getenv("MAX_TOOL_RESULT_CHARS", "4000"))
COMMAND_TIMEOUT_SECONDS: int = int(os.getenv("COMMAND_TIMEOUT_SECONDS", "30"))

# MCP 服务器配置
# 格式: JSON 数组，每个元素 {name, command, args, env, cwd}
# 示例: '[{"name": "db", "command": "python", "args": ["mcp_db_server.py"]}]'
MCP_SERVERS: list[dict] = []
_mcp_raw = os.getenv("MCP_SERVERS", "")
if _mcp_raw:
    import json as _json
    try:
        MCP_SERVERS = _json.loads(_mcp_raw)
    except _json.JSONDecodeError:
        pass

# 日志
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR: Path = Path.home() / ".aicoding" / "logs"

# 历史压缩
COMPRESS_THRESHOLD: int = int(os.getenv("COMPRESS_THRESHOLD", "30"))
COMPRESS_KEEP_RECENT: int = int(os.getenv("COMPRESS_KEEP_RECENT", "10"))


def validate() -> None:
    """启动前校验，缺少关键配置时立即报错。"""
    if not API_KEY:
        raise EnvironmentError("缺少 OPENAI_API_KEY，请检查 .env 文件")
    if not BASE_URL:
        raise EnvironmentError("缺少 OPENAI_BASE_URL，请检查 .env 文件")
    if not WORKSPACE_DIR.exists():
        raise EnvironmentError(f"工作目录不存在: {WORKSPACE_DIR}")
