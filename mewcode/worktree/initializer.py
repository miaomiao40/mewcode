"""Worktree environment initializer — copy configs, symlink deps, hooks."""

import os
import shutil
from pathlib import Path


#: Files to copy from repo root to worktree
_COPY_FILES = [
    "settings.local.json",
    ".mewcode.yaml",
    ".mewcode-security.yaml",
    ".mewcode-hooks.yaml",
    ".mewcode-mcp.yaml",
]

#: Large dependency directories to try symlinking
_SYMLINK_DIRS = ["node_modules", ".venv", "venv", "__pycache__"]

#: Gitignored file patterns to copy (best-effort)
_COPY_GITIGNORED_PATTERNS = ["*.env", ".env.*"]


class WorktreeInitializer:
    """Sets up a newly created worktree for use."""

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def initialize(self, worktree_path: Path, symlink_dirs: list[str] | None = None) -> list[str]:
        """Initialize a worktree. Returns log messages."""
        logs: list[str] = []

        # Copy config files
        for filename in _COPY_FILES:
            src = self._repo_root / filename
            dst = worktree_path / filename
            if src.exists() and not dst.exists():
                try:
                    shutil.copy2(str(src), str(dst))
                    logs.append(f"复制: {filename}")
                except OSError as exc:
                    logs.append(f"复制失败 {filename}: {exc}")

        # Symlink dependency dirs
        for dirname in (symlink_dirs or _SYMLINK_DIRS):
            src = self._repo_root / dirname
            dst = worktree_path / dirname
            if src.is_dir() and not dst.exists():
                try:
                    if hasattr(os, "symlink"):
                        os.symlink(str(src), str(dst), target_is_directory=True)
                    else:
                        # Windows fallback: junction
                        import subprocess
                        subprocess.run(
                            ["mklink", "/J", str(dst), str(src)],
                            shell=True, check=False,
                        )
                    logs.append(f"链接: {dirname}")
                except OSError as exc:
                    logs.append(f"链接失败 {dirname}: {exc}")

        return logs
