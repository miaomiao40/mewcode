"""Stdio transport — spawns a subprocess for MCP communication."""

import asyncio
import os

from mewcode.mcp.protocol import (
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    decode_message,
    encode_message,
)
from mewcode.mcp.transport.base import BaseTransport


class StdioTransport(BaseTransport):
    """Communicates with an MCP server via stdin/stdout."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._command = command
        self._args = args or []
        self._env = env
        self._timeout = timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 1
        self._reader_task: asyncio.Task | None = None

    @property
    def is_connected(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def connect(self) -> None:
        merged_env = os.environ.copy()
        if self._env:
            merged_env.update(self._env)

        self._proc = await asyncio.create_subprocess_exec(
            self._command,
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )
        self._reader_task = asyncio.ensure_future(self._read_loop())

    async def disconnect(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self._proc:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self._proc.kill()
            self._proc = None
        # Reject all pending futures
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("Transport disconnected"))
        self._pending.clear()

    async def send_request(self, request: JSONRPCRequest) -> JSONRPCResponse:
        if not self._proc or self._proc.stdin is None:
            raise ConnectionError("Transport not connected")

        req_id = self._next_id
        self._next_id += 1
        request.id = req_id

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        line = encode_message(request) + "\n"
        self._proc.stdin.write(line.encode("utf-8"))
        await self._proc.stdin.drain()

        try:
            return await asyncio.wait_for(future, timeout=self._timeout)
        finally:
            self._pending.pop(req_id, None)

    async def send_notification(self, method: str, params: dict | None = None) -> None:
        if not self._proc or self._proc.stdin is None:
            return
        notif = JSONRPCNotification(method=method, params=params)
        line = encode_message(notif) + "\n"
        self._proc.stdin.write(line.encode("utf-8"))
        await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        """Read lines from stdout and dispatch responses."""
        assert self._proc and self._proc.stdout
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break  # EOF
                msg = decode_message(line.decode("utf-8").strip())
                if isinstance(msg, JSONRPCResponse) and msg.id in self._pending:
                    fut = self._pending[msg.id]
                    if not fut.done():
                        fut.set_result(msg)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
