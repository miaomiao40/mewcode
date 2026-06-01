"""Auto-note manager — periodic LLM-driven note updates."""

import asyncio
from pathlib import Path

from mewcode.notes.categories import (
    PROJECT_CATEGORIES,
    USER_CATEGORIES,
    build_note_prompt,
    get_project_notes_dir,
    get_user_notes_dir,
)
from mewcode.providers.base import BaseProvider


class AutoNoteManager:
    """Updates notes every N rounds using the LLM."""

    def __init__(
        self,
        provider: BaseProvider,
        interval: int = 5,
        cwd: Path | None = None,
    ) -> None:
        self._provider = provider
        self._interval = interval
        self._cwd = (cwd or Path.cwd()).resolve()
        self._round_counter = 0
        self._recent_text: list[str] = []

        # Ensure directories exist
        get_user_notes_dir().mkdir(parents=True, exist_ok=True)
        get_project_notes_dir(self._cwd).mkdir(parents=True, exist_ok=True)

    # -- public API -----------------------------------------------------------

    def record_round(self, user_msg: str, assistant_msg: str) -> None:
        """Record a completed round for future note updates."""
        self._round_counter += 1
        self._recent_text.append(f"[user]: {user_msg}")
        self._recent_text.append(f"[assistant]: {assistant_msg}")
        # Keep only recent windows
        if len(self._recent_text) > 30:
            self._recent_text = self._recent_text[-30:]

    def should_update(self) -> bool:
        return self._round_counter > 0 and self._round_counter % self._interval == 0

    async def update_all(self) -> dict[str, str]:
        """Update both user and project notes. Returns {file_path: new_content}."""
        results: dict[str, str] = {}
        recent = "\n".join(self._recent_text)

        # Update user notes
        for category, filename in USER_CATEGORIES.items():
            file_path = get_user_notes_dir() / filename
            new_content = await self._update_one(file_path, category, recent)
            if new_content is not None:
                results[str(file_path)] = new_content

        # Update project notes
        for category, filename in PROJECT_CATEGORIES.items():
            file_path = get_project_notes_dir(self._cwd) / filename
            new_content = await self._update_one(file_path, category, recent)
            if new_content is not None:
                results[str(file_path)] = new_content

        self._recent_text.clear()
        return results

    async def update_on_exit(self) -> dict[str, str]:
        """Force a final note update before shutdown."""
        self._round_counter = self._interval  # force should_update
        return await self.update_all()

    # -- read / clear ---------------------------------------------------------

    def read_note(self, category: str) -> str:
        """Read a specific note file."""
        all_cats = {**USER_CATEGORIES, **PROJECT_CATEGORIES}
        filename = all_cats.get(category)
        if not filename:
            return f"未知分类: {category}"

        # Check user dir first, then project dir
        for base in [get_user_notes_dir(), get_project_notes_dir(self._cwd)]:
            fp = base / filename
            if fp.exists():
                return fp.read_text(encoding="utf-8")
        return "(空)"

    def clear_note(self, category: str) -> str:
        """Clear a note file."""
        all_cats = {**USER_CATEGORIES, **PROJECT_CATEGORIES}
        filename = all_cats.get(category)
        if not filename:
            return f"未知分类: {category}"
        for base in [get_user_notes_dir(), get_project_notes_dir(self._cwd)]:
            fp = base / filename
            if fp.exists():
                fp.write_text("", encoding="utf-8")
        return f"已清空: {category}"

    def get_note_path(self, category: str) -> str | None:
        """Return the file path for a category (for user editing)."""
        all_cats = {**USER_CATEGORIES, **PROJECT_CATEGORIES}
        filename = all_cats.get(category)
        if not filename:
            return None
        for base in [get_user_notes_dir(), get_project_notes_dir(self._cwd)]:
            fp = base / filename
            return str(fp)
        return None

    # -- internals ------------------------------------------------------------

    async def _update_one(
        self, file_path: Path, category: str, recent_text: str,
    ) -> str | None:
        current = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        prompt = build_note_prompt(current, recent_text)

        try:
            new_content = ""
            async for token in self._provider.chat_stream(
                [{"role": "user", "content": prompt}],
            ):
                if isinstance(token, str) and not token.startswith("<<"):
                    new_content += token
            if new_content.strip():
                file_path.write_text(new_content.strip() + "\n", encoding="utf-8")
                return new_content.strip()
        except Exception:
            pass
        return None
