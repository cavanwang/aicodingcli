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

## 工作流程
1. 先用 list_directory / read_file / search_in_files 了解项目
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
