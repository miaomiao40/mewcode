"""Write file tool."""

from pathlib import Path

from mewcode.tools.base import BaseTool, ToolParameter, ToolResult


class WriteFileTool(BaseTool):
    """Write content to a file (creates if not exists)."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "将内容写入文件。如果文件已存在，操作失败并提示。目录不存在时自动创建。"

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter("path", "string", "文件路径，相对于工作目录。"),
            ToolParameter("content", "string", "要写入的完整文本内容。"),
        ]

    async def execute(self, path: str, content: str) -> ToolResult:
        try:
            resolved = self._resolve(path)
        except ValueError as e:
            return ToolResult(success=False, content="", error=str(e))

        if resolved.exists():
            return ToolResult(
                success=False,
                content="",
                error=f"文件已存在: {path}。请使用 edit_file 修改内容，或先删除再写入。",
            )

        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return ToolResult(success=True, content=f"已写入文件: {path} ({len(content)} 字符)")

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            raise ValueError(f"不允许绝对路径: {path}")
        resolved = Path.cwd() / p
        return resolved
