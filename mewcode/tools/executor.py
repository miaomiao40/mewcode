"""Tool executor — runs a tool with timeout and error handling."""

import asyncio
from mewcode.tools.base import BaseTool, ToolResult


class ToolExecutor:
    """Executes a tool with timeout and structured error handling."""

    def __init__(self, default_timeout: float = 30.0) -> None:
        self._default_timeout = default_timeout

    async def execute(
        self,
        tool: BaseTool,
        params: dict,
        timeout: float | None = None,
    ) -> ToolResult:
        """Run *tool* with *params*, enforcing a timeout.

        On timeout or unexpected exception, returns a structured failure
        ``ToolResult`` so the model can adjust rather than crashing.
        """
        timeout = timeout if timeout is not None else self._default_timeout
        try:
            return await asyncio.wait_for(
                tool.execute(**params),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                content="",
                error=f"工具 '{tool.name}' 执行超时（{timeout}s）",
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                content="",
                error=f"工具 '{tool.name}' 执行异常: {type(exc).__name__}: {exc}",
            )
