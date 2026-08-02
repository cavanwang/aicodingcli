"""统一日志模块：输出到文件 + 可选控制台。

使用方式：
    from agent.logger import get_logger
    logger = get_logger(__name__)
    logger.info("...")
    logger.debug("...")
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import config

_initialized = False
_debug_console_added = False


def enable_debug_mode() -> None:
    """运行时切换到 DEBUG 级别，并启用控制台日志输出。"""
    global _debug_console_added
    root_logger = logging.getLogger("agent")
    root_logger.setLevel(logging.DEBUG)

    if not _debug_console_added:
        _debug_console_added = True
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(
            logging.Formatter("[%(levelname)-7s] %(name)s: %(message)s")
        )
        root_logger.addHandler(console_handler)


def _setup_logging() -> None:
    """初始化日志系统（仅执行一次）。"""
    global _initialized
    if _initialized:
        return
    _initialized = True

    # 确保日志目录存在
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)

    # 根 logger 配置
    root_logger = logging.getLogger("agent")
    root_logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))

    # 文件 handler：详细格式，追加模式
    log_file = config.LOG_DIR / "agent.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root_logger.addHandler(file_handler)

    # 控制台 handler：仅在 DEBUG 模式下启用，简洁格式
    if config.LOG_LEVEL == "DEBUG":
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(
            logging.Formatter("[%(levelname)-7s] %(name)s: %(message)s")
        )
        root_logger.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """获取一个已配置的 logger 实例。"""
    _setup_logging()
    # 确保子 logger 名称统一在 agent 命名空间下
    if not name.startswith("agent"):
        name = f"agent.{name}"
    return logging.getLogger(name)
