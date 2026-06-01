"""Shared task list — create, view, list, update with dependency support."""

import json
from datetime import datetime, timezone
from pathlib import Path

from mewcode.teams.models import TaskStatus, TeamTask


class SharedTaskList:
    """Persistent task list for a team, stored as JSON."""

    def __init__(self, team_dir: Path) -> None:
        self._file = team_dir / "tasks.json"
        self._tasks: dict[str, TeamTask] = {}
        self._load()

    # -- CRUD ----------------------------------------------------------------

    def create(self, name: str, description: str = "",
               depends_on: list[str] | None = None) -> TeamTask:
        task = TeamTask(name=name, description=description,
                        depends_on=depends_on or [])
        self._tasks[task.id] = task
        self._save()
        return task

    def get(self, task_id: str) -> TeamTask | None:
        return self._tasks.get(task_id)

    def list_all(self, status: TaskStatus | None = None) -> list[TeamTask]:
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return sorted(tasks, key=lambda t: t.created_at)

    def update(self, task_id: str, **kwargs) -> TeamTask | None:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        for k, v in kwargs.items():
            if hasattr(task, k):
                setattr(task, k, v)
        task.updated_at = datetime.now(timezone.utc).isoformat()
        self._save()
        return task

    def assign(self, task_id: str, member_name: str) -> TeamTask | None:
        return self.update(task_id, assigned_to=member_name,
                           status=TaskStatus.IN_PROGRESS)

    def complete(self, task_id: str, result: str = "") -> TeamTask | None:
        return self.update(task_id, status=TaskStatus.COMPLETED, result=result)

    def ready_tasks(self) -> list[TeamTask]:
        """Tasks whose dependencies are all completed and are unassigned."""
        ready: list[TeamTask] = []
        for t in self._tasks.values():
            if t.status != TaskStatus.PENDING:
                continue
            if t.assigned_to:
                continue
            deps_met = all(
                self._tasks.get(d) and self._tasks[d].status == TaskStatus.COMPLETED
                for d in t.depends_on
            )
            if deps_met:
                ready.append(t)
        return ready

    # -- persistence ---------------------------------------------------------

    def _save(self) -> None:
        data = {
            tid: {
                "id": t.id, "name": t.name, "description": t.description,
                "assigned_to": t.assigned_to, "depends_on": t.depends_on,
                "status": t.status.value, "result": t.result,
                "created_at": t.created_at, "updated_at": t.updated_at,
            }
            for tid, t in self._tasks.items()
        }
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    def _load(self) -> None:
        if not self._file.exists():
            return
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            for tid, d in data.items():
                self._tasks[tid] = TeamTask(
                    id=d.get("id", tid), name=d.get("name", ""),
                    description=d.get("description", ""),
                    assigned_to=d.get("assigned_to", ""),
                    depends_on=d.get("depends_on", []),
                    status=TaskStatus(d.get("status", "pending")),
                    result=d.get("result", ""),
                    created_at=d.get("created_at", ""),
                    updated_at=d.get("updated_at", ""),
                )
        except (json.JSONDecodeError, KeyError):
            pass
