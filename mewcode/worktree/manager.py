"""Git worktree manager — create, enter, exit, delete with full lifecycle."""

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any

from mewcode.worktree.models import WorktreeInfo
from mewcode.worktree.validator import name_to_branch, name_to_dirname, validate_name

WORKTREES_DIR = ".mewcode"  # relative to repo root
SESSION_FILE = Path.home() / ".mewcode" / "worktree_session.json"


class GitWorktreeManager:
    """Manages git worktrees for agent isolation."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self._repo_root = (repo_root or self._find_repo_root()).resolve()
        self._worktrees_dir = self._repo_root / WORKTREES_DIR / "worktrees"
        self._active: str = ""  # current worktree name ("" = main)

    # -- public API -----------------------------------------------------------

    async def create(
        self, name: str, branch: str = "", recover: bool = True,
    ) -> tuple[WorktreeInfo | None, str]:
        """Create a new worktree.

        If *recover* is True and the directory already exists, skips git worktree
        creation and reads HEAD directly (fast recovery).
        """
        ok, err = validate_name(name)
        if not ok:
            return None, err

        dir_name = name_to_dirname(name)
        target_path = self._worktrees_dir / dir_name
        branch_name = branch or name_to_branch(name)

        # Fast recovery: directory exists
        if target_path.exists():
            if recover:
                head = self._read_head(target_path)
                info = WorktreeInfo(
                    name=name, path=str(target_path), branch=branch_name,
                    head_commit=head, created_at="recovered",
                )
                return info, ""
            return None, f"目录已存在: {target_path}"

        # Create worktree via git
        target_path.parent.mkdir(parents=True, exist_ok=True)
        code, out, err_msg = await self._git(
            "worktree", "add", str(target_path), "-b", branch_name,
        )
        if code != 0:
            return None, f"git worktree add 失败: {err_msg}"

        head = self._read_head(target_path)
        info = WorktreeInfo(
            name=name, path=str(target_path), branch=branch_name,
            head_commit=head,
        )
        return info, ""

    async def enter(self, name: str) -> tuple[bool, str]:
        """Switch the working directory to a worktree."""
        if name:
            ok, err = validate_name(name)
            if not ok:
                return False, err

        if name:
            dir_name = name_to_dirname(name)
            target_path = self._worktrees_dir / dir_name
            if not target_path.exists():
                return False, f"工作目录不存在: {target_path}"
            os.chdir(str(target_path))
        else:
            # Exit back to main
            session = self._load_session()
            if session and session.original_cwd:
                os.chdir(session.original_cwd)
            else:
                os.chdir(str(self._repo_root))

        self._active = name
        self._save_session(name)
        return True, ""

    async def exit(self, name: str, force: bool = False) -> tuple[bool, str]:
        """Exit a worktree and optionally remove it."""
        if not name:
            return False, "未指定工作目录名"

        dir_name = name_to_dirname(name)
        target_path = self._worktrees_dir / dir_name

        if not target_path.exists():
            return False, f"工作目录不存在: {target_path}"

        # Change protection: check for uncommitted changes
        if not force:
            has_changes = await self._has_changes(target_path)
            if has_changes:
                return False, (
                    f"工作目录 '{name}' 有未提交的修改。"
                    f"使用 /worktree exit {name} --force 强制退出（修改将保留在工作目录中）。"
                )

        # Switch back to main repo
        await self.enter("")

        # Remove worktree (keep directory if changes exist)
        branch_name = name_to_branch(name)
        await self._git("worktree", "remove", str(target_path), "--force")
        await self._git("branch", "-D", branch_name)  # best-effort

        self._active = ""
        self._save_session("")
        return True, ""

    async def list_worktrees(self) -> list[WorktreeInfo]:
        """List all managed worktrees."""
        code, out, _ = await self._git("worktree", "list", "--porcelain")
        if code != 0:
            return []

        results: list[WorktreeInfo] = []
        for block in out.strip().split("\n\n"):
            if not block:
                continue
            info = self._parse_porcelain(block)
            if info and str(self._worktrees_dir) in info.path:
                results.append(info)
        return results

    async def status(self, name: str = "") -> WorktreeInfo | None:
        """Get status of a worktree (or the active one)."""
        if not name:
            name = self._active
        if not name:
            return None

        dir_name = name_to_dirname(name)
        target_path = self._worktrees_dir / dir_name
        if not target_path.exists():
            return None

        head = self._read_head(target_path)
        has_changes = await self._has_changes(target_path)
        return WorktreeInfo(
            name=name, path=str(target_path),
            branch=name_to_branch(name), head_commit=head,
            is_active=(name == self._active), has_changes=has_changes,
        )

    # -- cleanup --------------------------------------------------------------

    async def remove_stale(self, max_age_hours: int = 24) -> list[str]:
        """Remove worktrees older than *max_age_hours* with no changes."""
        removed: list[str] = []
        worktrees = await self.list_worktrees()
        for wt in worktrees:
            if wt.is_active:
                continue
            if wt.has_changes:
                continue  # fail-closed: don't remove dirty worktrees
            # Check branch pattern
            if not wt.branch.startswith("mewcode/"):
                continue
            await self._git("worktree", "remove", wt.path, "--force")
            await self._git("branch", "-D", wt.branch)
            removed.append(wt.name)
        return removed

    # -- helpers --------------------------------------------------------------

    @property
    def active(self) -> str:
        return self._active

    @staticmethod
    def _find_repo_root() -> Path:
        """Walk up from cwd to find the git repo root."""
        d = Path.cwd()
        while d != d.parent:
            if (d / ".git").exists():
                return d
            d = d.parent
        return Path.cwd()

    @staticmethod
    def _read_head(path: Path) -> str:
        head_file = path / ".git"
        if head_file.is_file():
            # worktree .git is a file pointing to the main repo
            git_dir = Path(head_file.read_text().strip().split(": ")[-1])
            head_file = git_dir / "HEAD"
        else:
            head_file = head_file / "HEAD"
        try:
            return head_file.read_text().strip()
        except Exception:
            return ""

    async def _has_changes(self, path: Path) -> bool:
        code, out, _ = await self._git("-C", str(path), "status", "--porcelain")
        return code == 0 and bool(out.strip())

    async def _git(self, *args: str) -> tuple[int, str, str]:
        cmd = ["git", *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=str(self._repo_root),
            )
            stdout, stderr = await proc.communicate()
            return (proc.returncode or 0,
                    stdout.decode("utf-8", errors="replace"),
                    stderr.decode("utf-8", errors="replace"))
        except Exception as exc:
            return (-1, "", str(exc))

    def _parse_porcelain(self, block: str) -> WorktreeInfo | None:
        info: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith("worktree "):
                info["path"] = line[9:]
            elif line.startswith("HEAD "):
                info["head"] = line[5:]
            elif line.startswith("branch "):
                info["branch"] = line[19:]  # refs/heads/xxx
        if "path" not in info:
            return None
        branch = info.get("branch", "").replace("refs/heads/", "")
        path = info["path"]
        name = Path(path).name.replace("-", "/")  # reverse dirname conversion
        return WorktreeInfo(
            name=name, path=path, branch=branch,
            head_commit=info.get("head", ""),
        )

    # -- session persistence --------------------------------------------------

    def _save_session(self, name: str) -> None:
        import json
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        session = {
            "active_worktree": name,
            "original_cwd": str(self._repo_root) if not name else str(Path.cwd()),
        }
        SESSION_FILE.write_text(json.dumps(session, indent=2), encoding="utf-8")

    def _load_session(self) -> dict | None:
        import json
        if SESSION_FILE.exists():
            try:
                return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return None
