"""Structured summarizer — layer 2 of token management.

Produces LLM summaries with mandatory sections.  Includes a circuit breaker
to stop auto-triggering on repeated failures.
"""

from dataclasses import dataclass

from mewcode.conversation.history import CHARS_PER_TOKEN
from mewcode.providers.base import BaseProvider, Message

#: Fraction of context window that triggers summarization.
TRIGGER_FRACTION = 0.7

#: Known context window sizes.
_MODEL_WINDOWS: dict[str, int] = {
    "claude-opus-4": 200_000, "claude-sonnet-4": 200_000, "claude-haiku-4": 200_000,
    "claude-3-opus": 200_000, "claude-3-sonnet": 200_000, "claude-3-haiku": 200_000,
    "claude-3.5-sonnet": 200_000, "claude-3.5-haiku": 200_000,
    "gpt-4": 128_000, "gpt-4o": 128_000, "gpt-4-turbo": 128_000,
    "gpt-4.1": 1_000_000, "gpt-3.5-turbo": 16_385,
    "o1": 200_000, "o3": 200_000, "o4": 200_000,
}
DEFAULT_WINDOW = 128_000
KEEP_RECENT = 4  # messages preserved verbatim at the tail

# ---------------------------------------------------------------------------
# Structured summary prompt
# ---------------------------------------------------------------------------

_SUMMARY_PROMPT = """\
你是一个对话摘要生成器。**只生成摘要，不要调用任何工具。**

请分析以下对话，按指定结构生成摘要。每个部分用 ## 标题分隔：

## 主要请求
用户的核心需求——他们想完成什么

## 关键概念
涉及的技术栈、框架、API、库

## 文件与代码
已检查或修改的文件、关键代码片段及其位置

## 错误与修复
遇到的错误信息和修复方式

## 解决过程
问题解决的步骤顺序和时间线

## 用户原话
用户的关键原话（用 > 引用，逐字保留，不要改写）

## 待办事项
尚未完成的任务

## 当前工作
当前正在进行的具体工作

## 下一步
建议的下一步操作

---

先将你的分析写成草稿，用 ```draft ... ``` 包裹。草稿写完后再输出正式摘要。

**再次强调：不要调用任何工具，只输出摘要文本。**"""

#: Post-compression boundary message (appended after the summary).
_BOUNDARY_MSG = (
    "[对话上下文已压缩] 上方的结构化摘要替代了早期的详细对话。"
    "如果你需要某个文件的完整内容或某段具体代码，请使用 read_file 或 grep "
    "重新读取，不要根据摘要脑补不存在的细节。"
)


@dataclass
class SummaryResult:
    summary_text: str = ""
    messages_compressed: int = 0
    tokens_saved: int = 0
    boundary_added: bool = False


class CircuitBreaker:
    """Opens after *max_failures* consecutive failures, halting auto-trigger."""

    def __init__(self, max_failures: int = 2) -> None:
        self._max = max_failures
        self._count = 0
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def record_failure(self) -> None:
        self._count += 1
        if self._count >= self._max:
            self._open = True

    def record_success(self) -> None:
        self._count = 0
        self._open = False

    def reset(self) -> None:
        self._count = 0
        self._open = False


class StructuredSummarizer:
    """Generates structured summaries when the conversation approaches the
    context-window limit."""

    def __init__(self, provider: BaseProvider, model: str) -> None:
        self._provider = provider
        self._model = model
        self._window = _MODEL_WINDOWS.get(model, DEFAULT_WINDOW)
        self._trigger = int(self._window * TRIGGER_FRACTION)
        self._breaker = CircuitBreaker()

    # -- properties -----------------------------------------------------------

    @property
    def context_window(self) -> int:
        return self._window

    @property
    def trigger_threshold(self) -> int:
        return self._trigger

    @property
    def circuit_open(self) -> bool:
        return self._breaker.is_open

    def reset_circuit(self) -> None:
        self._breaker.reset()

    # -- main API -------------------------------------------------------------

    def needs_summary(self, messages: list[Message]) -> bool:
        """Check whether token count exceeds the trigger threshold."""
        return self._estimate_tokens(messages) >= self._trigger

    async def summarize(
        self, messages: list[Message],
    ) -> tuple[list[Message], SummaryResult]:
        """Generate a structured summary of old messages.

        Returns ``(new_messages, result)``.  On failure, returns the original
        messages and a zeroed result; the circuit breaker is ticked.
        """
        result = SummaryResult()

        # Only summarize if enough messages to compress
        if len(messages) < KEEP_RECENT + 4:
            return messages, result

        # Partition: summarize older messages, keep recent ones verbatim
        split = len(messages) - KEEP_RECENT
        old = messages[:split]
        recent = messages[split:]

        # Build summary request — preserve user verbatim messages
        summary_input = _SUMMARY_PROMPT + "\n\n---\n对话内容:\n" + _format_for_summary(old)

        try:
            summary_text = ""
            async for token in self._provider.chat_stream(
                [{"role": "user", "content": summary_input}],
            ):
                if isinstance(token, str) and not token.startswith("<<"):
                    summary_text += token

            # Strip draft (keep only post-draft content)
            draft_end = summary_text.find("```")
            if draft_end != -1:
                # Find the closing ``` of the draft block, then take everything after
                second = summary_text.find("```", draft_end + 3)
                if second != -1:
                    summary_text = summary_text[second + 3:].strip()

            if not summary_text.strip():
                raise ValueError("摘要生成返回空内容")

        except Exception:
            self._breaker.record_failure()
            return messages, result

        self._breaker.record_success()

        # Count what we saved
        old_chars = sum(len(m.get("content", "") or "") for m in old)
        saved_tokens = int(old_chars / CHARS_PER_TOKEN) - int(len(summary_text) / CHARS_PER_TOKEN)

        # Build new message list
        new_messages: list[Message] = [
            {"role": "system", "content": f"[结构化摘要]\n{summary_text}"},
            {"role": "system", "content": _BOUNDARY_MSG},
            *recent,
        ]

        result.summary_text = summary_text
        result.messages_compressed = len(old)
        result.tokens_saved = max(0, saved_tokens)
        result.boundary_added = True

        return new_messages, result

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _estimate_tokens(messages: list[Message]) -> int:
        total = 0
        for m in messages:
            content = m.get("content")
            if isinstance(content, str):
                total += len(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        total += len(str(block))
        return int(total / CHARS_PER_TOKEN)


def _format_for_summary(messages: list[Message]) -> str:
    """Format messages for the summarizer prompt."""
    parts: list[str] = []
    for m in messages:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if isinstance(content, str):
            text = content[:3000]  # cap per-message length in prompt
        elif isinstance(content, list):
            text = str(content)[:3000]
        else:
            text = str(content)[:3000]
        parts.append(f"[{role}]: {text}")
    return "\n\n".join(parts)
