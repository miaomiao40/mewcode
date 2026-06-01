"""Abstract base provider, factory function, and shared types."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from mewcode.config.models import ProviderConfig

#: A single chat message in provider-neutral format.
#: Values can be str, list[dict], or None (for tool messages).
Message = dict[str, Any]


@dataclass
class ToolCall:
    """A tool invocation requested by the model."""

    id: str
    name: str
    input: dict[str, Any]


class BaseProvider(ABC):
    """Abstract interface for an LLM provider backend."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system_blocks: list[dict] | None = None,
    ) -> AsyncIterator[str | ToolCall]:
        """Send messages and yield tokens or tool calls as they arrive via SSE.

        Args:
            messages: Ordered list of chat messages.
            tools: Optional tool definitions in provider-native format.
            system_blocks: Optional Anthropic-format system content blocks.

        Yields:
            Token strings (``str``) or ``ToolCall`` objects.
        """
        ...

    def supports_thinking(self) -> bool:
        """Whether this provider supports extended thinking."""
        return False

    # -- tool result formatting (provider-specific) ---------------------------

    def make_tool_calls_message(
        self, tool_calls: list[ToolCall], text_prefix: str = ""
    ) -> Message:
        """Create a single assistant message carrying one or more tool calls.

        Includes optional preceding text so the model's response is one turn.
        """
        raise NotImplementedError

    def make_tool_result_message(
        self, tool_call_id: str, tool_name: str, result_text: str
    ) -> Message:
        """Create a message carrying the tool execution result.

        The result is appended after the tool call message and before the
        follow-up model response.
        """
        raise NotImplementedError


def create_provider(config: ProviderConfig) -> BaseProvider:
    """Factory: instantiate the correct provider subclass for the given config."""
    if config.protocol == "anthropic":
        from mewcode.providers.anthropic import AnthropicProvider

        return AnthropicProvider(config)

    if config.protocol == "openai":
        from mewcode.providers.openai import OpenAIProvider

        return OpenAIProvider(config)

    if config.protocol == "deepseek":
        from mewcode.providers.deepseek import DeepSeekProvider

        return DeepSeekProvider(config)

    raise ValueError(f"不支持的协议: {config.protocol}")
