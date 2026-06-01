"""Edit file tool — exact-match replacement."""

from pathlib import Path

from mewcode.tools.base import BaseTool, ToolParameter, ToolResult


class EditFileTool(BaseTool):
    """Replace a unique string in a file with another string."""

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "精确替换文件中的某段文本。old_string 必须在文件中恰好出现一次，"
            "否则操作失败。匹配时区分大小写，不忽略空白。"
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter("path", "string", "文件路径，相对于工作目录。"),
            ToolParameter("old_string", "string", "要替换的原文。必须与文件中内容逐字符完全匹配。"),
            ToolParameter("new_string", "string", "替换后的新文本。"),
        ]

    async def execute(self, path: str, old_string: str, new_string: str) -> ToolResult:
        try:
            resolved = self._resolve(path)
        except ValueError as e:
            return ToolResult(success=False, content="", error=str(e))

        if not resolved.exists():
            return ToolResult(success=False, content="", error=f"文件不存在: {path}")
        if not resolved.is_file():
            return ToolResult(success=False, content="", error=f"路径不是文件: {path}")

        original = resolved.read_text(encoding="utf-8")
        count = original.count(old_string)

        if count == 0:
            return ToolResult(
                success=False,
                content="",
                error=(
                    f"未找到匹配的原文。请确认 old_string 与文件中的文本逐字符一致"
                    f"（包括空白和换行）。文件内容预览（前 500 字符）:\n{original[:500]}"
                ),
            )
        if count > 1:
            return ToolResult(
                success=False,
                content="",
                error=(
                    f"找到 {count} 处匹配，old_string 必须在文件中只出现一次。"
                    f"请提供足够长的上下文以确保唯一性。"
                ),
            )

        new_content = original.replace(old_string, new_string, 1)
        resolved.write_text(new_content, encoding="utf-8")
        return ToolResult(
            success=True,
            content=f"已编辑文件: {path}（替换了 1 处）",
        )

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            raise ValueError(f"不允许绝对路径: {path}")
        return Path.cwd() / p
