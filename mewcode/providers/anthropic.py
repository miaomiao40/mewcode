"""Anthropic provider — SSE streaming with cache_control, thinking, and tool use."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from mewcode.config.models import ProviderConfig
from mewcode.providers.base import BaseProvider, Message, ToolCall

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(BaseProvider):
    """Provider for the Anthropic Messages API."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._thinking_enabled = False
        self._thinking_budget_tokens = 4096
        self.last_usage: dict[str, int] = {}

    # -- thinking control ----------------------------------------------------

    def enable_thinking(self, budget_tokens: int = 4096) -> None:
        self._thinking_enabled = True
        self._thinking_budget_tokens = budget_tokens

    def disable_thinking(self) -> None:
        self._thinking_enabled = False

    def supports_thinking(self) -> bool:
        return True

    @property
    def thinking_enabled(self) -> bool:
        return self._thinking_enabled

    @property
    def cache_hit(self) -> bool:
        """Whether the last request had a cache read (prompt caching)."""
        return self.last_usage.get("cache_read_input_tokens", 0) > 0

    # -- streaming -----------------------------------------------------------

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system_blocks: list[dict] | None = None,
    ) -> AsyncIterator[str | ToolCall]:
        base = self.config.base_url.rstrip("/")
        url = f"{base}/v1/messages"

        body: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": 4096,
            "messages": messages,
            "stream": True,
        }

        # System prompt with cache_control
        if system_blocks:
            body["system"] = system_blocks

        if self._thinking_enabled:
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": self._thinking_budget_tokens,
            }

        # Tool definitions with cache_control
        if tools:
            body["tools"] = [
                {**t, "cache_control": {"type": "ephemeral"}}
                for t in tools
            ]

        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }

        self.last_usage = {}

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    error_text = await resp.aread()
                    yield f"<<ERROR:{resp.status_code}:{error_text.decode(errors='replace')[:500]}>>"
                    return

                current_tool_id: str | None = None
                current_tool_name: str = ""
                current_tool_input: str = ""

                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[len("data: "):]
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    event_type = data.get("type", "")

                    # --- content block delta ---
                    if event_type == "content_block_delta":
                        delta = data.get("delta", {})
                        delta_type = delta.get("type", "")
                        if delta_type == "thinking_delta":
                            yield f"<<THINKING:{delta.get('thinking', '')}>>"
                        elif delta_type == "text_delta":
                            yield delta.get("text", "")
                        elif delta_type == "input_json_delta":
                            current_tool_input += delta.get("partial_json", "")

                    # --- tool use start ---
                    elif event_type == "content_block_start":
                        block = data.get("content_block", {})
                        if block.get("type") == "tool_use":
                            current_tool_id = block.get("id", "")
                            current_tool_name = block.get("name", "")
                            current_tool_input = ""

                    # --- tool use end ---
                    elif event_type == "content_block_stop":
                        if current_tool_id and current_tool_input:
                            try:
                                tool_input = json.loads(current_tool_input)
                            except json.JSONDecodeError:
                                tool_input = {}
                            yield ToolCall(
                                id=current_tool_id,
                                name=current_tool_name,
                                input=tool_input,
                            )
                            current_tool_id = None
                            current_tool_name = ""
                            current_tool_input = ""

                    # --- message delta (usage info) ---
                    elif event_type == "message_delta":
                        usage = data.get("usage", {})
                        if usage:
                            self.last_usage.update(usage)

                    # --- message stop ---
                    elif event_type == "message_stop":
                        # Final usage from message_start or accumulated
                        pass

    # -- tool message formatting -----------------------------------------------

    def make_tool_calls_message(
        self, tool_calls: list[ToolCall], text_prefix: str = ""
    ) -> Message:
        content: list[dict] = []
        if text_prefix:
            content.append({"type": "text", "text": text_prefix})
        for tc in tool_calls:
            content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.input,
            })
        return {"role": "assistant", "content": content}

    def make_tool_result_message(
        self, tool_call_id: str, tool_name: str, result_text: str
    ) -> Message:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": result_text,
                }
            ],
        }
