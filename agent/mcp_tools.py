"""MCP 工具转换层：将 MCP 动态工具转为本地 TOOL_FUNCTIONS / TOOLS_SCHEMA 格式。

职责：
1. 从 MCPManager 获取已发现的工具列表
2. 为每个 MCP 工具生成一个同步 callable（闭包捕获 manager + tool_name）
3. 将 MCP input_schema 转为 OpenAI function calling schema 格式
4. 注册到全局 TOOL_FUNCTIONS / TOOLS_SCHEMA
"""

from agent.logger import get_logger

logger = get_logger(__name__)


def register_mcp_tools(mcp_manager) -> int:
    """将 MCPManager 中发现的工具注册到全局工具注册表。

    返回注册的工具数量。
    """
    from agent.tools.registry import TOOL_FUNCTIONS, TOOLS_SCHEMA, CONFIRM_TOOLS

    tools = mcp_manager.list_tools()
    count = 0

    for tool_info in tools:
        # 跳过与本地工具同名的 MCP 工具（避免覆盖）
        if tool_info.name in TOOL_FUNCTIONS:
            logger.warning(
                "MCP 工具 [%s] 与本地工具同名，已跳过", tool_info.name
            )
            continue

        # 1. 创建闭包 callable
        def make_fn(name=tool_info.name, server=tool_info.server_name):
            def mcp_tool_fn(**kwargs):
                return mcp_manager.call_tool(name, kwargs)
            mcp_tool_fn.__name__ = name
            mcp_tool_fn.__doc__ = tool_info.description
            return mcp_tool_fn

        fn = make_fn()

        # 2. 构建 OpenAI function calling schema
        schema = {
            "name": tool_info.name,
            "description": tool_info.description,
            "parameters": _convert_schema(tool_info.input_schema),
        }

        # 3. 注册到全局表
        TOOL_FUNCTIONS[tool_info.name] = fn
        TOOLS_SCHEMA.append({"type": "function", "function": schema})

        count += 1
        logger.info(
            "MCP 工具已注册: %s (来自服务器 %s)",
            tool_info.name, tool_info.server_name,
        )

    return count


def _convert_schema(mcp_schema: dict) -> dict:
    """将 MCP input_schema 转为 OpenAI function calling 参数格式。

    MCP schema 已经是 JSON Schema 格式，基本兼容。
    主要确保 type/properties/required 结构正确。
    """
    result = {
        "type": mcp_schema.get("type", "object"),
        "properties": {},
    }

    properties = mcp_schema.get("properties", {})
    for prop_name, prop_def in properties.items():
        # 保留基本类型信息
        clean_prop = {}
        for key in ("type", "description", "enum", "items", "default"):
            if key in prop_def:
                clean_prop[key] = prop_def[key]
        # 处理 title（MCP 自动生成时可能带 title，去掉以避免干扰）
        result["properties"][prop_name] = clean_prop

    # 保留 required 列表
    if "required" in mcp_schema:
        result["required"] = mcp_schema["required"]

    return result
