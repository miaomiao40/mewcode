"""Team collaboration tools — only visible to team members, not main agent."""

from mewcode.teams.mailbox import Mailbox
from mewcode.teams.models import MessageType, TaskStatus, TeamMessage
from mewcode.teams.tasks import SharedTaskList
from mewcode.tools.base import BaseTool, ToolCategory, ToolParameter, ToolResult


def create_team_tools(team_dir, task_list: SharedTaskList,
                      mailbox: Mailbox, member_name: str,
                      all_members: list[str]) -> list[BaseTool]:
    """Create the collaboration tool set for a team member."""
    return [
        _CreateTaskTool(task_list),
        _ListTasksTool(task_list),
        _ViewTaskTool(task_list),
        _UpdateTaskTool(task_list),
        _SendMessageTool(mailbox, member_name),
        _BroadcastTool(mailbox, member_name, all_members),
    ]


class _CreateTaskTool(BaseTool):
    def __init__(self, tasks: SharedTaskList): self._tasks = tasks
    name = property(lambda s: "team_create_task")
    description = property(lambda s: "在共享任务清单中创建新任务。可指定依赖的其他任务ID。")
    category = property(lambda s: ToolCategory.WRITE)
    parameters = property(lambda s: [
        ToolParameter("name", "string", "任务名称"),
        ToolParameter("description", "string", "任务描述"),
        ToolParameter("depends_on", "string", "逗号分隔的依赖任务ID列表", required=False),
    ])
    async def execute(self, name: str, description: str, depends_on: str = "") -> ToolResult:
        deps = [d.strip() for d in depends_on.split(",") if d.strip()] if depends_on else []
        task = self._tasks.create(name, description, deps)
        return ToolResult(success=True, content=f"任务已创建: {task.id} ({name})")


class _ListTasksTool(BaseTool):
    def __init__(self, tasks: SharedTaskList): self._tasks = tasks
    name = property(lambda s: "team_list_tasks")
    description = property(lambda s: "列出共享任务清单中的所有任务。")
    category = property(lambda s: ToolCategory.READ)
    parameters = property(lambda s: [])
    async def execute(self) -> ToolResult:
        tasks = self._tasks.list_all()
        if not tasks:
            return ToolResult(success=True, content="(无任务)")
        lines = ["任务清单:"]
        for t in tasks:
            status_icon = {"pending": "⏳", "in_progress": "🔄", "completed": "✅", "failed": "❌"}.get(t.status.value, "❓")
            lines.append(f"  {status_icon} [{t.id}] {t.name} → {t.assigned_to or '未分配'} ({t.status.value})")
        return ToolResult(success=True, content="\n".join(lines))


class _ViewTaskTool(BaseTool):
    def __init__(self, tasks: SharedTaskList): self._tasks = tasks
    name = property(lambda s: "team_view_task")
    description = property(lambda s: "查看指定任务的详细信息。")
    category = property(lambda s: ToolCategory.READ)
    parameters = property(lambda s: [ToolParameter("task_id", "string", "任务ID")])
    async def execute(self, task_id: str) -> ToolResult:
        t = self._tasks.get(task_id)
        if t is None:
            return ToolResult(success=False, content="", error=f"任务不存在: {task_id}")
        return ToolResult(success=True, content=(
            f"任务: {t.id}\n名称: {t.name}\n描述: {t.description}\n"
            f"状态: {t.status.value}\n分配: {t.assigned_to or '未分配'}\n"
            f"依赖: {', '.join(t.depends_on) if t.depends_on else '无'}\n"
            f"结果: {t.result or '(无)'}"
        ))


class _UpdateTaskTool(BaseTool):
    def __init__(self, tasks: SharedTaskList): self._tasks = tasks
    name = property(lambda s: "team_update_task")
    description = property(lambda s: "更新任务状态或结果。")
    category = property(lambda s: ToolCategory.WRITE)
    parameters = property(lambda s: [
        ToolParameter("task_id", "string", "任务ID"),
        ToolParameter("status", "string", "新状态: pending/in_progress/completed/failed"),
        ToolParameter("result", "string", "任务结果文本", required=False),
    ])
    async def execute(self, task_id: str, status: str, result: str = "") -> ToolResult:
        try:
            st = TaskStatus(status)
        except ValueError:
            return ToolResult(success=False, content="", error=f"无效状态: {status}")
        t = self._tasks.update(task_id, status=st, result=result)
        if t is None:
            return ToolResult(success=False, content="", error=f"任务不存在: {task_id}")
        return ToolResult(success=True, content=f"任务 {task_id} 已更新为 {status}")


class _SendMessageTool(BaseTool):
    def __init__(self, mailbox: Mailbox, sender: str):
        self._mailbox = mailbox; self._sender = sender
    name = property(lambda s: "team_send_message")
    description = property(lambda s: "向指定成员发送点对点消息。")
    category = property(lambda s: ToolCategory.WRITE)
    parameters = property(lambda s: [
        ToolParameter("to", "string", "接收者名称"),
        ToolParameter("content", "string", "消息内容"),
    ])
    async def execute(self, to: str, content: str) -> ToolResult:
        msg = TeamMessage(from_member=self._sender, to_member=to,
                          msg_type=MessageType.TEXT, content=content)
        self._mailbox.send(msg)
        return ToolResult(success=True, content=f"消息已发送给 {to}")


class _BroadcastTool(BaseTool):
    def __init__(self, mailbox: Mailbox, sender: str, all_members: list[str]):
        self._mailbox = mailbox; self._sender = sender; self._all = all_members
    name = property(lambda s: "team_broadcast")
    description = property(lambda s: "向所有团队成员广播消息。")
    category = property(lambda s: ToolCategory.WRITE)
    parameters = property(lambda s: [
        ToolParameter("content", "string", "广播内容"),
    ])
    async def execute(self, content: str) -> ToolResult:
        msg = TeamMessage(from_member=self._sender, msg_type=MessageType.BROADCAST, content=content)
        self._mailbox.broadcast(msg, self._all)
        return ToolResult(success=True, content=f"已广播给 {len(self._all)-1} 位成员")
