"""Background cleaner — periodically removes expired worktree directories."""

import asyncio

from mewcode.worktree.manager import GitWorktreeManager

CLEANUP_INTERVAL_SECONDS = 300  # 5 minutes


class BackgroundCleaner:
    """Periodic background cleanup of stale worktrees."""

    def __init__(self, manager: GitWorktreeManager, max_age_hours: int = 24) -> None:
        self._manager = manager
        self._max_age_hours = max_age_hours
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            try:
                removed = await self._manager.remove_stale(self._max_age_hours)
            except Exception:
                pass  # fail silently — never interrupt the main loop
