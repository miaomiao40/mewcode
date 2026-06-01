"""MCP manager — orchestrates eager connection + discovery + adapter registration."""

import asyncio

from mewcode.mcp.adapter import MCPPromptAdapter, MCPResourceAdapter, MCPToolAdapter
from mewcode.mcp.config import MCPServerConfig, load_mcp_config
from mewcode.mcp.pool import MCPPool
from mewcode.tools.registry import ToolRegistry


class MCPManager:
    """Connects to all MCP servers at startup, discovers their capabilities,
    and registers adapters into the tool registry."""

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._registry = tool_registry
        self._pool: MCPPool | None = None
        self._server_configs: list[MCPServerConfig] = []

    # -- initialization -------------------------------------------------------

    def load_config(self) -> list[MCPServerConfig]:
        """Load MCP server configs from project + global files."""
        self._server_configs = load_mcp_config()
        self._pool = MCPPool(self._server_configs)
        return self._server_configs

    @property
    def is_configured(self) -> bool:
        return len(self._server_configs) > 0

    @property
    def connected_servers(self) -> list[str]:
        if self._pool is None:
            return []
        return list(self._pool._clients.keys())

    # -- discovery + registration ---------------------------------------------

    async def discover_and_register(self) -> int:
        """Connect to all servers in parallel, then discover tools eagerly.

        Tools are registered immediately so the LLM sees them.  Resource and
        prompt discovery is *deferred* — adapters are registered with lazy
        ``list_resources`` / ``list_prompts`` on first ``execute()``.

        Returns the total number of adapters registered.
        """
        if self._pool is None:
            return 0

        clients = await self._pool.connect_all()

        async def _discover_one(name: str, client) -> int:
            count = 0
            try:
                # Tools — eager (LLM needs visibility)
                tools = await client.list_tools()
                for tool_def in tools:
                    self._registry.register(MCPToolAdapter(client, tool_def))
                    count += 1

                # Resources — lazy (adapter defers list_resources to first execute)
                self._registry.register(MCPResourceAdapter(client))
                count += 1

                # Prompts — lazy (adapter defers list_prompts to first execute)
                self._registry.register(MCPPromptAdapter(client))
                count += 1

            except Exception as exc:
                import sys
                print(f"MCP [{name}]: 发现失败 — {exc}", file=sys.stderr)
            return count

        tasks = [_discover_one(name, client) for name, client in clients.items()]
        results = await asyncio.gather(*tasks)
        return sum(results)

    async def shutdown(self) -> None:
        if self._pool:
            await self._pool.shutdown()
