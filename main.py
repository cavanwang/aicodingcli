"""qcoder-cli 入口：支持子命令。"""

import argparse
import subprocess
import sys

from cli import run as run_repl


def cmd_usage(args) -> None:
    """查看历史 Token 用量。"""
    from agent.usage import UsageTracker

    history = UsageTracker.load_history(days=args.days)
    print(UsageTracker.format_history(history))


def cmd_rollback(args) -> None:
    """回滚到上一个 checkpoint。"""
    import config

    workspace = str(config.WORKSPACE_DIR)

    # 列出最近 checkpoint
    result = subprocess.run(
        'git log --grep="checkpoint" --oneline -5',
        shell=True, capture_output=True, text=True, cwd=workspace,
    )
    checkpoints = result.stdout.strip()

    if not checkpoints:
        print("❌ 未找到 checkpoint 提交")
        sys.exit(1)

    print("📝 最近 checkpoint:")
    for line in checkpoints.split("\n"):
        print(f"  {line}")
    print()

    if not args.yes:
        answer = input("确认回滚到上一个 checkpoint？[y/N] > ").strip().lower()
        if answer != "y":
            print("已取消")
            return

    # 执行回滚
    rollback_result = subprocess.run(
        "git reset --hard HEAD~1",
        shell=True, capture_output=True, text=True, cwd=workspace,
    )

    if rollback_result.returncode == 0:
        print("✅ 已回滚到上一个 checkpoint")
    else:
        print(f"❌ 回滚失败: {rollback_result.stderr}")
        sys.exit(1)


def main() -> None:
    """主入口：解析子命令并分发。"""
    parser = argparse.ArgumentParser(
        prog="qcoder-cli",
        description="qcoder-cli AI 编程助手",
    )
    subparsers = parser.add_subparsers(dest="command")

    # usage 子命令
    usage_parser = subparsers.add_parser("usage", help="查看历史 Token 用量")
    usage_parser.add_argument(
        "--days", type=int, default=7,
        help="查看最近 N 天的用量（默认 7）",
    )

    # rollback 子命令
    rollback_parser = subparsers.add_parser("rollback", help="回滚到上一个 checkpoint")
    rollback_parser.add_argument(
        "--yes", "-y", action="store_true",
        help="跳过确认提示",
    )

    args = parser.parse_args()

    if args.command == "usage":
        cmd_usage(args)
    elif args.command == "rollback":
        cmd_rollback(args)
    else:
        # 无子命令时启动 REPL
        run_repl()


if __name__ == "__main__":
    main()
