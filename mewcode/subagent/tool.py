"""Sub-agent tool — the single sub_agent entry point."""

import asyncio

from mewcode.conversation.history import ConversationHistory
from mewcode.subagent.manager import BackgroundTaskManager
from mewcode.subagent.models import SubAgentRole
from mewcode.subagent.runner import SubAgentRunner
from mewcode.tools.base import BaseTool, ToolCategory, ToolParameter, ToolResult


class SubAgentTool(BaseTool):
    """Single tool for creating sub-agents by role or fork."""

    def __init__(
        self,
        runner: SubAgentRunner,
        task_manager: BackgroundTaskManager,
        roles: dict[str, SubAgentRole],
        history: ConversationHistory,
    ) -> None:
        self._runner = runner
        self._task_manager = task_manager
        self._roles = roles
        self._history = history

    @property
    def name(self) -> str:
        return "sub_agent"

    @property
    def description(self) -> str:
        role_list = ", ".join(self._roles.keys()) if self._roles else "fork"
        return (
            "创建一个子工作器执行任务。可用角色: "
            f"{role_list}（或省略 role 使用 fork 模式继承当前对话）。"
            "后台运行: background=true。"
        )

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.WRITE

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter("task", "string", "要执行的任务描述"),
            ToolParameter("role", "string", "预定义角色名，省略则使用 fork 模式", required=False),
            ToolParameter("background", "boolean", "是否后台运行（fork 模式强制后台）", required=False),
        ]

    async def execute(
        self,
        task: str,
        role: str = "",
        background: bool = False,
    ) -> ToolResult:
        role_name = role.strip() if role else None
        is_fork = role_name is None

        # Fork mode: force background
        if is_fork:
            background = True

        # Validate role
        if role_name and role_name not in self._roles:
            available = ", ".join(self._roles.keys())
            return ToolResult(
                success=False, content="",
                error=f"未知角色: {role_name}。可用: {available}",
            )

        # Create task
        sub_task = self._task_manager.create(role_name, task, background=background)

        if background:
            # Fire and forget — will inject result when done
            asyncio.ensure_future(self._run_background(sub_task))
            return ToolResult(
                success=True,
                content=f"后台任务 {sub_task.id} 已启动（角色: {role_name or 'fork'}）。使用 /tasks 查看状态。",
            )
        else:
            # Synchronous execution
            sub_task.start()
            try:
                result_text = await self._runner.run(sub_task, self._history)
                return ToolResult(success=True, content=result_text)
            except Exception as exc:
                sub_task.fail(str(exc))
                return ToolResult(success=False, content="", error=str(exc))

    async def _run_background(self, task) -> None:
        """Run a task in background, injecting the result on completion."""
        task.start()
        try:
            await self._runner.run(task, self._history)
        except Exception as exc:
            task.fail(str(exc))
        # Inject result into main conversation
        self._task_manager.inject_result(task, self._history)
