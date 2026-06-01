"""MCP client — handshake, discovery, tool/resource/prompt calls."""

import asyncio
from typing import Any

from mewcode.mcp.protocol import (
    JSONRPCRequest,
    MCP_PROTOCOL_VERSION,
)
from mewcode.mcp.transport.base import BaseTransport


class MCPClient:
    """An MCP client that speaks JSON-RPC 2.0 over a transport.

    Lifecycle: connect → initialize → initialized → discover → call.
    """

    def __init__(self, transport: BaseTransport, server_name: str, timeout: float = 30.0) -> None:
        self._transport = transport
        self.server_name = server_name
        self._timeout = timeout
        self._server_info: dict = {}
        self._connected = False

    # -- lifecycle ------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._connected and self._transport.is_connected

    async def connect(self) -> None:
        """Establish connection and run MCP handshake."""
        await self._transport.connect()

        # 1. Initialize
        init_resp = await self._send("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "MewCode", "version": "0.1.0"},
        })
        if init_resp.error:
            raise ConnectionError(f"Initialize failed: {init_resp.error}")
        self._server_info = init_resp.result or {}

        # 2. Send initialized notification
        await self._transport.send_notification("notifications/initialized")
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        await self._transport.disconnect()

    # -- discovery ------------------------------------------------------------

    async def list_tools(self) -> list[dict]:
        resp = await self._send("tools/list")
        if resp.error:
            raise RuntimeError(f"tools/list failed: {resp.error}")
        return (resp.result or {}).get("tools", [])

    async def list_resources(self) -> list[dict]:
        resp = await self._send("resources/list")
        if resp.error:
            raise RuntimeError(f"resources/list failed: {resp.error}")
        return (resp.result or {}).get("resources", [])

    async def list_prompts(self) -> list[dict]:
        resp = await self._send("prompts/list")
        if resp.error:
            raise RuntimeError(f"prompts/list failed: {resp.error}")
        return (resp.result or {}).get("prompts", [])

    # -- tool call ------------------------------------------------------------

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Call a tool and return the text content."""
        resp = await self._send("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if resp.error:
            raise RuntimeError(f"tools/call '{name}' failed: {resp.error}")
        return self._extract_text(resp.result)

    # -- resource read --------------------------------------------------------

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a resource by URI."""
        resp = await self._send("resources/read", {"uri": uri})
        if resp.error:
            raise RuntimeError(f"resources/read '{uri}' failed: {resp.error}")
        result = resp.result or {}
        contents = result.get("contents", [])
        return {
            "uri": uri,
            "text": self._extract_text_from_contents(contents),
            "contents": contents,
        }

    # -- prompt get -----------------------------------------------------------

    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Get a prompt template."""
        params: dict = {"name": name}
        if arguments:
            params["arguments"] = arguments
        resp = await self._send("prompts/get", params)
        if resp.error:
            raise RuntimeError(f"prompts/get '{name}' failed: {resp.error}")
        return resp.result or {}

    # -- helpers --------------------------------------------------------------

    async def _send(self, method: str, params: dict | None = None):
        return await self._transport.send_request(
            JSONRPCRequest(method=method, params=params)
        )

    @staticmethod
    def _extract_text(result: dict) -> str:
        content = result.get("content", [])
        return MCPClient._extract_text_from_contents(content)

    @staticmethod
    def _extract_text_from_contents(contents: list) -> str:
        parts: list[str] = []
        for item in contents:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "resource":
                    resource = item.get("resource", {})
                    parts.append(resource.get("text", ""))
        return "\n".join(parts)
