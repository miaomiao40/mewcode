"""Tool filter — multi-layer defense against nested sub-agent chains."""

from mewcode.subagent.models import SubAgentRole

# Always blocked in sub-agents (prevents A→B→C chains)
GLOBAL_BLOCKED = {"sub_agent"}

# Background workers get read-only access
BACKGROUND_WHITELIST = {"read_file", "glob", "grep"}
BACKGROUND_EXTRA = {"mcp_resource"}  # optional read-only extras


class ToolFilter:
    """Filters tool availability for sub-agents."""

    def __init__(
        self,
        role: SubAgentRole | None,
        background: bool = False,
        parent_tools: list[str] | None = None,
    ) -> None:
        self._role = role
        self._background = background
        self._parent_tools = parent_tools or []

    def filter(self, tool_names: list[str]) -> list[str]:
        """Return the list of allowed tool names."""
        allowed = set(tool_names)

        # Layer 1: global blocked
        allowed -= GLOBAL_BLOCKED

        # Layer 2: role allow/deny
        if self._role:
            if self._role.tools_allow is not None:
                allowed &= set(self._role.tools_allow)
            allowed -= set(self._role.tools_deny)

        # Layer 3: background workers — read-only
        if self._background:
            allowed &= set(BACKGROUND_WHITELIST) | set(BACKGROUND_EXTRA)

        return sorted(allowed)
