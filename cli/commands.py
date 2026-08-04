"""Slash 命令注册与分发。

12 个内置命令，用户输入 / 开头触发，不经过 LLM。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import config
from agent.logger import get_logger

logger = get_logger(__name__)

# 命令类型：接收 agent，返回 bool（True=继续循环，False=退出）
CommandHandler = Callable  # (agent) -> bool


# ──────────────────────────────────────────────
# 命令实现
# ──────────────────────────────────────────────

def cmd_help(agent) -> bool:
    """/help — 显示所有可用命令。"""
    from rich.console import Console
    console = Console()

    lines = ["[bold]可用命令：[/]"]
    for name, (_, desc) in sorted(COMMANDS.items()):
        lines.append(f"  [cyan]{name}[/] — {desc}")
    lines.append("\n[dim]命令不经过 LLM，直接执行[/]")

    console.print("\n".join(lines))
    return True


def cmd_compact(agent) -> bool:
    """/compact — 手动压缩对话历史。"""
    from rich.console import Console
    console = Console()

    ok = agent.compress_history()
    if ok:
        console.print(f"📦 历史已压缩，当前消息数: {len(agent.messages)}")
    else:
        console.print("📦 无需压缩（消息数未达阈值或无旧消息）")
    return True


def cmd_cost(agent) -> bool:
    """/cost — 显示本次会话 Token 用量和费用。"""
    from rich.console import Console
    console = Console()

    summary = agent.usage.summary(model_name=config.MODEL_NAME)
    console.print(summary)
    return True


def cmd_clear(agent) -> bool:
    """/clear — 清空对话历史。"""
    from rich.console import Console
    console = Console()

    agent.reset()
    console.print("🗑️ 对话历史已清空")
    return True


def cmd_status(agent) -> bool:
    """/status — 显示当前状态。"""
    from rich.console import Console
    console = Console()

    lines = ["[bold]📊 当前状态[/]"]
    lines.append(f"  模型: [cyan]{config.MODEL_NAME}[/]")
    lines.append(f"  工作目录: [cyan]{config.WORKSPACE_DIR}[/]")
    lines.append(f"  消息数: {len(agent.messages)}")

    # Token 用量
    session = agent.usage.session
    if session.api_calls > 0:
        lines.append(
            f"  Token: {session.total_tokens:,} "
            f"(输入 {session.prompt_tokens:,} + 输出 {session.completion_tokens:,})"
        )
        cost = session.estimated_cost(config.MODEL_NAME)
        if cost > 0:
            lines.append(f"  💰 费用: ${cost:.4f}")
    else:
        lines.append("  Token: 无 API 调用")

    # 计划进度
    if agent.planner.current_plan is not None:
        plan = agent.planner.current_plan
        if plan.status not in ("completed", "failed"):
            total = len(plan.subtasks)
            done = sum(1 for s in plan.subtasks if s.status == "done")
            lines.append(f"  📋 计划: {done}/{total} 完成")

    # Todo 进度
    todo_line = agent.todo.progress_line()
    if todo_line:
        lines.append(f"  {todo_line}")

    console.print("\n".join(lines))
    return True


def cmd_review(agent) -> bool:
    """/review — 手动触发变更审查。"""
    from rich.console import Console
    from rich.markdown import Markdown
    console = Console()

    from agent.review import ChangeReviewer
    reviewer = ChangeReviewer()
    result = reviewer.review()
    report = reviewer.format_report(result)

    console.print()
    console.print(Markdown(report))
    return True


def cmd_doctor(agent) -> bool:
    """/doctor — 诊断环境健康状态。"""
    from rich.console import Console
    console = Console()

    checks = []

    # 1. API 连通性
    try:
        from openai import OpenAI
        client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)
        client.models.list()
        checks.append("✅ API 连通性: 正常")
    except Exception as e:
        checks.append(f"❌ API 连通性: {e}")

    # 2. API Key
    if config.API_KEY and len(config.API_KEY) > 8:
        masked = config.API_KEY[:4] + "****" + config.API_KEY[-4:]
        checks.append(f"✅ API Key: {masked}")
    elif config.API_KEY:
        checks.append("⚠️ API Key: 过短，可能无效")
    else:
        checks.append("❌ API Key: 未配置")

    # 3. 模型
    checks.append(f"ℹ️ 模型: {config.MODEL_NAME}")

    # 4. 沙箱
    import sys
    if sys.platform == "darwin":
        checks.append("✅ 沙箱: sandbox-exec (macOS)")
    elif sys.platform == "linux":
        checks.append("ℹ️ 沙箱: 无 (Linux)")
    elif sys.platform == "win32":
        checks.append("ℹ️ 沙箱: 无 (Windows)")
    else:
        checks.append(f"ℹ️ 沙箱: 未知平台 ({sys.platform})")

    # 5. 工作目录
    workspace = Path(config.WORKSPACE_DIR)
    if workspace.exists():
        checks.append(f"✅ 工作目录: {workspace}")
    else:
        checks.append(f"❌ 工作目录不存在: {workspace}")

    # 6. .env
    env_path = Path(config.WORKSPACE_DIR) / ".env"
    if env_path.exists():
        checks.append("✅ .env 文件: 存在")
    else:
        checks.append("⚠️ .env 文件: 不存在")

    console.print("\n[bold]🩺 环境诊断[/]")
    for check in checks:
        console.print(f"  {check}")

    return True


def cmd_usage(agent) -> bool:
    """/usage — 显示历史用量。"""
    from rich.console import Console
    console = Console()

    from agent.usage import UsageTracker
    history = UsageTracker.load_history(days=7)
    console.print(UsageTracker.format_history(history))
    return True


def cmd_todo(agent) -> bool:
    """/todo — 显示当前 Todo 列表。"""
    from rich.console import Console
    console = Console()

    console.print(agent.todo.summary())
    return True


def cmd_plan(agent) -> bool:
    """/plan — 显示当前任务计划。"""
    from rich.console import Console
    console = Console()

    console.print(agent.planner.progress_summary())
    return True


def cmd_memory(agent) -> bool:
    """/memory — 显示代码记忆摘要。"""
    from rich.console import Console
    console = Console()

    mem = agent.memory
    lines = ["[bold]🧠 代码记忆[/]"]
    lines.append(f"  已追踪文件: {mem.tracked_file_count}")
    lines.append(f"  已记忆文件: {mem.file_count}")

    if mem.file_summaries:
        lines.append("\n  [dim]记忆详情：[/]")
        for path, summary in list(mem.file_summaries.items())[:10]:
            short = summary[:60] + "..." if len(summary) > 60 else summary
            lines.append(f"    📄 {path}: {short}")
        if len(mem.file_summaries) > 10:
            lines.append(f"    ... 还有 {len(mem.file_summaries) - 10} 个文件")
    else:
        lines.append("  [dim]暂无记忆[/]")

    console.print("\n".join(lines))
    return True


def cmd_init(agent) -> bool:
    """/init — 在当前目录生成 .agent.md 模板。"""
    from rich.console import Console
    console = Console()

    template = """\
# 项目配置

## 项目简介
<!-- 简要描述项目的功能和目标 -->

## 技术栈
<!-- 列出项目使用的语言、框架、工具 -->

## 编码规范
<!-- 描述项目的编码风格和约定 -->
- 使用 4 空格缩进
- 函数和类需要 docstring
- 变量使用 snake_case 命名

## 常用命令
<!-- 列出开发中常用的命令 -->
- 运行测试: `pytest`
- 启动服务: `python main.py`

## 禁止事项
<!-- 列出不允许 Agent 执行的操作 -->
- 不要修改 .env 文件
- 不要删除测试文件
"""

    target = Path(config.WORKSPACE_DIR) / ".agent.md"
    if target.exists():
        console.print(f"⚠️ .agent.md 已存在: {target}")
        return True

    target.write_text(template, encoding="utf-8")
    console.print(f"✅ 已生成 .agent.md 模板: {target}")
    return True


# ──────────────────────────────────────────────
# 命令注册表
# ──────────────────────────────────────────────

COMMANDS: dict[str, tuple[CommandHandler, str]] = {
    "/help":    (cmd_help,    "显示所有可用命令"),
    "/compact": (cmd_compact, "手动压缩对话历史"),
    "/cost":    (cmd_cost,    "显示本次会话 Token 用量和费用"),
    "/clear":   (cmd_clear,   "清空对话历史"),
    "/status":  (cmd_status,  "显示当前状态（模型、目录、Token、计划等）"),
    "/review":  (cmd_review,  "手动触发代码变更审查"),
    "/doctor":  (cmd_doctor,  "诊断环境健康状态"),
    "/usage":   (cmd_usage,   "显示历史用量（最近 7 天）"),
    "/todo":    (cmd_todo,    "显示当前 Todo 列表"),
    "/plan":    (cmd_plan,    "显示当前任务计划"),
    "/memory":  (cmd_memory,  "显示代码记忆摘要"),
    "/init":    (cmd_init,    "在当前目录生成 .agent.md 模板"),
}


def dispatch_command(user_input: str, agent) -> bool:
    """解析并执行 Slash 命令。

    Args:
        user_input: 用户输入（以 / 开头）
        agent: Agent 实例

    Returns:
        True=继续循环，False=退出
    """
    parts = user_input.strip().split(maxsplit=1)
    cmd = parts[0].lower()

    entry = COMMANDS.get(cmd)
    if entry is None:
        from rich.console import Console
        console = Console()
        console.print(
            f"[red]未知命令: {cmd}[/]\n"
            f"[dim]输入 /help 查看可用命令[/]"
        )
        return True

    handler, _ = entry
    logger.info("Slash 命令: %s", cmd)
    try:
        return handler(agent)
    except Exception as e:
        from rich.console import Console
        console = Console()
        console.print(f"[red]命令执行出错: {e}[/]")
        logger.error("命令 %s 执行异常: %s", cmd, e, exc_info=True)
        return True
