"""Sub-agent runner — executes a sub-agent to completion (run-to-end mode)."""

from mewcode.agent.loop import AgentLoop
from mewcode.conversation.history import ConversationHistory
from mewcode.providers.base import BaseProvider
from mewcode.prompts.builder import PromptBuilder
from mewcode.prompts.injector import PromptInjector
from mewcode.subagent.filter import ToolFilter
from mewcode.subagent.models import SubAgentRole, SubAgentTask
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry

_FORK_INSTRUCTION = """\
[Fork 模式] 你是一个子工作器。遵守以下规则：
- 不要再创建子工作器（sub_agent 不可用）
- 不要主动对话、不要请求确认、不要问用户问题
- 直接使用工具完成任务，不需要征求许可
- 完成后输出结构化报告，控制在 500 字以内
- 报告格式：## 结果摘要 / ## 关键发现 / ## 文件与代码 / ## 建议"""


class SubAgentRunner:
    """Run a sub-agent to completion in a single call."""

    def __init__(
        self,
        provider: BaseProvider,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        roles: dict[str, SubAgentRole],
    ) -> None:
        self._provider = provider
        self._tool_registry = tool_registry
        self._tool_executor = tool_executor
        self._roles = roles

    async def run(self, task: SubAgentTask, parent_history: ConversationHistory) -> str:
        """Execute a sub-agent task to completion.

        Returns the final result text.
        """
        role = self._roles.get(task.role) if task.role else None
        is_fork = role is None

        # Filter tools
        all_tool_names = [t.name for t in self._tool_registry.list_tools()]
        tool_filter = ToolFilter(role, background=task.background,
                                 parent_tools=all_tool_names)
        allowed_tools = tool_filter.filter(all_tool_names)

        # Build tool definitions (only allowed tools)
        # We need a filtered registry
        filtered_registry = ToolRegistry()
        for t in self._tool_registry.list_tools():
            if t.name in allowed_tools:
                filtered_registry.register(t)

        # Build sub-history
        sub_history = ConversationHistory()

        if is_fork:
            # Fork: inherit parent history
            sub_history._messages = list(parent_history._messages)
            # Append fork instruction as user message
            sub_history.add_user_message(f"{_FORK_INSTRUCTION}\n\n任务: {task.task}")
        else:
            # Defined role: blank conversation
            assert role is not None
            sub_history.add_user_message(f"{role.system_prompt}\n\n任务: {task.task}")

        # Build sub prompt components
        prompt_builder = PromptBuilder()
        prompt_injector = PromptInjector()

        # Sub agent loop
        sub_loop = AgentLoop(
            provider=self._provider,
            tool_registry=filtered_registry,
            tool_executor=self._tool_executor,
            prompt_builder=prompt_builder,
            prompt_injector=prompt_injector,
            max_rounds=role.max_rounds if role else 3,
        )

        final_text = ""
        round_count = 0

        async for event in sub_loop.run(sub_history):
            from mewcode.agent.events import TextDeltaEvent, AgentDoneEvent
            if isinstance(event, TextDeltaEvent):
                final_text += event.text
            elif isinstance(event, AgentDoneEvent):
                break
            round_count += 1

        task.complete(final_text, rounds=round_count)
        return final_text
