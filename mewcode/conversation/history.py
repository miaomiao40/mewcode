"""Conversation history — user/assistant/tool message storage."""

import json

from mewcode.providers.base import Message

CHARS_PER_TOKEN = 3.5


def _content_chars(content: object) -> int:
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(_content_chars(item.get("content", "") if isinstance(item, dict) else "") for item in content)
    return len(str(content))


class ConversationHistory:
    """Ordered message list (user, assistant, tool). No system prompt — that
    is managed by the PromptBuilder and AgentLoop."""

    def __init__(self) -> None:
        self._messages: list[Message] = []

    # -- mutation ------------------------------------------------------------

    def add_user_message(self, content: str) -> None:
        if not content:
            return
        self._messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        if not content:
            return
        self._messages.append({"role": "assistant", "content": content})

    def add_raw_message(self, message: Message) -> None:
        if message.get("role") == "assistant":
            has_content = bool(message.get("content"))
            has_tool_calls = bool(message.get("tool_calls"))
            if not has_content and not has_tool_calls:
                return
        self._messages.append(message)

    def add_context_message(self, content: str) -> None:
        """Append a system-level context message (compression summary)."""
        self._messages.append({"role": "system", "content": content})

    def replace_messages(self, messages: list[Message]) -> None:
        self._messages = messages

    def clear(self) -> None:
        self._messages.clear()

    # -- access --------------------------------------------------------------

    def get_messages(self) -> list[Message]:
        """Return messages (no system prompt — caller adds prompt context)."""
        result: list[Message] = []
        for msg in self._messages:
            if msg.get("role") == "assistant":
                has_content = bool(msg.get("content"))
                has_tool_calls = bool(msg.get("tool_calls"))
                if not has_content and not has_tool_calls:
                    continue
            result.append(msg)
        return result

    def estimated_token_count(self) -> int:
        total_chars = 0
        for msg in self._messages:
            total_chars += _content_chars(msg.get("content"))
            if "tool_calls" in msg:
                total_chars += len(json.dumps(msg["tool_calls"], ensure_ascii=False))
        return max(0, int(total_chars / CHARS_PER_TOKEN))

    def __len__(self) -> int:
        return len(self._messages)

    def __iter__(self):
        return iter(self._messages)
