"""Tool result truncator — layer 1 of token management.

Truncates oversized individual tool results and caps total size across
all tool results in a single conversation round.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from mewcode.providers.base import Message

DEFAULT_STORAGE_DIR = Path.home() / ".mewcode" / "tool_results"


@dataclass
class TruncateConfig:
    per_result_threshold: int = 100_000      # chars — truncate single result above this
    total_round_threshold: int = 500_000     # chars — truncate largest when round exceeds this
    preview_length: int = 2_000              # chars of preview kept in-conversation
    storage_dir: Path = DEFAULT_STORAGE_DIR


class ToolResultTruncator:
    """Scans conversation messages for oversized tool results, writes full
    content to disk, and replaces them with previews."""

    def __init__(self, config: TruncateConfig | None = None) -> None:
        self._cfg = config or TruncateConfig()
        self._cfg.storage_dir.mkdir(parents=True, exist_ok=True)

    # -- public API -----------------------------------------------------------

    def process_round(self, messages: list[Message]) -> tuple[list[Message], list[dict]]:
        """Like ``process`` but additionally enforces the round-level cap.

        Returns ``(truncated_messages, truncation_infos)`` where each info
        dict has keys ``tool_name``, ``original_chars``, ``file_path``.
        """
        infos: list[dict] = []

        # First pass: identify tool messages and their sizes
        tool_indices: list[tuple[int, int]] = []  # (index, char_count)
        for i, msg in enumerate(messages):
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                tool_indices.append((i, len(content)))

        total = sum(chars for _, chars in tool_indices)
        if total <= self._cfg.total_round_threshold:
            msgs, individual_infos = self._truncate_individual(messages)
            infos.extend(individual_infos)
            return msgs, infos

        # Truncate largest tool results first until we're under the cap
        tool_indices.sort(key=lambda x: x[1], reverse=True)
        to_truncate: set[int] = set()
        for idx, chars in tool_indices:
            to_truncate.add(idx)
            total -= max(0, chars - self._cfg.per_result_threshold)
            if total <= self._cfg.total_round_threshold:
                break

        result: list[Message] = []
        for i, msg in enumerate(messages):
            if i in to_truncate and msg.get("role") == "tool":
                truncated, file_path = self._truncate_tool_msg_with_path(msg)
                result.append(truncated)
                infos.append({
                    "tool_name": msg.get("name", "unknown"),
                    "original_chars": len(msg.get("content", "")),
                    "file_path": file_path,
                })
            else:
                result.append(msg)
        return result, infos

    # -- internals ------------------------------------------------------------

    def _truncate_individual(self, messages: list[Message]) -> tuple[list[Message], list[dict]]:
        """Truncate individual oversized results, return messages + infos."""
        result: list[Message] = []
        infos: list[dict] = []
        for msg in messages:
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > self._cfg.per_result_threshold:
                    truncated, file_path = self._truncate_tool_msg_with_path(msg)
                    result.append(truncated)
                    infos.append({
                        "tool_name": msg.get("name", "unknown"),
                        "original_chars": len(content),
                        "file_path": file_path,
                    })
                else:
                    result.append(msg)
            else:
                result.append(msg)
        return result, infos

    def _truncate_tool_msg_with_path(self, msg: Message) -> tuple[Message, str]:
        """Truncate and return (message, file_path)."""
        content = msg.get("content", "")
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        tool_name = msg.get("name", "unknown")
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", tool_name)
        file_path = str(self._cfg.storage_dir / f"{ts}_{safe_name}.txt")
        Path(file_path).write_text(content, encoding="utf-8")
        preview = content[:self._cfg.preview_length]
        truncated_msg = {
            **msg,
            "content": (
                f"[工具结果过大，完整内容已保存到磁盘]\n"
                f"文件: {file_path}\n"
                f"预览（前 {self._cfg.preview_length} 字符）:\n{preview}\n"
                f"...（省略 {len(content) - self._cfg.preview_length} 字符）"
            ),
        }
        return truncated_msg, file_path
