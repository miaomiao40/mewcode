"""Instructions loader — reads MEWCODE.md files with @include support."""

import re
from pathlib import Path

MAX_INCLUDE_DEPTH = 3
_INCLUDE_RE = re.compile(r'^@include\((.+)\)$', re.MULTILINE)


class InstructionsLoader:
    """Loads project + user instruction files, resolving @include directives.

    Priority: project-level (``MEWCODE.md`` in cwd) first, then user-level
    (``~/.mewcode/instructions.md``) — higher priority = first in output.
    """

    def load(self, cwd: Path | None = None) -> str:
        cwd = (cwd or Path.cwd()).resolve()
        parts: list[str] = []

        project_file = cwd / "MEWCODE.md"
        if project_file.exists():
            parts.append(self._load_with_includes(project_file, depth=0))

        user_file = Path.home() / ".mewcode" / "instructions.md"
        if user_file.exists():
            parts.append(self._load_with_includes(user_file, depth=0))

        return "\n\n".join(parts)

    def load_project(self, cwd: Path | None = None) -> str:
        cwd = (cwd or Path.cwd()).resolve()
        project_file = cwd / "MEWCODE.md"
        if project_file.exists():
            return self._load_with_includes(project_file, depth=0)
        return ""

    def load_user(self) -> str:
        user_file = Path.home() / ".mewcode" / "instructions.md"
        if user_file.exists():
            return self._load_with_includes(user_file, depth=0)
        return ""

    # -- internals -----------------------------------------------------------

    def _load_with_includes(self, file_path: Path, depth: int) -> str:
        if depth > MAX_INCLUDE_DEPTH:
            raise ValueError(
                f"@include 嵌套深度超过 {MAX_INCLUDE_DEPTH} 层: {file_path}"
            )
        content = file_path.read_text(encoding="utf-8")
        base_dir = file_path.parent.resolve()

        def _resolve_include(match: re.Match) -> str:
            include_path = match.group(1).strip()
            full_path = (base_dir / include_path).resolve()
            # Block escaping project/user dirs
            try:
                full_path.relative_to(base_dir)
            except ValueError:
                # Also allow user home dir includes from user instructions
                home = Path.home()
                try:
                    full_path.relative_to(home)
                except ValueError:
                    raise ValueError(f"@include 路径越界: {include_path}")
            if not full_path.exists():
                raise ValueError(f"@include 文件不存在: {include_path}")
            return self._load_with_includes(full_path, depth + 1)

        return _INCLUDE_RE.sub(_resolve_include, content)
