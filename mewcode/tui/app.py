"""Prompt Toolkit TUI — event consumer, command dispatcher, status bar."""

import asyncio
from typing import TYPE_CHECKING

from prompt_toolkit.application import Application
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText, merge_formatted_text
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    HSplit,
    Layout,
    ScrollablePane,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea

from mewcode.agent.events import (
    AgentDoneEvent,
    ErrorEvent,
    HITLRequestEvent,
    ThinkingEvent,
    TextDeltaEvent,
    ToolBlockedEvent,
    ToolCallEvent,
    ToolResultEvent,
    TruncationEvent,
)
from mewcode.commands import CommandDispatcher, CommandRegistry, UIControl, register_builtins
from mewcode.security.models import HITLDecision, SecurityLevel
from mewcode.tui.render import (
    STYLE,
    format_error,
    format_info,
    format_user_message,
    format_warning,
)

if TYPE_CHECKING:
    from mewcode.agent.loop import AgentLoop
    from mewcode.conversation.history import ConversationHistory
    from mewcode.conversation.compression import ContextCompressor
    from mewcode.notes.manager import AutoNoteManager
    from mewcode.storage.sessions import SessionStore
    from mewcode.skills.registry import SkillRegistry


class _CommandCompleter(Completer):
    """Tab completer for slash commands."""

    def __init__(self, registry: CommandRegistry) -> None:
        self._registry = registry

    def get_completions(self, document, complete_event):
        text = document.text
        if text.startswith("/"):
            prefix = text[1:]
            for name in self._registry.get_completions(prefix):
                yield Completion(name, start_position=-len(text))


class MewCodeTUI(UIControl):
    """TUI application + UIControl implementation for commands."""

    def __init__(
        self,
        agent_loop: "AgentLoop",
        history: "ConversationHistory",
        compressor: "ContextCompressor",
        session_store: "SessionStore",
        note_manager: "AutoNoteManager | None",
        provider_name: str,
        model: str,
        mcp_server_count: int = 0,
        skill_registry: "SkillRegistry | None" = None,
        task_manager = None,
        worktree_manager = None,
    ) -> None:
        self._agent_loop = agent_loop
        self._history = history
        self._compressor = compressor
        self._session_store = session_store
        self._note_manager = note_manager
        self._skill_registry = skill_registry
        self._provider_name = provider_name
        self._model = model
        self._mcp_server_count = mcp_server_count

        # Command system
        self._cmd_registry = CommandRegistry()
        register_builtins(self._cmd_registry, ui=self, note_manager=note_manager,
                          skill_registry=skill_registry, task_manager=task_manager,
                          worktree_manager=worktree_manager)

        # Auto-register each skill as a /<name> command
        if skill_registry:
            for meta in skill_registry.list_available():
                self._register_skill_command(meta)
        self._cmd_dispatcher = CommandDispatcher(self._cmd_registry, ui=self)
        self._completer = _CommandCompleter(self._cmd_registry)

        self._output_fragments: list = []
        self._input_area = TextArea(
            height=1, prompt="> ", multiline=False,
            focus_on_click=True, completer=self._completer,
        )
        self._conversation_control = FormattedTextControl(
            text=lambda: merge_formatted_text(self._output_fragments),
            focusable=False,
        )
        # Status bar
        self._status_control = FormattedTextControl(
            text=lambda: self._build_status(),
            focusable=False,
        )

        self._kb = self._build_keybindings()
        self._layout = self._build_layout()
        self._app: Application | None = None
        self._generating = False
        self._hitl_future: asyncio.Future | None = None
        self._security_level = SecurityLevel.NORMAL

    # -- UIControl implementation --------------------------------------------

    def show_system_message(self, text: str) -> None:
        self._output_fragments.append(format_info(f"\n{text}"))
        self._refresh()

    def send_to_conversation(self, text: str) -> None:
        """Inject a prompt-inject command result into the AI."""
        asyncio.ensure_future(self._on_user_input(text))

    def toggle_plan_mode(self) -> bool:
        return self._agent_loop.toggle_plan_only()

    def set_security_level(self, level_name: str) -> str:
        try:
            level = SecurityLevel(level_name.lower())
            self._security_level = level
            self._agent_loop.set_security_level(level)
            return level.value
        except ValueError:
            return self._security_level.value

    def get_token_count(self) -> int:
        return self._history.estimated_token_count()

    def clear_conversation(self) -> None:
        self._history.clear()
        self._output_fragments.clear()
        # Also clear activated skills
        if self._skill_registry:
            self._skill_registry.clear_activated()
        # Wipe session file so old context doesn't come back on restart
        self._do_save()
        self._build_layout()

    async def trigger_compress(self) -> str:
        self._compressor.reset_circuit()
        self._compressor.reset_warning()
        result = await self._compressor.check_and_compress(
            self._history, self._agent_loop.provider)
        if result.was_compressed:
            return f"上下文已压缩：{result.messages_compressed} 条消息 → 节省约 {result.estimated_tokens_saved} tokens"
        if self._compressor.circuit_open:
            return "压缩熔断——已停止自动压缩"
        return "当前无需压缩"

    def get_session_list(self) -> list[dict]:
        return self._session_store.list_sessions()

    def load_session(self, session_id: str) -> str:
        restored = self._session_store.load(session_id)
        if restored is None:
            return f"会话 {session_id[:8]} 不存在"
        restored_history, provider, model = restored
        self._history._messages = restored_history._messages
        self._output_fragments.clear()
        self._build_layout()
        self._output_fragments.append(
            format_info(f"已加载会话 {session_id[:8]} ({len(restored_history)} 条消息)")
        )
        self._refresh()
        return f"已加载会话 {session_id[:8]} ({len(restored_history)} 条消息)"

    def new_session(self) -> str:
        sid = self._session_store.new_session()
        self._history.clear()
        self._output_fragments.clear()
        self._build_layout()
        self._output_fragments.append(format_info(f"新会话 {sid}"))
        self._refresh()
        return f"新会话已创建: {sid}"

    def delete_session(self, session_id: str) -> str:
        ok = self._session_store.delete(session_id)
        if ok:
            return f"会话 {session_id} 已删除"
        return f"会话 {session_id} 不存在"

    def get_plan_only(self) -> bool:
        return self._agent_loop.plan_only

    def get_security_level(self) -> str:
        return self._security_level.value

    # -- layout --------------------------------------------------------------

    def _build_layout(self) -> Layout:
        mcp_info = f" | MCP: {self._mcp_server_count} servers" if self._mcp_server_count > 0 else ""
        welcome = FormattedText([
            ("bold", "MewCode"),
            ("", f" — Provider: {self._provider_name} | Model: {self._model}{mcp_info}"),
            ("class:info", "\nCtrl+C exit | Enter submit | /help for commands\n"),
            ("", "─" * 60),
        ])
        self._output_fragments.append(welcome)

        conversation_window = ScrollablePane(
            content=Window(
                content=self._conversation_control,
                wrap_lines=True, always_hide_cursor=True,
            )
        )
        # Output = conversation + status bar
        root = HSplit([
            conversation_window,
            Window(height=1, char="─"),
            Window(content=self._status_control, height=1),
            self._input_area,
        ])
        return Layout(root, focused_element=self._input_area)

    def _build_status(self) -> FormattedText:
        plan = "ON" if self._agent_loop.plan_only else "OFF"
        return FormattedText([
            ("class:info", f" [Plan: {plan}] [Sec: {self._security_level.value}] "
             f"| /help /clear /compress /status"),
        ])

    # -- key bindings --------------------------------------------------------

    def _build_keybindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("enter", filter=Condition(lambda: self._hitl_future is None), eager=True)
        def _(event):
            text = self._input_area.text.strip()
            if not text or self._generating:
                return
            self._input_area.text = ""

            # Route: command or AI
            if self._cmd_dispatcher.is_command(text):
                asyncio.ensure_future(self._handle_command(text))
            else:
                asyncio.ensure_future(self._on_user_input(text))

        @kb.add("c-c", eager=True)
        def _(event):
            if self._hitl_future and not self._hitl_future.done():
                self._hitl_future.set_result(HITLDecision.DENY)
            self._agent_loop.cancel()
            self._do_save()
            asyncio.ensure_future(self._exit_notes())
            self._output_fragments.append(format_info("Goodbye!"))
            if self._app:
                self._app.exit()

        @kb.add("c-p", eager=True)
        def _(event):
            new_state = self._agent_loop.toggle_plan_only()
            self._output_fragments.append(
                format_info(f"Plan-only 模式: {'ON' if new_state else 'OFF'}"))
            self._refresh()

        @kb.add("a", filter=Condition(lambda: self._hitl_future is not None), eager=True)
        def _(event): self._resolve_hitl(HITLDecision.ALLOW_ONCE)
        @kb.add("s", filter=Condition(lambda: self._hitl_future is not None), eager=True)
        def _(event): self._resolve_hitl(HITLDecision.ALLOW_SESSION)
        @kb.add("p", filter=Condition(lambda: self._hitl_future is not None), eager=True)
        def _(event): self._resolve_hitl(HITLDecision.ALLOW_PERMANENT)
        @kb.add("d", filter=Condition(lambda: self._hitl_future is not None), eager=True)
        def _(event): self._resolve_hitl(HITLDecision.DENY)

        @kb.add("c-s", eager=True)
        def _(event):
            levels = [SecurityLevel.STRICT, SecurityLevel.NORMAL, SecurityLevel.PERMISSIVE]
            idx = levels.index(self._security_level)
            self._security_level = levels[(idx + 1) % len(levels)]
            self._agent_loop.set_security_level(self._security_level)
            labels = {SecurityLevel.STRICT: "严格", SecurityLevel.NORMAL: "默认", SecurityLevel.PERMISSIVE: "放行"}
            self._output_fragments.append(format_info(f"安全等级: {labels[self._security_level]}"))
            self._refresh()

        @kb.add("c-q", eager=True)
        def _(event):
            if not self._generating:
                asyncio.ensure_future(self._manual_compress())

        return kb

    def _register_skill_command(self, meta) -> None:
        """Register a skill as a /<name> slash command (hot-reload on exec)."""
        from mewcode.commands.types import CommandMeta, CommandType

        async def _handler(args: list[str]) -> str:
            # Hot-reload from source
            if self._skill_registry:
                skill = self._skill_registry.activate(meta.name)
                if skill:
                    return f"Skill '{meta.name}' 已激活。\n\n{skill.body[:1000]}"
            return f"Skill '{meta.name}' 激活失败"

        # Skip if command name already taken (e.g. built-in /review)
        if self._cmd_registry.lookup(meta.name) is None:
            self._cmd_registry.register(CommandMeta(
                name=meta.name,
                description=meta.description,
                usage=f"/{meta.name}",
                cmd_type=CommandType.UI,
                handler=_handler,
            ))

    # -- command handling ----------------------------------------------------

    async def _handle_command(self, text: str) -> None:
        was_cmd, result = await self._cmd_dispatcher.dispatch(text)
        if result:
            self._output_fragments.append(format_info(result))
            self._refresh()

    # -- message handling ----------------------------------------------------

    async def _on_user_input(self, text: str) -> None:
        self._generating = True
        self._output_fragments.append(format_user_message(text))
        self._history.add_user_message(text)
        self._refresh()

        comp = await self._compressor.check_and_compress(self._history, self._agent_loop.provider)
        if comp.warning_issued:
            self._output_fragments.append(format_warning(
                f"上下文窗口使用超过 {self._compressor.warning_threshold} tokens "
                f"(窗口上限 {self._compressor.context_window})"))
            self._refresh()
        if comp.was_compressed:
            self._output_fragments.append(format_info(
                f"上下文已压缩：{comp.messages_compressed} 条消息 → "
                f"摘要，节省约 {comp.estimated_tokens_saved} tokens"))
            self._refresh()

        # Stream AI response
        ai_prefix = "\n\nMewCode: "
        thinking_active = False
        current_response = ""
        streaming_start: int | None = None

        async for event in self._agent_loop.run(self._history):
            if isinstance(event, TextDeltaEvent):
                if thinking_active:
                    thinking_active = False
                    if streaming_start is not None:
                        self._output_fragments[streaming_start] = FormattedText([
                            ("class:ai-prefix", ai_prefix)])
                if streaming_start is None:
                    streaming_start = len(self._output_fragments)
                    self._output_fragments.append(FormattedText([("class:ai-prefix", ai_prefix)]))
                current_response += event.text
                del self._output_fragments[streaming_start + 1:]
                self._output_fragments.append(FormattedText([("", current_response)]))
                self._refresh()

            elif isinstance(event, ThinkingEvent):
                if not thinking_active:
                    thinking_active = True
                    if streaming_start is None:
                        streaming_start = len(self._output_fragments)
                        self._output_fragments.append(
                            FormattedText([("class:thinking", f"\n\n[{event.label}] ")]))
                    else:
                        self._output_fragments[streaming_start] = FormattedText([
                            ("class:thinking", f"\n\n[{event.label}] ")])
                del self._output_fragments[streaming_start + 1:]
                self._output_fragments.append(FormattedText([("class:thinking", event.text)]))
                self._refresh()

            elif isinstance(event, ToolCallEvent):
                args_str = ", ".join(f"{k}={v!r}" for k, v in event.tool_call.input.items())
                self._output_fragments.append(format_info(f"\n🔧 {event.tool_call.name}({args_str})"))
                self._refresh()

            elif isinstance(event, ToolResultEvent):
                display = event.result.content[:500]
                if len(event.result.content) > 500:
                    display += "..."
                if event.result.success:
                    self._output_fragments.append(format_info(f"  → {display}"))
                else:
                    self._output_fragments.append(format_error(f"  → {event.result.error}"))
                self._refresh()

            elif isinstance(event, ToolBlockedEvent):
                self._output_fragments.append(format_warning(f"\n⛔ {event.reason}"))
                self._refresh()

            elif isinstance(event, TruncationEvent):
                self._output_fragments.append(format_info(
                    f"\n📎 {event.tool_name} 结果过大（{event.original_chars:,} 字符）→ 存盘 {event.file_path}"))
                self._refresh()

            elif isinstance(event, HITLRequestEvent):
                self._output_fragments.append(
                    FormattedText([("class:warning", f"\n{event.prompt}\n")]))
                self._hitl_future = event.future
                self._refresh()

            elif isinstance(event, AgentDoneEvent):
                if self._agent_loop.cache_hit:
                    self._output_fragments.append(
                        FormattedText([("class:info", " [cache: ✓]")]))
                    self._refresh()
                asyncio.ensure_future(self._maybe_update_notes())
                break

            elif isinstance(event, ErrorEvent):
                self._output_fragments.append(format_error(f"\n{event.message}"))
                self._refresh()
                break

        # Record round for notes
        if current_response:
            self._agent_loop.record_round(text, current_response)

        self._do_save()
        self._generating = False

    # -- helpers -------------------------------------------------------------

    def _resolve_hitl(self, decision: HITLDecision) -> None:
        if self._hitl_future and not self._hitl_future.done():
            labels = {HITLDecision.ALLOW_ONCE: "允许(本次)", HITLDecision.ALLOW_SESSION: "允许(本会话)",
                      HITLDecision.ALLOW_PERMANENT: "允许(永久)", HITLDecision.DENY: "拒绝"}
            self._output_fragments.append(format_info(f" → {labels[decision]}"))
            self._refresh()
            self._hitl_future.set_result(decision)
            self._hitl_future = None

    async def _maybe_update_notes(self) -> None:
        count = await self._agent_loop.update_notes_if_needed()
        if count > 0:
            self._output_fragments.append(format_info(f"📝 已更新 {count} 个笔记文件"))
            self._refresh()

    async def _exit_notes(self) -> None:
        if self._note_manager:
            await self._note_manager.update_on_exit()

    async def _manual_compress(self) -> None:
        self._compressor.reset_circuit()
        self._compressor.reset_warning()
        result = await self._compressor.check_and_compress(
            self._history, self._agent_loop.provider)
        if result.was_compressed:
            self._output_fragments.append(format_info(
                f"上下文已压缩：{result.messages_compressed} 条消息 → "
                f"摘要，节省约 {result.estimated_tokens_saved} tokens"))
        elif self._compressor.circuit_open:
            self._output_fragments.append(format_warning("压缩熔断——已停止自动压缩"))
        else:
            self._output_fragments.append(format_info("当前无需压缩"))
        self._refresh()

    def _refresh(self) -> None:
        if self._app:
            self._app.invalidate()

    def _do_save(self) -> None:
        self._session_store.save(
            self._history,
            provider_name=self._provider_name, model=self._model,
        )

    # -- run -----------------------------------------------------------------

    def run(self) -> None:
        import asyncio
        asyncio.run(self.run_async())

    async def run_async(self) -> None:
        self._app = Application(
            layout=self._layout, key_bindings=self._kb, style=STYLE,
            full_screen=True, mouse_support=False,
        )
        await self._app.run_async()
