"""qcoder-cli 入口：支持子命令。"""

import argparse
import sys

from cli import run as run_repl


def cmd_usage(args) -> None:
    """查看历史 Token 用量。"""
    from agent.usage import UsageTracker

    history = UsageTracker.load_history(days=args.days)
    print(UsageTracker.format_history(history))


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

    args = parser.parse_args()

    if args.command == "usage":
        cmd_usage(args)
    else:
        # 无子命令时启动 REPL
        run_repl()


if __name__ == "__main__":
    main()
