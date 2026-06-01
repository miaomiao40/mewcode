"""Session persistence — JSONL append + meta file + recovery.

Each session is stored as:
  - ``{sessions_dir}/{id}.jsonl`` — append-only message log
  - ``{sessions_dir}/{id}.meta.json`` — summary for listing

On load: corrupt lines are skipped, unpaired tool_use triggers truncation,
token overflow triggers compression, and time gaps inject reminders.
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mewcode.conversation.history import ConversationHistory

SESSIONS_DIR = Path.home() / ".mewcode" / "sessions"
TIME_GAP_MINUTES = 30  # inject reminder after this inactivity


class SessionStore:
    """JSONL-backed session persistence."""

    def __init__(self) -> None:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self._current_id: str | None = None

    # -- create / switch ------------------------------------------------------

    def new_session(self) -> str:
        sid = uuid.uuid4().hex[:12]
        self._current_id = sid
        self._write_meta(sid, created=True)
        return sid

    @property
    def current_id(self) -> str | None:
        return self._current_id

    # -- append ---------------------------------------------------------------

    def append_message(self, message: dict[str, Any]) -> None:
        """Append a single message to the JSONL (O(1) write)."""
        if not self._current_id:
            self.new_session()
        sid = self._current_id
        line = json.dumps({
            **message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False)
        with open(self._path_for(sid), "a", encoding="utf-8") as f:
            f.write(line + "\n")
        self._update_meta(sid, message_count_delta=1)

    def append_messages(self, messages: list[dict[str, Any]]) -> None:
        """Append multiple messages in one write."""
        if not messages:
            return
        if not self._current_id:
            self.new_session()
        sid = self._current_id
        ts = datetime.now(timezone.utc).isoformat()
        lines = []
        for m in messages:
            lines.append(json.dumps({**m, "timestamp": ts}, ensure_ascii=False))
        with open(self._path_for(sid), "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self._update_meta(sid, message_count_delta=len(messages))

    # -- save full history (compat) -------------------------------------------

    def save(
        self,
        history: ConversationHistory,
        provider_name: str,
        model: str,
        session_name: str = "default",
    ) -> None:
        """Full save — overwrites JSONL with current history.

        Called at the end of each exchange as a safety net.
        """
        if not self._current_id:
            sid = session_name if session_name != "default" else uuid.uuid4().hex[:12]
            self._current_id = sid
        sid = self._current_id

        msgs = history.get_messages()
        ts = datetime.now(timezone.utc).isoformat()
        lines = []
        for m in msgs:
            lines.append(json.dumps({**m, "timestamp": ts}, ensure_ascii=False))

        with open(self._path_for(sid), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        self._write_meta(sid, provider=provider_name, model=model,
                         message_count=len(msgs))

    # -- load / recover -------------------------------------------------------

    def load(
        self, session_name: str = "default",
    ) -> tuple[ConversationHistory, str, str] | None:
        """Load a session with recovery.

        Returns ``(history, provider_name, model)`` or None.
        """
        sid = self._resolve_id(session_name)
        if sid is None:
            return None

        file_path = self._path_for(sid)
        if not file_path.exists():
            return None

        history = ConversationHistory()
        messages: list[dict] = []

        # Read JSONL line by line
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # skip corrupt lines
                messages.append(msg)

        # Truncate at unpaired tool_use
        messages = self._truncate_unpaired(messages)

        # Check for time gaps between messages
        gap_messages = self._detect_time_gaps(messages)
        if gap_messages:
            for gm in gap_messages:
                history.add_context_message(gm["content"])

        # Reconstruct history
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                if "[Prior conversation summary]" in str(content):
                    history.add_context_message(content)
                elif "[结构化摘要]" in str(content):
                    history.add_context_message(content)
                # Skip old system prompts
            elif role == "user":
                if isinstance(content, str):
                    history.add_user_message(content)
                else:
                    history.add_raw_message(msg)
            elif role == "assistant":
                if msg.get("tool_calls") or isinstance(content, list):
                    history.add_raw_message(msg)
                elif content:
                    history.add_assistant_message(content)
            elif role == "tool":
                history.add_raw_message(msg)

        self._current_id = sid

        # Read meta for provider/model
        meta = self._read_meta(sid)
        provider = meta.get("provider", "")
        model = meta.get("model", "")

        return history, provider, model

    # -- list sessions --------------------------------------------------------

    def list_sessions(self) -> list[dict]:
        """Return summary of all sessions from meta files."""
        if not SESSIONS_DIR.exists():
            return []
        sessions: list[dict] = []
        for f in sorted(SESSIONS_DIR.glob("*.meta.json"), reverse=True):
            meta = self._read_meta(f.stem.replace(".meta", ""))
            if meta:
                sessions.append(meta)
        return sessions

    def get_session_title(self, sid: str) -> str | None:
        meta = self._read_meta(sid)
        return meta.get("title") if meta else None

    # -- migration ------------------------------------------------------------

    def migrate_old_format(self) -> bool:
        """Migrate ``default.json`` to JSONL format. Returns True if migrated."""
        old_path = SESSIONS_DIR / "default.json"
        if not old_path.exists():
            return False
        try:
            data = json.loads(old_path.read_text(encoding="utf-8"))
            messages = data.get("messages", [])
            provider = data.get("provider", "")
            model = data.get("model", "")

            sid = uuid.uuid4().hex[:12]
            ts = datetime.now(timezone.utc).isoformat()
            lines = []
            for m in messages:
                lines.append(json.dumps({**m, "timestamp": ts}, ensure_ascii=False))

            new_path = self._path_for(sid)
            with open(new_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

            title = self._guess_title(messages)
            self._write_meta(sid, provider=provider, model=model,
                             message_count=len(messages), title=title)
            self._current_id = sid
            old_path.rename(old_path.with_suffix(".json.bak"))
            return True
        except Exception:
            return False

    # -- internals ------------------------------------------------------------

    def _path_for(self, sid: str) -> Path:
        safe = sid.replace("\\", "_").replace("/", "_")
        return SESSIONS_DIR / f"{safe}.jsonl"

    def _meta_path_for(self, sid: str) -> Path:
        safe = sid.replace("\\", "_").replace("/", "_")
        return SESSIONS_DIR / f"{safe}.meta.json"

    def delete(self, session_id: str) -> bool:
        """Delete a session and its meta file from disk."""
        sid = self._resolve_id(session_id)
        if sid is None:
            return False
        jsonl = self._path_for(sid)
        meta = self._meta_path_for(sid)
        deleted = False
        if jsonl.exists():
            jsonl.unlink()
            deleted = True
        if meta.exists():
            meta.unlink()
            deleted = True
        return deleted

    def _resolve_id(self, session_name: str) -> str | None:
        if session_name != "default":
            # Support partial ID matching (prefix)
            jsonl = SESSIONS_DIR / f"{session_name}.jsonl"
            if jsonl.exists():
                return session_name
            # Try prefix match
            matches = list(SESSIONS_DIR.glob(f"{session_name}*.jsonl"))
            if len(matches) == 1:
                return matches[0].stem
            elif len(matches) > 1:
                return None  # ambiguous
            return None
        # Find most recent session
        metas = sorted(SESSIONS_DIR.glob("*.meta.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if metas:
            return metas[0].stem.replace(".meta", "")
        return None

    def _write_meta(self, sid: str, **kwargs) -> None:
        meta_path = self._meta_path_for(sid)
        existing = self._read_meta(sid)
        now = datetime.now(timezone.utc).isoformat()
        if kwargs.pop("created", False):
            existing["id"] = sid
            existing["created_at"] = now
        existing["last_active_at"] = now
        for k, v in kwargs.items():
            existing[k] = v
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    def _update_meta(self, sid: str, message_count_delta: int = 0) -> None:
        meta = self._read_meta(sid)
        meta["last_active_at"] = datetime.now(timezone.utc).isoformat()
        if message_count_delta:
            meta["message_count"] = meta.get("message_count", 0) + message_count_delta
        self._meta_path_for(sid).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_meta(self, sid: str) -> dict:
        meta_path = self._meta_path_for(sid)
        if meta_path.exists():
            try:
                return json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {"id": sid, "message_count": 0}

    @staticmethod
    def _truncate_unpaired(messages: list[dict]) -> list[dict]:
        """Remove messages after the last unpaired tool_use."""
        open_tool_calls: set[str] = set()
        last_unpaired_idx: int = -1

        for i, msg in enumerate(messages):
            role = msg.get("role", "")
            if role == "assistant":
                tool_calls = msg.get("tool_calls", [])
                content = msg.get("content", "")
                # Anthropic style: content is list with tool_use blocks
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            open_tool_calls.add(block.get("id", ""))
                # OpenAI style: tool_calls field
                for tc in tool_calls:
                    open_tool_calls.add(tc.get("id", ""))

            elif role == "tool":
                tc_id = msg.get("tool_call_id", "")
                if tc_id in open_tool_calls:
                    open_tool_calls.remove(tc_id)

            if open_tool_calls:
                last_unpaired_idx = i

        if last_unpaired_idx >= 0:
            return messages[:last_unpaired_idx]
        return messages

    @staticmethod
    def _detect_time_gaps(messages: list[dict]) -> list[dict]:
        """Find gaps > TIME_GAP_MINUTES and return context messages."""
        gap_messages: list[dict] = []
        prev_ts: datetime | None = None
        for msg in messages:
            ts_str = msg.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                continue
            if prev_ts and (ts - prev_ts) > timedelta(minutes=TIME_GAP_MINUTES):
                delta = ts - prev_ts
                hours = delta.total_seconds() / 3600
                text = f"[时间跨度提醒] 距上次活跃约 {hours:.1f} 小时，以下是新消息。"
                gap_messages.append({
                    "role": "system",
                    "content": text,
                })
            prev_ts = ts
        return gap_messages

    @staticmethod
    def _guess_title(messages: list[dict]) -> str:
        for m in messages:
            if m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, str):
                    return content[:60]
        return "未命名会话"
