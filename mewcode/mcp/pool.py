"""MCP connection pool — eager startup connect, cache, reconnect on demand."""

import asyncio

from mewcode.mcp.client import MCPClient
from mewcode.mcp.config import MCPServerConfig
from mewcode.mcp.transport.http import HttpTransport
from mewcode.mcp.transport.stdio import StdioTransport


class MCPPool:
    """Manages MCP client connections.

    All servers are connected eagerly at startup via ``connect_all``.
    ``get_client`` returns a cached client, reconnecting once if the
    connection was lost.
    """

    def __init__(self, server_configs: list[MCPServerConfig]) -> None:
        self._configs: dict[str, MCPServerConfig] = {c.name: c for c in server_configs}
        self._clients: dict[str, MCPClient] = {}

    # -- startup --------------------------------------------------------------

    async def connect_all(self) -> dict[str, MCPClient]:
        """Connect to all configured servers in parallel.

        Returns a dict of {server_name: client} for successfully connected
        servers.  Failed servers are logged (printed to stderr) but do not
        block startup.
        """
        async def _connect_one(config: MCPServerConfig) -> tuple[str, MCPClient | None]:
            try:
                transport = self._create_transport(config)
                client = MCPClient(transport, config.name, timeout=config.timeout)
                await client.connect()
                return config.name, client
            except Exception as exc:
                import sys
                print(f"MCP [{config.name}]: 连接失败 — {exc}", file=sys.stderr)
                return config.name, None

        tasks = [_connect_one(c) for c in self._configs.values()]
        results: list[tuple[str, MCPClient | None]] = await asyncio.gather(*tasks)

        for name, client in results:
            if client is not None:
                self._clients[name] = client

        return {n: c for n, c in self._clients.items()}

    # -- runtime access -------------------------------------------------------

    async def get_client(self, server_name: str) -> MCPClient | None:
        """Return a connected client, reconnecting once if needed."""
        client = self._clients.get(server_name)
        if client is not None:
            if client.is_connected:
                return client
            # Dead connection — try reconnect once
            try:
                await client.connect()
                return client
            except Exception:
                import sys
                print(f"MCP [{server_name}]: 重连失败，工具不可用", file=sys.stderr)
                return None

        # Not in cache — try connecting (server might have been added after startup)
        config = self._configs.get(server_name)
        if config is None:
            return None
        try:
            transport = self._create_transport(config)
            client = MCPClient(transport, config.name, timeout=config.timeout)
            await client.connect()
            self._clients[server_name] = client
            return client
        except Exception:
            return None

    # -- shutdown -------------------------------------------------------------

    async def shutdown(self) -> None:
        for client in self._clients.values():
            await client.disconnect()
        self._clients.clear()

    # -- internals ------------------------------------------------------------

    def _create_transport(self, config: MCPServerConfig):
        if config.transport == "stdio":
            return StdioTransport(
                command=config.command,
                args=config.args,
                env=config.env,
                timeout=config.timeout,
            )
        elif config.transport == "http":
            return HttpTransport(
                url=config.url,
                headers=config.headers,
                timeout=config.timeout,
            )
        raise ValueError(f"不支持的传输方式: {config.transport}")
