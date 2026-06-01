"""Streamable HTTP transport for MCP."""

import asyncio

import httpx

from mewcode.mcp.protocol import (
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    decode_message,
    encode_message,
)
from mewcode.mcp.transport.base import BaseTransport


class HttpTransport(BaseTransport):
    """Communicates with an MCP server via Streamable HTTP (POST /mcp)."""

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._url = url.rstrip("/") + "/mcp"
        self._headers = headers or {}
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 1
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            headers={**self._headers, "Content-Type": "application/json"},
        )
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        if self._client:
            await self._client.aclose()
            self._client = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("Transport disconnected"))
        self._pending.clear()

    async def send_request(self, request: JSONRPCRequest) -> JSONRPCResponse:
        if not self._client:
            raise ConnectionError("Transport not connected")

        req_id = self._next_id
        self._next_id += 1
        request.id = req_id

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        try:
            resp = await self._client.post(
                self._url,
                content=encode_message(request),
            )
            if resp.status_code == 200:
                # Response may be SSE stream or plain JSON
                content_type = resp.headers.get("content-type", "")
                if "text/event-stream" in content_type:
                    # SSE — read the first event
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[len("data: "):]
                            msg = decode_message(data_str)
                            if isinstance(msg, JSONRPCResponse) and msg.id == req_id:
                                future.set_result(msg)
                                break
                else:
                    text = resp.text.strip()
                    msg = decode_message(text)
                    if isinstance(msg, JSONRPCResponse):
                        future.set_result(msg)
            else:
                future.set_exception(
                    ConnectionError(f"HTTP {resp.status_code}: {resp.text[:500]}")
                )
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)

        try:
            return await asyncio.wait_for(future, timeout=self._timeout)
        finally:
            self._pending.pop(req_id, None)

    async def send_notification(self, method: str, params: dict | None = None) -> None:
        if not self._client:
            return
        notif = JSONRPCNotification(method=method, params=params)
        try:
            await self._client.post(self._url, content=encode_message(notif))
        except Exception:
            pass  # Notifications are fire-and-forget
