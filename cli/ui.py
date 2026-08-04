"""CLI 交互界面。"""

import argparse

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

import config
from agent import create_agent
from agent.logger import enable_debug_mode

console = Console()

def _confirm_tool(func_name: str, func_args: dict) -> bool:
    """破坏性操作前询问用户。"""
    console.print(f"\n  ⚠️  [yellow]即将执行: {func_name}({func_args})[/]")
    answer = console.input("  允许？[bold green]y[/]/[bold red]N[/] > ").strip().lower()
    return answer == "y"


def run() -> None:
    """启动交互式 REPL。"""
    parser = argparse.ArgumentParser(description="qcoder-cli AI 编程助手")
    parser.add_argument("--debug", action="store_true", help="启用调试输出模式")
    args = parser.parse_args()

    if args.debug:
        enable_debug_mode()
        console.print("[dim]🔍 调试模式已启用[/]")

    agent = create_agent(confirm_fn=_confirm_tool, debug=args.debug)

    console.print(Panel(
        f"[bold]🤖 qcoder-cli[/bold] — AI 编程助手\n"
        f"模型: [cyan]{config.MODEL_NAME}[/]\n"
        f"工作目录: [cyan]{config.WORKSPACE_DIR}[/]\n"
        f"输入 [cyan]quit[/] 退出",
        title="Welcome",
        border_style="blue",
    ))

    while True:
        try:
            user_input = console.input("\n[bold green]你 >[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            # 保存执行轨迹
            if agent.tracer.event_count > 0:
                trace_path = agent.tracer.save()
                console.print(f"[dim]📝 执行轨迹已保存: {trace_path}[/]")
            # 保存代码记忆
            if agent.memory.file_count > 0:
                mem_path = agent.memory.save()
                console.print(f"[dim]🧠 代码记忆已保存: {mem_path}[/]")
            # 保存任务计划
            if agent.planner.current_plan is not None:
                plan_path = agent.planner.save()
                if plan_path:
                    console.print(f"[dim]📋 任务计划已保存: {plan_path}[/]")
            # 展示并保存 Token 用量
            if agent.usage.session.api_calls > 0:
                console.print(f"\n[dim]{agent.usage.summary(model_name=config.MODEL_NAME)}[/]")
                usage_path = agent.usage.save()
                if usage_path:
                    console.print(f"[dim]💾 用量已保存: {usage_path}[/]")
            console.print("[dim]👋 再见！[/]")
            break

        try:
            reply = agent.chat(user_input)
            console.print()
            console.print(Panel(Markdown(reply), title="🤖 Agent", border_style="cyan"))
        except Exception as e:
            console.print(f"[bold red]错误: {e}[/]")
