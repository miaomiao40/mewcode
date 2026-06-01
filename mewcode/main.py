"""Main entry point — wires config, prompts, security, MCP, agent loop, history, and TUI."""

import asyncio
import sys

from mewcode.agent.loop import AgentLoop
from mewcode.config.loader import load_config
from mewcode.instructions import InstructionsLoader
from mewcode.mcp.manager import MCPManager
from mewcode.notes import AutoNoteManager
from mewcode.hooks import load_hooks, HookEngine
from mewcode.skills import SkillLoader, SkillRegistry, SkillTool
from mewcode.subagent import RoleLoader, SubAgentRunner, BackgroundTaskManager, SubAgentTool
from mewcode.worktree import GitWorktreeManager, BackgroundCleaner
from mewcode.providers.base import create_provider
from mewcode.conversation.history import ConversationHistory
from mewcode.conversation.compression import ContextCompressor
from mewcode.conversation.truncator import ToolResultTruncator
from mewcode.prompts import PromptBuilder, PromptInjector, collect_environment
from mewcode.security import SecurityGuard, SecurityPolicy, PathSandbox, SecurityLevel
from mewcode.storage.sessions import SessionStore
from mewcode.tools import (
    ToolRegistry,
    ToolExecutor,
    ReadFileTool,
    WriteFileTool,
    EditFileTool,
    RunCommandTool,
    GlobTool,
    GrepTool,
)
from mewcode.tui.app import MewCodeTUI


def _create_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(EditFileTool())
    registry.register(RunCommandTool())
    registry.register(GlobTool())
    registry.register(GrepTool())
    return registry


async def main() -> None:
    # 1. Load configuration
    try:
        app_config = load_config()
    except SystemExit:
        return

    # 2. Find active provider
    active_config = None
    for p in app_config.providers:
        if p.name == app_config.active_provider:
            active_config = p
            break
    if active_config is None:
        print(f"active_provider '{app_config.active_provider}' 未找到", file=sys.stderr)
        return

    # 3. Create provider
    try:
        provider = create_provider(active_config)
    except ValueError as e:
        print(f"无法创建 provider: {e}", file=sys.stderr)
        return

    # 4. Conversation history + session store + migration
    history = ConversationHistory()
    session_store = SessionStore()
    session_store.migrate_old_format()  # one-time: default.json → JSONL
    restored = session_store.load()
    if restored is not None:
        restored_history, _, _ = restored
        history = restored_history

    # 4.5. Instructions
    instructions_text = InstructionsLoader().load()

    # 5. Prompt system
    prompt_builder = PromptBuilder()
    prompt_injector = PromptInjector()
    environment_text = collect_environment()

    # 6. Context compressor + truncator
    compressor = ContextCompressor(model=active_config.model, provider=provider)
    truncator = ToolResultTruncator()
    note_manager = AutoNoteManager(provider=provider, interval=5)

    # 7. Tool registry (create early — needed by skills MCP subagent)
    tool_registry = _create_tool_registry()

    # 7.5. Skills (needs tool_registry for whitelist validation)
    skill_loader = SkillLoader()
    skill_registry = SkillRegistry(skill_loader)
    skill_metas = skill_registry.load_all()
    # Validate tool whitelists fail-fast
    for meta in skill_metas:
        if meta.tools:
            for tool_name in meta.tools:
                if not tool_registry.get(tool_name):
                    print(f"Skill [{meta.name}]: 白名单工具 '{tool_name}' 不存在", file=sys.stderr)
                    return
    # Register skill_loader as always-available system tool
    skill_tool = SkillTool(skill_registry)
    tool_registry.register(skill_tool)

    # Skill summaries for the prompt
    skill_summaries = "\n".join(
        f"- `skill_loader(name=\"{m.name}\")`: {m.description}" for m in skill_metas
    ) if skill_metas else ""
    if skill_summaries:
        instructions_text = (
            f"## 可用 Skills\n"
            f"使用 skill_loader 工具激活 Skill 以获取 SOP 指令。"
            f"激活后每轮 LLM 调用都会看到 Skill 的完整指令。\n"
            f"{skill_summaries}\n\n" + instructions_text
        )

    # 8. MCP — discover external servers and register their tools
    mcp_manager = MCPManager(tool_registry)
    mcp_manager.load_config()
    if mcp_manager.is_configured:
        mcp_count = await mcp_manager.discover_and_register()
        if mcp_count > 0:
            print(f"MCP: 已注册 {mcp_count} 个远端工具/资源/提示词", file=sys.stderr)

    # 9. Security system
    sandbox = PathSandbox()
    policy = SecurityPolicy(level=SecurityLevel.NORMAL)
    security_guard = SecurityGuard(policy=policy, sandbox=sandbox)

    # 10. Tool executor & Agent Loop
    tool_executor = ToolExecutor(default_timeout=30.0)
    # Hooks
    hook_rules = load_hooks()
    hook_engine = HookEngine(hook_rules)

    # Sub-agent system
    role_loader = RoleLoader()
    roles = role_loader.load_all()
    sub_runner = SubAgentRunner(provider, tool_registry, tool_executor, roles)
    task_manager = BackgroundTaskManager()
    sub_agent_tool = SubAgentTool(sub_runner, task_manager, roles, history)
    tool_registry.register(sub_agent_tool)

    # Worktree management
    worktree_manager = GitWorktreeManager()
    cleaner = BackgroundCleaner(worktree_manager)
    cleaner.start()

    # --resume: restore previous worktree session
    if "--resume" in sys.argv and worktree_manager._load_session():
        session = worktree_manager._load_session()
        if session and session.get("active_worktree"):
            await worktree_manager.enter(session["active_worktree"])

    agent_loop = AgentLoop(
        provider=provider,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        prompt_builder=prompt_builder,
        prompt_injector=prompt_injector,
        security_guard=security_guard,
        truncator=truncator,
        note_manager=note_manager,
        skill_registry=skill_registry,
        hook_engine=hook_engine,
        instructions_text=instructions_text,
        environment_text=environment_text,
        max_rounds=10,
    )

    # Apply --mode CLI flag if any
    if "--mode" in sys.argv:
        idx = sys.argv.index("--mode")
        if idx + 1 < len(sys.argv):
            mode_str = sys.argv[idx + 1].lower()
            try:
                level = SecurityLevel(mode_str)
                security_guard.set_level(level)
                agent_loop.set_security_level(level)
            except ValueError:
                print(f"无效的安全等级: {mode_str}，使用默认", file=sys.stderr)

    # 11. Launch TUI
    tui = MewCodeTUI(
        agent_loop=agent_loop,
        history=history,
        compressor=compressor,
        session_store=session_store,
        note_manager=note_manager,
        provider_name=active_config.name,
        model=active_config.model,
        mcp_server_count=len(mcp_manager.connected_servers),
        skill_registry=skill_registry,
        task_manager=task_manager,
        worktree_manager=worktree_manager,
    )
    try:
        await tui.run_async()
    finally:
        cleaner.stop()
        await mcp_manager.shutdown()


def entry_point() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
