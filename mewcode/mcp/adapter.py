"""MCP adapters — wrap MCP tools/resources/prompts as MewCode BaseTool."""

from typing import Any

from mewcode.mcp.client import MCPClient
from mewcode.tools.base import BaseTool, ToolCategory, ToolParameter, ToolResult


class MCPToolAdapter(BaseTool):
    """Wraps a single MCP tool as a MewCode BaseTool."""

    def __init__(self, client: MCPClient, tool_def: dict) -> None:
        self._client = client
        self._name = tool_def["name"]
        self._description = tool_def.get("description", "")
        self._input_schema = tool_def.get("inputSchema", {})

    @property
    def name(self) -> str:
        return f"{self._client.server_name}/{self._name}"

    @property
    def description(self) -> str:
        return self._description

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.WRITE

    @property
    def parameters(self) -> list[ToolParameter]:
        params: list[ToolParameter] = []
        schema_props = self._input_schema.get("properties", {})
        required = self._input_schema.get("required", [])
        for prop_name, prop_schema in schema_props.items():
            params.append(ToolParameter(
                name=prop_name,
                type=prop_schema.get("type", "string"),
                description=prop_schema.get("description", ""),
                required=prop_name in required,
            ))
        return params

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            text = await self._client.call_tool(self._name, kwargs)
            return ToolResult(success=True, content=text)
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))


# ---------------------------------------------------------------------------
# Lazy adapters — defer list_resources / list_prompts to first execute()
# ---------------------------------------------------------------------------

class MCPResourceAdapter(BaseTool):
    """Lazy: reads a resource by URI. Discovers available URIs on first call."""

    def __init__(self, client: MCPClient) -> None:
        self._client = client
        self._discovered: list[dict] | None = None  # None = not yet loaded

    @property
    def name(self) -> str:
        return f"{self._client.server_name}/mcp_resource"

    @property
    def description(self) -> str:
        if self._discovered is None:
            return f"读取 MCP server '{self._client.server_name}' 上的资源（首次调用时发现可用资源列表）"
        return self._build_description()

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter("uri", "string", "资源 URI，如 file:///path/to/file"),
        ]

    async def execute(self, uri: str) -> ToolResult:
        # Lazy discovery on first call
        if self._discovered is None:
            try:
                self._discovered = await self._client.list_resources()
            except Exception as exc:
                return ToolResult(success=False, content="", error=f"资源发现失败: {exc}")

        try:
            data = await self._client.read_resource(uri)
            return ToolResult(success=True, content=data.get("text", ""))
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))

    def _build_description(self) -> str:
        lines = [f"读取 MCP server '{self._client.server_name}' 上的资源。可用资源:"]
        for r in (self._discovered or [])[:50]:
            lines.append(f"  - {r.get('uri', '?')} ({r.get('name', '?')})")
        return "\n".join(lines)


class MCPPromptAdapter(BaseTool):
    """Lazy: fetches a prompt template. Discovers available prompts on first call."""

    def __init__(self, client: MCPClient) -> None:
        self._client = client
        self._discovered: list[dict] | None = None  # None = not yet loaded

    @property
    def name(self) -> str:
        return f"{self._client.server_name}/mcp_prompt"

    @property
    def description(self) -> str:
        if self._discovered is None:
            return f"获取 MCP server '{self._client.server_name}' 上的提示词模板（首次调用时发现可用模板列表）"
        return self._build_description()

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter("name", "string", "提示词模板名称"),
            ToolParameter("arguments", "string", "模板参数，JSON 格式", required=False),
        ]

    async def execute(self, name: str, arguments: str = "{}") -> ToolResult:
        import json

        # Lazy discovery on first call
        if self._discovered is None:
            try:
                self._discovered = await self._client.list_prompts()
            except Exception as exc:
                return ToolResult(success=False, content="", error=f"提示词发现失败: {exc}")

        try:
            args_dict = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return ToolResult(success=False, content="", error=f"无效的 JSON 参数: {arguments}")

        try:
            result = await self._client.get_prompt(name, args_dict)
            messages = result.get("messages", [])
            parts: list[str] = []
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if isinstance(content, dict):
                    content = content.get("text", "")
                parts.append(f"[{role}]: {content}")
            return ToolResult(success=True, content="\n".join(parts))
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))

    def _build_description(self) -> str:
        lines = [f"获取 MCP server '{self._client.server_name}' 上的提示词模板。可用模板:"]
        for p in (self._discovered or [])[:50]:
            lines.append(f"  - {p.get('name', '?')}: {p.get('description', '?')}")
        return "\n".join(lines)
