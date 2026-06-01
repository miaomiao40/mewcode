"""Lead agent — orchestrates team: split, assign, merge, synthesize."""

import asyncio
from pathlib import Path

from mewcode.teams.mailbox import Mailbox
from mewcode.teams.member import TeamMember
from mewcode.teams.models import MemberDef, MemberStatus, MessageType, TaskStatus, TeamDef, TeamMessage
from mewcode.teams.tasks import SharedTaskList


class LeadAgent:
    """Orchestrator: decomposes goals, assigns to members, merges results."""

    def __init__(
        self,
        team_def: TeamDef,
        team_dir: Path,
        members: dict[str, TeamMember],
        task_list: SharedTaskList,
        merger,  # GitMerger
    ) -> None:
        self._def = team_def
        self._dir = team_dir
        self._members = members
        self._tasks = task_list
        self._merger = merger
        self._mailbox = Mailbox(team_dir, "lead")
        self._active = True

    # -- public API -----------------------------------------------------------

    async def execute(self, goal: str) -> str:
        """Execute a team goal end-to-end."""
        # 1. Decompose into tasks (members use their own LLM to propose tasks)
        await self._decompose(goal)

        # 2. Dispatch tasks to idle members incrementally
        await self._dispatch_loop()

        # 3. All tasks done — merge worktrees
        merge_results = await self._merge_all()

        # 4. Synthesize final report
        return f"## Team 执行完成\n\n{merge_results}\n\n任务统计: {self._task_summary()}"

    # -- internals ------------------------------------------------------------

    async def _decompose(self, goal: str) -> None:
        """Ask the first available member to propose task breakdown."""
        self._tasks.create(name="root", description=goal)
        # For now: create one task per member (simple decomposition)
        for i, (name, member) in enumerate(self._members.items()):
            self._tasks.create(
                name=f"task-{i+1}",
                description=f"由 {name} 处理: {goal}",
            )

    async def _dispatch_loop(self) -> None:
        """Incrementally dispatch ready tasks to idle members."""
        while self._active:
            ready = self._tasks.ready_tasks()
            idle = [m for m in self._members.values() if m.status == MemberStatus.IDLE]

            for task in ready:
                if not idle:
                    break
                member = idle.pop(0)
                self._tasks.assign(task.id, member.defn.name)
                # Run in background
                asyncio.ensure_future(self._run_member_task(member, task))

            # Check completion
            pending = self._tasks.list_all(TaskStatus.PENDING)
            in_progress = self._tasks.list_all(TaskStatus.IN_PROGRESS)
            if not pending and not in_progress:
                break

            await asyncio.sleep(1.0)

    async def _run_member_task(self, member: TeamMember, task) -> None:
        try:
            result = await member.run(task.description)
            self._tasks.complete(task.id, result)
        except Exception as exc:
            self._tasks.update(task.id, status=TaskStatus.FAILED, result=str(exc))

    async def _merge_all(self) -> str:
        """Incrementally merge each member's worktree."""
        results: list[str] = []
        for name, member in self._members.items():
            wt = member.defn.worktree
            if not wt:
                continue
            branch = f"mewcode/{wt.replace('/', '-')}"
            ok, msg = await self._merger.merge(branch)
            results.append(f"  {name} ({branch}): {msg}")
        return "\n".join(results)

    def _task_summary(self) -> str:
        all_tasks = self._tasks.list_all()
        done = sum(1 for t in all_tasks if t.status == TaskStatus.COMPLETED)
        return f"{done}/{len(all_tasks)} 完成"

    # -- messaging ------------------------------------------------------------

    def send_to_member(self, member_name: str, content: str) -> None:
        msg = TeamMessage(from_member="lead", to_member=member_name,
                          msg_type=MessageType.TEXT, content=content)
        self._mailbox.send(msg)

    def broadcast(self, content: str) -> None:
        msg = TeamMessage(from_member="lead", msg_type=MessageType.BROADCAST,
                          content=content)
        all_names = list(self._members.keys())
        self._mailbox.broadcast(msg, all_names)
