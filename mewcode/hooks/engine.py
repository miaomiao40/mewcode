"""Hook engine — fires events at lifecycle points in the Agent Loop."""

import asyncio
import sys
from typing import Any

from mewcode.hooks.actions import ActionExecutor
from mewcode.hooks.conditions import ConditionEvaluator
from mewcode.hooks.models import HookEvent, Rule
from mewcode.hooks.templates import TemplateEngine


class HookEngine:
    """Registers hook rules and fires events at lifecycle nodes."""

    def __init__(self, rules: list[Rule]) -> None:
        self._rules = rules
        self._conditions = ConditionEvaluator()
        self._templates = TemplateEngine()
        self._actions = ActionExecutor(self._templates)
        self._fired_once: set[str] = set()  # rule names that fired (for once:true)

    # -- public API -----------------------------------------------------------

    async def fire(
        self,
        event: HookEvent,
        context: dict[str, Any] | None = None,
    ) -> str | None:
        """Fire all matching rules for *event*.

        For TOOL_PRE_EXEC, returns the first rejection reason (or None if all
        allowed).  The caller should feed the rejection back to the LLM as a
        tool result.

        For all other events, returns None — errors are logged, never raised.
        """
        ctx = context or {}
        ctx["_event"] = event.value

        rejection: str | None = None

        for rule in self._rules:
            if rule.event != event:
                continue

            # once-only
            if rule.control.once and rule.name in self._fired_once:
                continue

            # Evaluate condition
            if not self._conditions.evaluate(rule.condition, ctx):
                continue

            # Mark fired
            if rule.control.once:
                self._fired_once.add(rule.name)

            # Execute actions
            if rule.control.async_:
                for action in rule.actions:
                    asyncio.ensure_future(
                        self._actions.execute(action, ctx, timeout=rule.control.timeout)
                    )
            else:
                for action in rule.actions:
                    result = await self._actions.execute(
                        action, ctx, timeout=rule.control.timeout,
                    )
                    # For intercept events, collect rejection from prompt_inject
                    if rule.is_intercept and action.type.value == "prompt_inject" and result:
                        rejection = result

        return rejection

    def fire_sync(
        self,
        event: HookEvent,
        context: dict[str, Any] | None = None,
    ) -> str | None:
        """Synchronous helper — runs fire() inside an event loop if needed."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in event loop — schedule and wait
                future = asyncio.ensure_future(self.fire(event, context))
                # Can't block here — just fire and forget
                return None
            return asyncio.run(self.fire(event, context))
        except RuntimeError:
            return asyncio.run(self.fire(event, context))

    def reset_once(self) -> None:
        """Clear once-fired tracking (e.g., on new session)."""
        self._fired_once.clear()
