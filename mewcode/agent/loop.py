"""Agent Loop — ReAct pattern with prompt assembly, injections, and cache tracking."""

import asyncio
from collections.abc import AsyncIterator

from mewcode.agent.events import (
    AgentDoneEvent,
    AgentEvent,
    ErrorEvent,
    HITLRequestEvent,
    TextDeltaEvent,
    ThinkingEvent,
    ToolBlockedEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from mewcode.conversation.history import ConversationHistory
from mewcode.conversation.truncator import ToolResultTruncator
from mewcode.notes.manager import AutoNoteManager
from mewcode.hooks.engine import HookEngine
from mewcode.hooks.models import HookEvent
from mewcode.skills.registry import SkillRegistry
from mewcode.providers.base import BaseProvider, ToolCall
from mewcode.prompts.builder import PromptBuilder
from mewcode.prompts.injector import PromptInjector
from mewcode.security.guard import SecurityGuard
from mewcode.security.models import HITLDecision, SecurityLevel
from mewcode.tools.base import ToolResult
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry

DEFAULT_MAX_ROUNDS = 10
_PLAN_MODE_ALLOWED = {"read_file", "glob", "grep"}


class AgentLoop:
    """ReAct 循环 + Prompt 拼装 + 缓存感知。"""

    def __init__(
        self,
        provider: BaseProvider,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        prompt_builder: PromptBuilder,
        prompt_injector: PromptInjector,
        security_guard: SecurityGuard | None = None,
        truncator: ToolResultTruncator | None = None,
        note_manager: AutoNoteManager | None = None,
        skill_registry: SkillRegistry | None = None,
        hook_engine: HookEngine | None = None,
        instructions_text: str = "",
        environment_text: str = "",
        max_rounds: int = DEFAULT_MAX_ROUNDS,
    ) -> None:
        self._provider = provider
        self._tool_registry = tool_registry
        self._tool_executor = tool_executor
        self._prompt_builder = prompt_builder
        self._prompt_injector = prompt_injector
        self._security_guard = security_guard
        self._truncator = truncator
        self._note_manager = note_manager
        self._skill_registry = skill_registry
        self._hook_engine = hook_engine
        self._instructions_text = instructions_text
        self._environment_text = environment_text
        self._max_rounds = max_rounds

        self._plan_only = False
        self._cancel_event = asyncio.Event()
        self.cache_hit = False

    # -- public API -----------------------------------------------------------

    @property
    def provider(self) -> BaseProvider:
        return self._provider

    @property
    def plan_only(self) -> bool:
        return self._plan_only

    def toggle_plan_only(self) -> bool:
        self._plan_only = not self._plan_only
        self._prompt_injector.set_plan_only(self._plan_only)
        return self._plan_only

    def cancel(self) -> None:
        self._cancel_event.set()

    def reset_cancel(self) -> None:
        self._cancel_event.clear()

    async def run(self, history: ConversationHistory) -> AsyncIterator[AgentEvent]:
        self.reset_cancel()
        self.cache_hit = False

        for round_num in range(1, self._max_rounds + 1):
            if self._cancel_event.is_set():
                yield AgentDoneEvent("cancelled")
                return

            # --- 1. 拼装本轮 messages ---
            messages = self._assemble_messages(history, round_num)

            # --- 1.5. Layer 1 截断 ---
            if self._truncator is not None:
                messages, trunc_infos = self._truncator.process_round(messages)
                for info in trunc_infos:
                    from mewcode.agent.events import TruncationEvent
                    yield TruncationEvent(
                        tool_name=info["tool_name"],
                        original_chars=info["original_chars"],
                        file_path=info["file_path"],
                    )

            # --- Hook: ROUND_START ---
            if self._hook_engine:
                await self._hook_engine.fire(HookEvent.ROUND_START, {
                    "round_number": round_num, "max_rounds": self._max_rounds,
                })

            # --- Hook: MESSAGE_PRE_SEND ---
            if self._hook_engine:
                await self._hook_engine.fire(HookEvent.MESSAGE_PRE_SEND, {
                    "message_count": len(messages),
                })

            # --- 2. 调 LLM ---
            tool_calls: list[ToolCall] = []
            text_parts: list[str] = []

            async for raw in self._provider.chat_stream(
                messages=messages,
                tools=self._build_tool_defs(),
                system_blocks=self._build_system_blocks(),
            ):
                if self._cancel_event.is_set():
                    yield AgentDoneEvent("cancelled")
                    return

                if isinstance(raw, str):
                    if raw.startswith("<<THINKING:") or raw.startswith("<<REASONING:"):
                        label = "Thinking" if raw.startswith("<<THINKING:") else "Reasoning"
                        text = raw[len("<<THINKING:"):-2] if raw.startswith("<<THINKING:") else raw[len("<<REASONING:"):-2]
                        yield ThinkingEvent(text=text, label=label)
                    elif raw.startswith("<<ERROR:"):
                        yield ErrorEvent(message=raw[len("<<ERROR:"):-2])
                        return
                    else:
                        text_parts.append(raw)
                        yield TextDeltaEvent(text=raw)
                else:
                    tool_calls.append(raw)
                    yield ToolCallEvent(tool_call=raw)

            # --- Hook: MESSAGE_POST_RECEIVE ---
            if self._hook_engine:
                await self._hook_engine.fire(HookEvent.MESSAGE_POST_RECEIVE, {
                    "text": "".join(text_parts)[:500],
                    "tool_calls_count": len(tool_calls),
                })

            # --- 3. 检测缓存命中 ---
            if hasattr(self._provider, 'cache_hit') and self._provider.cache_hit:
                self.cache_hit = True

            # --- 4. 无工具调用 → 终止 ---
            if not tool_calls:
                if text_parts:
                    history.add_assistant_message("".join(text_parts))
                yield AgentDoneEvent("no_tool_call")
                return

            # --- 5. 合并文本 + 工具调用为单条 assistant 消息 ---
            text_prefix = "".join(text_parts)
            tc_msg = self._provider.make_tool_calls_message(tool_calls, text_prefix=text_prefix)
            history.add_raw_message(tc_msg)

            # --- 6. 工具分批执行（含安全检查） ---
            reads, writes = self._partition_tools(tool_calls)

            # 读类 — 并发（安全检查前置）
            valid_reads: list[ToolCall] = []
            for tc in reads:
                allowed, reason, hitl_future = self._precheck_tool(tc)
                if hitl_future is not None:
                    prompt = self._security_guard.build_hitl_prompt(tc.name, tc.input)
                    yield HITLRequestEvent(
                        tool_name=tc.name, params=tc.input, prompt=prompt, future=hitl_future,
                    )
                    decision = await hitl_future
                    if decision == HITLDecision.DENY:
                        blocked_result = ToolResult(success=False, content="", error="用户拒绝了该操作")
                        yield ToolResultEvent(tool_name=tc.name, result=blocked_result)
                        self._append_tool_result(history, tc, blocked_result)
                        continue
                    self._security_guard.apply_hitl(decision, tc.name, tc.input)
                elif not allowed:
                    blocked_result = ToolResult(success=False, content="", error=reason)
                    yield ToolResultEvent(tool_name=tc.name, result=blocked_result)
                    self._append_tool_result(history, tc, blocked_result)
                    continue
                valid_reads.append(tc)

            if valid_reads:
                results = await self._execute_concurrent(valid_reads)
                for tc, result in zip(valid_reads, results):
                    yield ToolResultEvent(tool_name=tc.name, result=result)
                    self._append_tool_result(history, tc, result)

            # 写类 — 串行（每个执行前检查）
            for tc in writes:
                if self._cancel_event.is_set():
                    yield AgentDoneEvent("cancelled")
                    return

                if self._plan_only and tc.name not in _PLAN_MODE_ALLOWED:
                    blocked = await self._block_tool(tc)
                    yield blocked
                    self._append_tool_result(history, tc, blocked.result)
                    continue

                allowed, reason, hitl_future = self._precheck_tool(tc)
                if hitl_future is not None:
                    prompt = self._security_guard.build_hitl_prompt(tc.name, tc.input)
                    yield HITLRequestEvent(
                        tool_name=tc.name, params=tc.input, prompt=prompt, future=hitl_future,
                    )
                    decision = await hitl_future
                    if decision == HITLDecision.DENY:
                        blocked_result = ToolResult(success=False, content="", error="用户拒绝了该操作")
                        yield ToolResultEvent(tool_name=tc.name, result=blocked_result)
                        self._append_tool_result(history, tc, blocked_result)
                        continue
                    self._security_guard.apply_hitl(decision, tc.name, tc.input)
                elif not allowed:
                    blocked_result = ToolResult(success=False, content="", error=reason)
                    yield ToolResultEvent(tool_name=tc.name, result=blocked_result)
                    self._append_tool_result(history, tc, blocked_result)
                    continue

                # --- Hook: TOOL_PRE_EXEC (intercept) ---
                intercept_reason: str | None = None
                if self._hook_engine:
                    intercept_reason = await self._hook_engine.fire(
                        HookEvent.TOOL_PRE_EXEC,
                        {"tool_name": tc.name, "params": tc.input},
                    )

                if intercept_reason:
                    result = ToolResult(success=False, content="", error=intercept_reason)
                else:
                    result = await self._tool_executor.execute(
                        self._tool_registry.get(tc.name), tc.input,
                    )

                # --- Hook: TOOL_POST_EXEC ---
                if self._hook_engine:
                    await self._hook_engine.fire(HookEvent.TOOL_POST_EXEC, {
                        "tool_name": tc.name, "params": tc.input,
                        "success": result.success,
                    })

                yield ToolResultEvent(tool_name=tc.name, result=result)
                self._append_tool_result(history, tc, result)

        yield AgentDoneEvent("max_rounds")

    # -- message assembly -----------------------------------------------------

    def _assemble_messages(
        self, history: ConversationHistory, round_num: int,
    ) -> list:
        """Build the messages array for this round.

        Structure (for Anthropic): system is sent separately via _build_system_blocks.
        For OpenAI/DeepSeek: system prompt + env + injections all go in messages.
        """
        result: list = []

        is_anthropic = (self._provider.config.protocol == "anthropic")

        if not is_anthropic:
            # OpenAI / DeepSeek: system prompt goes in messages
            sys_prompt = self._prompt_builder.build()
            if sys_prompt:
                result.append({"role": "system", "content": sys_prompt})

        # Instructions (project + user MEWCODE.md)
        if self._instructions_text:
            role = "user" if is_anthropic else "system"
            result.append({
                "role": role,
                "content": f"[Instructions]\n{self._instructions_text}",
            })

        # Activated skills (pinned — always visible)
        if self._skill_registry:
            skill_text = self._skill_registry.get_active_instructions()
            if skill_text:
                role = "user" if is_anthropic else "system"
                result.append({
                    "role": role,
                    "content": f"[Activated Skills]\n{skill_text}",
                })

        # Environment context (not cached — dynamic)
        if self._environment_text:
            role = "user" if is_anthropic else "system"
            result.append({
                "role": role,
                "content": f"[Environment]\n{self._environment_text}",
            })

        # Per-round injection
        injection = self._prompt_injector.build_injection(round_num)
        if injection:
            result.append({"role": "user", "content": injection})

        # Conversation messages
        result.extend(history.get_messages())

        return result

    def _build_system_blocks(self) -> list[dict] | None:
        """Build Anthropic system blocks (None for other providers)."""
        if self._provider.config.protocol != "anthropic":
            return None
        return self._prompt_builder.build_anthropic()

    # -- internals ------------------------------------------------------------

    def _build_tool_defs(self) -> list[dict]:
        all_tools = (
            self._tool_registry.to_anthropic_format()
            if self._provider.config.protocol == "anthropic"
            else self._tool_registry.to_openai_format()
        )

        # Apply skill tool whitelist
        if self._skill_registry:
            whitelist = self._skill_registry.get_active_tool_whitelist()
            if whitelist is not None:
                # Always include skill_loader (system tool)
                whitelist_set = set(whitelist) | {"skill_loader"}
                all_tools = [t for t in all_tools
                             if t.get("name", "") in whitelist_set or
                                (isinstance(t.get("function"), dict) and
                                 t["function"].get("name", "") in whitelist_set)]

        return all_tools

    def _partition_tools(
        self, tool_calls: list[ToolCall],
    ) -> tuple[list[ToolCall], list[ToolCall]]:
        from mewcode.tools.base import ToolCategory
        reads: list[ToolCall] = []
        writes: list[ToolCall] = []
        for tc in tool_calls:
            tool = self._tool_registry.get(tc.name)
            if tool is not None and tool.category == ToolCategory.READ:
                reads.append(tc)
            else:
                writes.append(tc)
        return reads, writes

    async def _execute_concurrent(self, tool_calls: list[ToolCall]) -> list:
        async def _one(tc: ToolCall):
            tool = self._tool_registry.get(tc.name)
            if tool is None:
                return ToolResult(success=False, content="", error=f"未知工具: {tc.name}")
            return await self._tool_executor.execute(tool, tc.input)
        return await asyncio.gather(*[_one(tc) for tc in tool_calls])

    async def _block_tool(self, tc: ToolCall) -> ToolBlockedEvent:
        reason = (
            f"Plan-only 模式已开启，'{tc.name}' 是写入类工具，已被拦截。"
            f"请先关闭 plan-only 开关再执行修改操作。"
        )
        return ToolBlockedEvent(
            tool_name=tc.name, reason=reason,
        )

    def _precheck_tool(self, tc: ToolCall) -> tuple[bool, str, "asyncio.Future | None"]:
        """Run security check. Returns ``(allowed, reason, hitl_future)``.

        If ``hitl_future`` is not None, the caller must yield a HITLRequestEvent
        and await the future before proceeding.
        """
        if self._security_guard is None:
            return True, "ok", None

        allowed, reason = self._security_guard.check(tc.name, tc.input)
        if allowed and reason == "ask":
            loop = asyncio.get_event_loop()
            future: asyncio.Future = loop.create_future()
            return True, "ask", future
        return allowed, reason, None

    def record_round(self, user_msg: str, assistant_msg: str) -> None:
        """Record a completed round for auto-note purposes."""
        if self._note_manager:
            self._note_manager.record_round(user_msg, assistant_msg)

    async def update_notes_if_needed(self) -> int:
        """Trigger note update if interval reached. Returns number of files changed."""
        if self._note_manager and self._note_manager.should_update():
            results = await self._note_manager.update_all()
            return len(results)
        return 0

    def set_security_level(self, level: SecurityLevel) -> None:
        """Switch the global security level."""
        if self._security_guard:
            self._security_guard.set_level(level)

    def _append_tool_result(
        self, history: ConversationHistory, tool_call: ToolCall, result: ToolResult,
    ) -> None:
        tr_msg = self._provider.make_tool_result_message(
            tool_call.id, tool_call.name, result.to_message(),
        )
        history.add_raw_message(tr_msg)
