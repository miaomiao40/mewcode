"""Read file tool."""

from pathlib import Path

from mewcode.tools.base import BaseTool, ToolCategory, ToolParameter, ToolResult


class ReadFileTool(BaseTool):
    """Read the contents of a file."""

    _allowed_encodings = ("utf-8", "gbk", "latin-1")

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "读取指定文件的内容。返回文件文本。"

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.READ

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter("path", "string", "文件路径，相对于工作目录。"),
        ]

    async def execute(self, path: str) -> ToolResult:
        try:
            resolved = self._resolve(path)
        except ValueError as e:
            return ToolResult(success=False, content="", error=str(e))

        if not resolved.exists():
            return ToolResult(success=False, content="", error=f"文件不存在: {path}")
        if not resolved.is_file():
            return ToolResult(success=False, content="", error=f"路径不是文件: {path}")

        for enc in self._allowed_encodings:
            try:
                text = resolved.read_text(encoding=enc)
                return ToolResult(success=True, content=text)
            except UnicodeDecodeError:
                continue

        return ToolResult(
            success=False,
            content="",
            error=f"无法解码文件（尝试了 {', '.join(self._allowed_encodings)}）: {path}",
        )

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            raise ValueError(f"不允许绝对路径: {path}")
        resolved = Path.cwd() / p
        # Prevent path traversal
        try:
            resolved.resolve(strict=False)
        except Exception:
            raise ValueError(f"无效路径: {path}")
        if ".." in resolved.parts[len(Path.cwd().parts):]:
            raise ValueError(f"路径遍历不被允许: {path}")
        return resolved
