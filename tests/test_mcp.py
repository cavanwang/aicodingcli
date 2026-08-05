"""MCP 集成测试：验证 MCPManager 同步桥接 + 工具注册。"""

import asyncio
import json
import os
import sys
import tempfile
import textwrap
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from agent.mcp_manager import MCPManager, MCPServerConfig, MCPToolInfo
from agent.mcp_tools import register_mcp_tools, _convert_schema


# ──────────────────────────────────────────────
# 辅助：创建一个临时 MCP 服务器脚本
# ──────────────────────────────────────────────

def _make_server_script() -> str:
    """创建一个临时 MCP 测试服务器脚本，返回文件路径。"""
    script = textwrap.dedent('''\
        import asyncio
        from mcp.server import MCPServer

        mcp = MCPServer("test_server")

        @mcp.tool()
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        @mcp.tool()
        def greet(name: str) -> str:
            """Greet someone."""
            return f"Hello, {name}!"

        async def main():
            await mcp.run_stdio_async()

        if __name__ == "__main__":
            asyncio.run(main())
    ''')
    fd, path = tempfile.mkstemp(suffix=".py", dir=".")
    with os.fdopen(fd, "w") as f:
        f.write(script)
    return path


# ──────────────────────────────────────────────
# MCPManager 单元测试
# ──────────────────────────────────────────────

class TestMCPServerConfig:
    """MCPServerConfig 数据类测试。"""

    def test_basic_config(self):
        cfg = MCPServerConfig(name="test", command="python")
        assert cfg.name == "test"
        assert cfg.command == "python"
        assert cfg.args == []
        assert cfg.env is None

    def test_full_config(self):
        cfg = MCPServerConfig(
            name="db",
            command="node",
            args=["server.js", "--port", "3000"],
            env={"DB_URL": "sqlite:///test.db"},
            cwd="/tmp",
        )
        assert cfg.args == ["server.js", "--port", "3000"]
        assert cfg.env["DB_URL"] == "sqlite:///test.db"
        assert cfg.cwd == "/tmp"


class TestMCPToolInfo:
    """MCPToolInfo 数据类测试。"""

    def test_tool_info(self):
        info = MCPToolInfo(
            name="query_db",
            description="Run a SQL query",
            input_schema={"type": "object", "properties": {"sql": {"type": "string"}}},
            server_name="db_server",
        )
        assert info.name == "query_db"
        assert info.server_name == "db_server"
        assert "sql" in info.input_schema["properties"]


class TestMCPManagerUnit:
    """MCPManager 单元测试（不连接真实服务器）。"""

    def test_init_state(self):
        mgr = MCPManager()
        assert mgr.server_names == []
        assert not mgr.is_connected
        assert mgr.list_tools() == []

    def test_add_server(self):
        mgr = MCPManager()
        cfg = MCPServerConfig(name="test", command="python")
        mgr.add_server(cfg)
        assert mgr.server_names == ["test"]

    def test_add_multiple_servers(self):
        mgr = MCPManager()
        mgr.add_server(MCPServerConfig(name="a", command="python"))
        mgr.add_server(MCPServerConfig(name="b", command="node"))
        assert sorted(mgr.server_names) == ["a", "b"]

    def test_has_tool_empty(self):
        mgr = MCPManager()
        assert not mgr.has_tool("anything")

    def test_call_tool_not_connected(self):
        mgr = MCPManager()
        result = mgr.call_tool("test", {})
        assert "未连接" in result

    def test_connect_all_no_servers(self):
        mgr = MCPManager()
        tools = mgr.connect_all()
        assert tools == []

    def test_disconnect_when_not_connected(self):
        mgr = MCPManager()
        mgr.disconnect_all()  # 不应报错
        assert not mgr.is_connected


# ──────────────────────────────────────────────
# MCPManager 集成测试（连接真实 MCP 服务器）
# ──────────────────────────────────────────────

class TestMCPManagerIntegration:
    """使用真实 MCP 服务器进程的集成测试。"""

    @pytest.fixture
    def server_script(self):
        path = _make_server_script()
        yield path
        if os.path.exists(path):
            os.unlink(path)

    @pytest.fixture
    def manager_with_server(self, server_script):
        mgr = MCPManager()
        # 必须用当前解释器（含 mcp 依赖）；裸 python 可能解析到
        # 未安装 mcp 的系统环境，导致服务器启动失败
        mgr.add_server(MCPServerConfig(
            name="test",
            command=sys.executable,
            args=[server_script],
        ))
        yield mgr
        mgr.disconnect_all()

    def test_connect_and_discover(self, manager_with_server):
        mgr = manager_with_server
        tool_names = mgr.connect_all()
        assert mgr.is_connected
        assert "add" in tool_names
        assert "greet" in tool_names

    def test_list_tools(self, manager_with_server):
        mgr = manager_with_server
        mgr.connect_all()
        tools = mgr.list_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert "add" in names
        assert "greet" in names
        # 验证 server_name 正确
        for t in tools:
            assert t.server_name == "test"

    def test_call_tool_add(self, manager_with_server):
        mgr = manager_with_server
        mgr.connect_all()
        result = mgr.call_tool("add", {"a": 3, "b": 4})
        assert result.strip() == "7"

    def test_call_tool_greet(self, manager_with_server):
        mgr = manager_with_server
        mgr.connect_all()
        result = mgr.call_tool("greet", {"name": "World"})
        assert "Hello" in result
        assert "World" in result

    def test_has_tool(self, manager_with_server):
        mgr = manager_with_server
        mgr.connect_all()
        assert mgr.has_tool("add")
        assert mgr.has_tool("greet")
        assert not mgr.has_tool("nonexistent")

    def test_call_unknown_tool(self, manager_with_server):
        mgr = manager_with_server
        mgr.connect_all()
        result = mgr.call_tool("nonexistent", {})
        assert "未知" in result or "不存在" in result

    def test_disconnect(self, manager_with_server):
        mgr = manager_with_server
        mgr.connect_all()
        assert mgr.is_connected
        mgr.disconnect_all()
        assert not mgr.is_connected
        assert mgr.list_tools() == []

    def test_connect_bad_server(self):
        """连接一个不存在的命令，应优雅地失败。"""
        mgr = MCPManager()
        mgr.add_server(MCPServerConfig(
            name="bad",
            command="nonexistent_command_xyz",
        ))
        tool_names = mgr.connect_all()
        assert tool_names == []  # 连接失败，没有工具
        mgr.disconnect_all()


# ──────────────────────────────────────────────
# 工具转换层测试
# ──────────────────────────────────────────────

class TestConvertSchema:
    """_convert_schema 单元测试。"""

    def test_basic_schema(self):
        mcp_schema = {
            "type": "object",
            "properties": {
                "a": {"type": "integer", "description": "First number"},
                "b": {"type": "integer", "description": "Second number"},
            },
            "required": ["a", "b"],
        }
        result = _convert_schema(mcp_schema)
        assert result["type"] == "object"
        assert "a" in result["properties"]
        assert result["properties"]["a"]["type"] == "integer"
        assert result["required"] == ["a", "b"]

    def test_strip_title(self):
        """MCP 自动生成的 schema 可能带 title，应被去掉。"""
        mcp_schema = {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "title": "XValue", "description": "X"},
            },
            "required": ["x"],
        }
        result = _convert_schema(mcp_schema)
        assert "title" not in result["properties"]["x"]
        assert result["properties"]["x"]["description"] == "X"

    def test_empty_schema(self):
        result = _convert_schema({})
        assert result["type"] == "object"
        assert result["properties"] == {}

    def test_enum_preserved(self):
        mcp_schema = {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["text", "json"],
                    "description": "Output format",
                },
            },
        }
        result = _convert_schema(mcp_schema)
        assert result["properties"]["format"]["enum"] == ["text", "json"]


class TestRegisterMCPTools:
    """register_mcp_tools 测试。"""

    def test_register_tools(self):
        """模拟 MCPManager，验证工具注册到全局表。"""
        mgr = MagicMock()
        mgr.list_tools.return_value = [
            MCPToolInfo(
                name="mcp_test_add",
                description="Add numbers",
                input_schema={
                    "type": "object",
                    "properties": {
                        "a": {"type": "integer"},
                        "b": {"type": "integer"},
                    },
                    "required": ["a", "b"],
                },
                server_name="test",
            ),
        ]
        mgr.call_tool.return_value = "42"

        # 导入全局注册表
        from agent.tools.registry import TOOL_FUNCTIONS, TOOLS_SCHEMA

        original_count = len(TOOLS_SCHEMA)
        original_funcs = set(TOOL_FUNCTIONS.keys())

        try:
            count = register_mcp_tools(mgr)
            assert count == 1
            assert "mcp_test_add" in TOOL_FUNCTIONS
            assert len(TOOLS_SCHEMA) == original_count + 1

            # 验证 callable 能正确调用
            fn = TOOL_FUNCTIONS["mcp_test_add"]
            result = fn(a=20, b=22)
            assert result == "42"
            mgr.call_tool.assert_called_once_with("mcp_test_add", {"a": 20, "b": 22})
        finally:
            # 清理：恢复全局注册表
            for key in list(TOOL_FUNCTIONS.keys()):
                if key not in original_funcs:
                    del TOOL_FUNCTIONS[key]
            while len(TOOLS_SCHEMA) > original_count:
                TOOLS_SCHEMA.pop()

    def test_skip_duplicate_tool(self):
        """与本地工具同名的 MCP 工具应被跳过。"""
        mgr = MagicMock()
        mgr.list_tools.return_value = [
            MCPToolInfo(
                name="read_file",  # 与本地工具同名
                description="MCP version",
                input_schema={"type": "object", "properties": {}},
                server_name="test",
            ),
        ]

        from agent.tools.registry import TOOL_FUNCTIONS, TOOLS_SCHEMA

        original_count = len(TOOLS_SCHEMA)
        original_read_file = TOOL_FUNCTIONS.get("read_file")

        try:
            count = register_mcp_tools(mgr)
            assert count == 0  # 被跳过
            assert len(TOOLS_SCHEMA) == original_count
            # 本地 read_file 不应被覆盖
            assert TOOL_FUNCTIONS.get("read_file") is original_read_file
        finally:
            pass


# ──────────────────────────────────────────────
# Config 加载测试
# ──────────────────────────────────────────────

class TestInitMCPPythonMapping:
    """init_mcp 裸 python 命令映射测试（防环境坑）。"""

    def _agent_with_mock_mcp(self):
        from agent.core import Agent
        agent = Agent.__new__(Agent)
        agent._mcp = MagicMock()
        agent._mcp.connect_all.return_value = []
        return agent

    def test_bare_python_mapped_to_executable(self):
        agent = self._agent_with_mock_mcp()
        agent.init_mcp([{"name": "s1", "command": "python", "args": ["srv.py"]},
                        {"name": "s2", "command": "python3"},
                        {"name": "s3", "command": "python3.12"}])
        from agent.mcp_manager import MCPServerConfig
        configs = [c.args[0] for c in agent._mcp.add_server.call_args_list]
        for cfg in configs:
            assert isinstance(cfg, MCPServerConfig)
            assert cfg.command == sys.executable

    def test_other_commands_untouched(self):
        agent = self._agent_with_mock_mcp()
        agent.init_mcp([{"name": "n", "command": "node", "args": ["srv.js"]},
                        {"name": "p", "command": "/usr/local/bin/custom-py"}])
        commands = [c.args[0].command for c in agent._mcp.add_server.call_args_list]
        assert commands == ["node", "/usr/local/bin/custom-py"]


# ──────────────────────────────────────────────
# Config 加载测试（原有）
# ──────────────────────────────────────────────

class TestMCPConfig:
    """MCP 配置加载测试。"""

    def test_default_empty(self):
        """默认 MCP_SERVERS 应为空列表。"""
        import config
        # 如果没有设置环境变量，应该为空
        # 注意：这里不直接修改全局 config，只验证类型
        assert isinstance(config.MCP_SERVERS, list)

    def test_parse_json_config(self):
        """验证 JSON 配置解析逻辑。"""
        raw = '[{"name": "test", "command": "python", "args": ["server.py"]}]'
        result = json.loads(raw)
        assert len(result) == 1
        assert result[0]["name"] == "test"
        assert result[0]["command"] == "python"
