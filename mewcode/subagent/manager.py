"""Background task manager — track, notify, manage sub-agent tasks."""

import asyncio
from datetime import datetime, timezone

from mewcode.subagent.models import SubAgentTask, TaskStatus


class BackgroundTaskManager:
    """Tracks background sub-agent tasks and injects results on completion."""

    def __init__(self) -> None:
        self._tasks: dict[str, SubAgentTask] = {}

    def create(self, role: str | None, task_text: str, background: bool = False) -> SubAgentTask:
        task = SubAgentTask(role=role, task=task_text, background=background)
        self._tasks[task.id] = task
        return task

    def list_tasks(self) -> list[SubAgentTask]:
        return list(self._tasks.values())

    def get(self, task_id: str) -> SubAgentTask | None:
        return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status in (TaskStatus.QUEUED, TaskStatus.RUNNING):
            task.cancel()
            return True
        return False

    def inject_result(self, task: SubAgentTask, history) -> None:
        """Inject a completed task's result into the main conversation.

        Injected as a tool-role message so the main Agent sees it as the
        sub_agent tool's return value.
        """
        if task.status == TaskStatus.COMPLETED:
            content = f"[Sub-agent '{task.role or 'fork'}' ({task.id}) 完成]\n{task.result}"
        elif task.status == TaskStatus.FAILED:
            content = f"[Sub-agent '{task.role or 'fork'}' ({task.id}) 失败]\n{task.result}"
        else:
            content = f"[Sub-agent '{task.role or 'fork'}' ({task.id}) 已取消]"

        history.add_raw_message({
            "role": "tool",
            "tool_call_id": f"sub_{task.id}",
            "name": "sub_agent",
            "content": content,
        })

    def get_status_summary(self) -> str:
        """Return a human-readable summary of all tasks."""
        if not self._tasks:
            return "没有后台任务"
        lines = ["后台任务:"]
        for t in sorted(self._tasks.values(), key=lambda x: x.started_at or "", reverse=True):
            status_icon = {
                TaskStatus.QUEUED: "⏳", TaskStatus.RUNNING: "🔄",
                TaskStatus.COMPLETED: "✅", TaskStatus.FAILED: "❌",
                TaskStatus.CANCELLED: "🚫",
            }.get(t.status, "❓")
            role = t.role or "fork"
            lines.append(f"  {status_icon} {t.id}  {role}  {t.task[:60]}")
        return "\n".join(lines)
