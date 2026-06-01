"""Compatibility wrapper — delegates to the two-layer token management system.

Layer 1: ``ToolResultTruncator`` — lightweight, runs before every API call.
Layer 2: ``StructuredSummarizer`` — expensive LLM call, only when needed.
"""

from dataclasses import dataclass

from mewcode.conversation.history import ConversationHistory
from mewcode.conversation.summarizer import StructuredSummarizer, SummaryResult
from mewcode.conversation.truncator import ToolResultTruncator
from mewcode.providers.base import BaseProvider, Message


@dataclass
class CompressionResult:
    """Public result (kept backward-compatible)."""
    was_compressed: bool = False
    messages_compressed: int = 0
    estimated_tokens_saved: int = 0
    warning_issued: bool = False
    summary_result: SummaryResult | None = None


class ContextCompressor:
    """Orchestrates the two-layer token management pipeline.

    Usage (before each API call):
        1. ``truncate(messages)`` → lightweight tool-result truncation
        2. ``check_and_compress(history, provider)`` → expensive LLM summary
    """

    def __init__(self, model: str, provider: BaseProvider) -> None:
        self._truncator = ToolResultTruncator()
        self._summarizer = StructuredSummarizer(provider, model)
        self._warning_emitted = False

    # -- public API -----------------------------------------------------------

    @property
    def context_window(self) -> int:
        return self._summarizer.context_window

    @property
    def warning_threshold(self) -> int:
        return self._summarizer.trigger_threshold

    @property
    def circuit_open(self) -> bool:
        return self._summarizer.circuit_open

    def reset_circuit(self) -> None:
        self._summarizer.reset_circuit()

    def truncate(self, messages: list[Message]) -> list[Message]:
        """Layer 1: truncate oversized tool results (cheap, no LLM call)."""
        result, _ = self._truncator.process_round(messages)
        return result

    async def check_and_compress(
        self, history: ConversationHistory, provider: BaseProvider,
    ) -> CompressionResult:
        """Layer 2: generate structured summary if near context limit.

        Returns a ``CompressionResult``.  The history is mutated in-place
        if compression occurred.
        """
        result = CompressionResult()

        messages = history.get_messages()

        # Warning
        if not self._warning_emitted and self._summarizer.needs_summary(messages):
            result.warning_issued = True
            self._warning_emitted = True

        # Circuit breaker check
        if self._summarizer.circuit_open:
            return result

        # Only compress if actually needed
        estimated = StructuredSummarizer._estimate_tokens(messages)
        if estimated < self._summarizer.trigger_threshold:
            return result

        new_messages, summary = await self._summarizer.summarize(messages)
        if summary.messages_compressed == 0:
            return result  # failed — circuit breaker already ticked

        # Replace history messages with compressed version
        history.replace_messages(new_messages)

        result.was_compressed = True
        result.messages_compressed = summary.messages_compressed
        result.estimated_tokens_saved = summary.tokens_saved
        result.summary_result = summary
        return result

    def reset_warning(self) -> None:
        self._warning_emitted = False
