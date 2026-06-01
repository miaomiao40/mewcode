"""Glob tool — find files by pattern."""

from pathlib import Path

from mewcode.tools.base import BaseTool, ToolCategory, ToolParameter, ToolResult

MAX_RESULTS = 50


class GlobTool(BaseTool):
    """Find files matching a glob pattern."""

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return "按 glob 模式查找文件。返回匹配的文件路径列表。最多返回 50 条。"

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.READ

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter("pattern", "string", "Glob 模式，如 '**/*.py' 或 'src/**/*.ts'。"),
        ]

    async def execute(self, pattern: str) -> ToolResult:
        cwd = Path.cwd()
        try:
            matches = sorted(cwd.glob(pattern))
        except Exception as exc:
            return ToolResult(
                success=False, content="", error=f"Glob 模式无效: {exc}"
            )

        if not matches:
            return ToolResult(success=True, content="(无匹配文件)")

        truncated = len(matches) > MAX_RESULTS
        matches = matches[:MAX_RESULTS]

        lines = []
        for m in matches:
            rel = m.relative_to(cwd) if m.is_relative_to(cwd) else m
            lines.append(str(rel))

        summary = (
            f"找到 {len(matches)} 个匹配（已截断到前 {MAX_RESULTS} 条）\n"
            if truncated
            else f"找到 {len(matches)} 个匹配\n"
        )
        return ToolResult(success=True, content=summary + "\n".join(lines))
