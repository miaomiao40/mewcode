"""Team member runner — coroutine backend implementation."""

import asyncio
from pathlib import Path

from mewcode.agent.loop import AgentLoop
from mewcode.conversation.history import ConversationHistory
from mewcode.prompts.builder import PromptBuilder
from mewcode.prompts.injector import PromptInjector
from mewcode.providers.base import BaseProvider
from mewcode.teams.mailbox import Mailbox
from mewcode.teams.models import MemberDef, MemberStatus, MessageType, TeamMessage
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry


class TeamMember:
    """Runs a team member in a coroutine (same process, independent history)."""

    def __init__(
        self,
        member_def: MemberDef,
        team_dir: Path,
        provider: BaseProvider,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
    ) -> None:
        self.defn = member_def
        self.status = MemberStatus.IDLE
        self._history = ConversationHistory()
        self._mailbox = Mailbox(team_dir, member_def.name)
        self._provider = provider
        self._tool_registry = tool_registry
        self._tool_executor = tool_executor
        self._last_msg_id = ""

    async def run(self, task: str) -> str:
        """Execute one task to completion. Returns result text."""
        self.status = MemberStatus.BUSY
        self._history.add_user_message(task)

        prompt_builder = PromptBuilder()
        prompt_injector = PromptInjector()

        loop = AgentLoop(
            provider=self._provider,
            tool_registry=self._tool_registry,
            tool_executor=self._tool_executor,
            prompt_builder=prompt_builder,
            prompt_injector=prompt_injector,
            max_rounds=10,
        )

        result_parts: list[str] = []
        async for event in loop.run(self._history):
            from mewcode.agent.events import TextDeltaEvent, AgentDoneEvent
            if isinstance(event, TextDeltaEvent):
                result_parts.append(event.text)
            elif isinstance(event, AgentDoneEvent):
                break

        result = "".join(result_parts)
        self.status = MemberStatus.IDLE
        self._notify_lead("done", result)
        return result

    async def resume(self, new_task: str) -> str:
        """Resume from idle with a new task (keeps context)."""
        self._check_mail()
        return await self.run(new_task)

    def _notify_lead(self, event: str, detail: str = "") -> None:
        msg = TeamMessage(
            from_member=self.defn.name, to_member="lead",
            msg_type=MessageType.LIFECYCLE,
            content=f"[{event}] {detail}",
        )
        self._mailbox.send(msg)

    def _check_mail(self) -> list[TeamMessage]:
        msgs = self._mailbox.read_new(self._last_msg_id)
        if msgs:
            self._last_msg_id = msgs[-1].id
            for m in msgs:
                if m.msg_type == MessageType.TEXT and m.from_member == "lead":
                    self._history.add_context_message(f"[Lead → {self.defn.name}]: {m.content}")
        return msgs
