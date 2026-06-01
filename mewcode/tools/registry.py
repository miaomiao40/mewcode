"""Tool registry — central catalog of available tools."""

from mewcode.tools.base import BaseTool


class ToolRegistry:
    """Registers tools and provides lookups and API-format conversion."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Add a tool to the registry."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def to_openai_format(self) -> list[dict]:
        """Return tool definitions in OpenAI tool-calling format."""
        return [t.to_openai_schema() for t in self._tools.values()]

    def to_anthropic_format(self) -> list[dict]:
        """Return tool definitions in Anthropic tool-use format."""
        return [t.to_anthropic_schema() for t in self._tools.values()]
