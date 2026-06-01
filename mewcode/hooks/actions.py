"""Action executors — shell, prompt_inject, http, sub_agent."""

import asyncio
import sys

import httpx

from mewcode.hooks.models import Action, ActionType
from mewcode.hooks.templates import TemplateEngine


class ActionExecutor:
    """Execute hook actions with error isolation."""

    def __init__(self, template_engine: TemplateEngine | None = None) -> None:
        self._templates = template_engine or TemplateEngine()

    async def execute(
        self,
        action: Action,
        context: dict,
        timeout: float = 30.0,
    ) -> str | None:
        """Execute a single action.  Returns the result text, or None.

        Errors are logged to stderr but never raised.
        """
        try:
            if action.type == ActionType.SHELL:
                return await self._exec_shell(action, context, timeout)
            elif action.type == ActionType.PROMPT_INJECT:
                return self._exec_prompt_inject(action, context)
            elif action.type == ActionType.HTTP:
                return await self._exec_http(action, context, timeout)
            elif action.type == ActionType.SUB_AGENT:
                return self._exec_sub_agent(action, context)
        except Exception as exc:
            print(f"Hook action [{action.type.value}]: 执行失败 — {exc}", file=sys.stderr)
        return None

    # -- internals -----------------------------------------------------------

    async def _exec_shell(self, action: Action, context: dict, timeout: float) -> str:
        cmd = self._templates.render(action.command, context)
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            result = out
            if err:
                result += f"\n[stderr]\n{err}"
            return result[:2000]
        except asyncio.TimeoutError:
            return f"(超时 {timeout}s)"

    def _exec_prompt_inject(self, action: Action, context: dict) -> str:
        return self._templates.render(action.text, context)

    async def _exec_http(self, action: Action, context: dict, timeout: float) -> str:
        url = self._templates.render(action.url, context)
        body = self._templates.render(action.body, context) if action.body else None
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            resp = await client.request(
                action.method, url, content=body, headers=action.headers,
            )
            return resp.text[:2000]

    def _exec_sub_agent(self, action: Action, context: dict) -> str:
        return f"[sub_agent] task: {action.task}（子 Agent 尚未实现）"
