"""Grep tool — search for a pattern in file contents."""

import re
from pathlib import Path

from mewcode.tools.base import BaseTool, ToolCategory, ToolParameter, ToolResult

MAX_RESULTS = 50
SNIPPET_LENGTH = 300  # max chars of context per match


class GrepTool(BaseTool):
    """Search file contents for a regex pattern."""

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return "在文件内容中搜索正则表达式。返回文件名和匹配行。最多 50 条。"

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.READ

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter("pattern", "string", "正则表达式，如 'def main' 或 'import.*os'。"),
        ]

    async def execute(self, pattern: str) -> ToolResult:
        cwd = Path.cwd()
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return ToolResult(
                success=False, content="", error=f"正则表达式无效: {exc}"
            )

        results: list[str] = []
        truncated = False

        # Walk all files (skip common binary/dot dirs)
        skip_dirs = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv"}
        for file_path in cwd.rglob("*"):
            if file_path.is_dir():
                continue
            # Skip hidden and binary-looking
            if any(part.startswith(".") for part in file_path.parts[len(cwd.parts):]):
                continue
            if any(d in file_path.parts for d in skip_dirs):
                continue
            suffix = file_path.suffix.lower()
            if suffix in {".pyc", ".pyo", ".exe", ".dll", ".so", ".o", ".bin", ".jpg", ".png", ".pdf"}:
                continue

            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            for line_no, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    rel = file_path.relative_to(cwd) if file_path.is_relative_to(cwd) else file_path
                    snippet = line[:SNIPPET_LENGTH]
                    results.append(f"{rel}:{line_no}: {snippet}")
                    if len(results) >= MAX_RESULTS:
                        truncated = True
                        break
            if truncated:
                break

        if not results:
            return ToolResult(success=True, content="(无匹配)")

        header = f"找到 {len(results)} 条匹配"
        if truncated:
            header += f"（已截断到前 {MAX_RESULTS} 条）"
        return ToolResult(success=True, content=header + "\n" + "\n".join(results))
