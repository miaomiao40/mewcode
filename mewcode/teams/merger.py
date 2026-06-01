"""Git merger — incremental merge with LLM conflict resolution."""

import asyncio
from pathlib import Path

from mewcode.providers.base import BaseProvider


class GitMerger:
    """Merges worktree branches back to main, using LLM for conflicts."""

    def __init__(self, provider: BaseProvider, repo_root: Path) -> None:
        self._provider = provider
        self._repo_root = repo_root

    async def merge(self, source_branch: str, target_branch: str = "main") -> tuple[bool, str]:
        """Merge *source_branch* into *target_branch*.

        Returns ``(success, message)``.
        """
        # 1. Checkout target
        code, out, err = await self._git("checkout", target_branch)
        if code != 0:
            return False, f"checkout {target_branch} 失败: {err}"

        # 2. Merge source
        code, out, err = await self._git("merge", source_branch, "--no-commit", "--no-ff")
        if code == 0:
            # Clean merge — commit
            await self._git("commit", "-m", f"Merge {source_branch}")
            return True, f"已合并 {source_branch}（无冲突）"

        # 3. Conflicts — use LLM
        conflict_files = await self._get_conflict_files()
        if not conflict_files:
            await self._git("merge", "--abort")
            return False, f"合并冲突但无法定位冲突文件，已回滚"

        resolved = await self._resolve_conflicts(conflict_files)
        if resolved:
            await self._git("add", ".")
            await self._git("commit", "-m", f"Merge {source_branch} (LLM resolved conflicts)")
            return True, f"已合并 {source_branch}（LLM 解决 {len(conflict_files)} 个冲突）"
        else:
            await self._git("merge", "--abort")
            return False, f"合并 {source_branch} 失败：LLM 无法解决冲突，已回滚"

    # -- internals -----------------------------------------------------------

    async def _git(self, *args: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(self._repo_root),
        )
        stdout, stderr = await proc.communicate()
        return (proc.returncode or 0,
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"))

    async def _get_conflict_files(self) -> list[str]:
        code, out, _ = await self._git("diff", "--name-only", "--diff-filter=U")
        if code != 0:
            return []
        return [f for f in out.strip().split("\n") if f]

    async def _resolve_conflicts(self, files: list[str]) -> bool:
        for filepath in files:
            fp = self._repo_root / filepath
            try:
                content = fp.read_text(encoding="utf-8")
            except Exception:
                return False

            # Ask LLM to resolve
            prompt = (
                f"以下是 git merge 冲突文件 '{filepath}'。请输出解决冲突后的完整文件内容。"
                f"只输出最终文件内容，不要加注释或解释。\n\n{content}"
            )
            resolved = ""
            async for token in self._provider.chat_stream(
                [{"role": "user", "content": prompt}],
            ):
                if isinstance(token, str) and not token.startswith("<<"):
                    resolved += token

            if resolved.strip():
                fp.write_text(resolved.strip(), encoding="utf-8")
            else:
                return False
        return True
