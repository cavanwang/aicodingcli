"""MCP 客户端管理器：同步桥接层，让同步 Agent 能调用异步 MCP 工具。

核心设计：
- 后台线程运行 asyncio event loop
- 通过 threading.Event + Future 实现 sync ↔ async 桥接
- 每个 MCP Server 对应一个子进程（stdio 传输）
"""

import asyncio
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from agent.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MCPServerConfig:
    """单个 MCP 服务器的配置。"""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None


@dataclass
class MCPToolInfo:
    """从 MCP 服务器发现的工具信息。"""
    name: str
    description: str
    input_schema: dict
    server_name: str  # 来自哪个服务器


class MCPManager:
    """MCP 客户端管理器（同步接口）。

    用法：
        manager = MCPManager()
        manager.add_server(MCPServerConfig(name="db", command="python", args=["db_server.py"]))
        manager.connect_all()
        tools = manager.list_tools()
        result = manager.call_tool("db_query", {"sql": "SELECT 1"})
        manager.disconnect_all()
    """

    def __init__(self):
        self._servers: dict[str, MCPServerConfig] = {}
        self._clients: dict[str, Any] = {}  # server_name → MCP Client
        self._tools: dict[str, MCPToolInfo] = {}  # tool_name → MCPToolInfo
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._connected = False

    # ──────────────────────────────────────────────
    # 服务器配置
    # ──────────────────────────────────────────────

    def add_server(self, config: MCPServerConfig) -> None:
        """注册一个 MCP 服务器配置。"""
        self._servers[config.name] = config
        logger.info("MCP 服务器已注册: %s (%s)", config.name, config.command)

    @property
    def server_names(self) -> list[str]:
        return list(self._servers.keys())

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ──────────────────────────────────────────────
    # 连接管理
    # ──────────────────────────────────────────────

    def connect_all(self) -> list[str]:
        """连接所有已注册的 MCP 服务器，返回发现的工具名列表。

        在后台线程中启动 event loop，逐个连接服务器。
        """
        if not self._servers:
            logger.info("没有 MCP 服务器需要连接")
            return []

        # 启动后台 event loop 线程
        self._start_loop()

        # 在 loop 中执行连接
        future = asyncio.run_coroutine_threadsafe(self._connect_all_async(), self._loop)
        tool_names = future.result(timeout=30)
        self._connected = True
        return tool_names

    def disconnect_all(self) -> None:
        """断开所有连接，停止后台线程。"""
        if not self._connected:
            return

        future = asyncio.run_coroutine_threadsafe(self._disconnect_all_async(), self._loop)
        try:
            future.result(timeout=10)
        except Exception as e:
            logger.warning("MCP 断开连接异常: %s", e)

        self._stop_loop()
        self._clients.clear()
        self._tools.clear()
        self._connected = False
        logger.info("MCP 所有连接已断开")

    # ──────────────────────────────────────────────
    # 工具操作
    # ──────────────────────────────────────────────

    def list_tools(self) -> list[MCPToolInfo]:
        """返回所有已连接服务器上的工具列表。"""
        return list(self._tools.values())

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """同步调用一个 MCP 工具，返回文本结果。"""
        if not self._connected:
            return "MCP 未连接"

        tool_info = self._tools.get(tool_name)
        if tool_info is None:
            return f"未知 MCP 工具: {tool_name}"

        future = asyncio.run_coroutine_threadsafe(
            self._call_tool_async(tool_info.server_name, tool_name, arguments),
            self._loop,
        )
        return future.result(timeout=60)

    def has_tool(self, tool_name: str) -> bool:
        """检查某个工具是否存在。"""
        return tool_name in self._tools

    # ──────────────────────────────────────────────
    # 内部：async 实现
    # ──────────────────────────────────────────────

    async def _connect_all_async(self) -> list[str]:
        """异步连接所有服务器，发现并注册工具。"""
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters, stdio_client

        all_tool_names: list[str] = []

        for name, cfg in self._servers.items():
            try:
                params = StdioServerParameters(
                    command=cfg.command,
                    args=cfg.args,
                    env=cfg.env,
                    cwd=cfg.cwd,
                )
                # 创建 Client 并连接
                client = Client(stdio_client(params))
                await client.__aenter__()

                self._clients[name] = client

                # 发现工具
                tools_result = await client.list_tools()
                for tool in tools_result.tools:
                    mcp_tool = MCPToolInfo(
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=tool.input_schema,
                        server_name=name,
                    )
                    self._tools[tool.name] = mcp_tool
                    all_tool_names.append(tool.name)

                logger.info(
                    "MCP 服务器 [%s] 已连接，发现 %d 个工具",
                    name, len(tools_result.tools),
                )
            except Exception as e:
                logger.error("MCP 服务器 [%s] 连接失败: %s", name, e)

        return all_tool_names

    async def _disconnect_all_async(self) -> None:
        """异步断开所有连接。"""
        for name, client in self._clients.items():
            try:
                await client.__aexit__(None, None, None)
                logger.debug("MCP 服务器 [%s] 已断开", name)
            except Exception as e:
                logger.warning("MCP 服务器 [%s] 断开异常: %s", name, e)

    async def _call_tool_async(
        self, server_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> str:
        """异步调用 MCP 工具。"""
        client = self._clients.get(server_name)
        if client is None:
            return f"MCP 服务器 [{server_name}] 未连接"

        try:
            result = await client.call_tool(tool_name, arguments)
            # 提取文本内容
            texts = []
            for content in result.content:
                if hasattr(content, "text"):
                    texts.append(content.text)
            return "\n".join(texts) if texts else str(result.content)
        except Exception as e:
            logger.error("MCP 工具调用失败 [%s]: %s", tool_name, e)
            return f"MCP 工具调用失败: {e}"

    # ──────────────────────────────────────────────
    # 内部：后台 event loop 管理
    # ──────────────────────────────────────────────

    def _start_loop(self) -> None:
        """在后台线程中启动 asyncio event loop。"""
        if self._loop is not None:
            return

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.debug("MCP 后台 event loop 已启动")

    def _run_loop(self) -> None:
        """后台线程入口：运行 event loop 直到被关闭。"""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _stop_loop(self) -> None:
        """停止后台 event loop 和线程。"""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=5)
            self._loop = None
            self._thread = None
            logger.debug("MCP 后台 event loop 已停止")
