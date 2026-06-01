"""Mailbox — per-member message files for point-to-point communication."""

import json
import os
from pathlib import Path

from mewcode.teams.models import TeamMessage


class Mailbox:
    """Append-only JSONL mailbox for a single team member."""

    def __init__(self, team_dir: Path, member_name: str) -> None:
        self._dir = team_dir / "mailboxes"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / f"{member_name}.jsonl"
        self._member_name = member_name

    def send(self, msg: TeamMessage) -> None:
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "id": msg.id, "from": msg.from_member, "to": msg.to_member,
                "type": msg.msg_type.value, "content": msg.content,
                "summary": msg.summary, "timestamp": msg.timestamp,
            }, ensure_ascii=False) + "\n")

    def read_new(self, since_id: str = "") -> list[TeamMessage]:
        """Read messages since *since_id* (empty = all)."""
        if not self._file.exists():
            return []
        messages: list[TeamMessage] = []
        found_since = not since_id
        with open(self._file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg_id = data.get("id", "")
                if not found_since:
                    if msg_id == since_id:
                        found_since = True
                    continue
                messages.append(TeamMessage(
                    id=msg_id,
                    from_member=data.get("from", ""),
                    to_member=data.get("to", ""),
                    msg_type=data.get("type", "text"),
                    content=data.get("content", ""),
                    summary=data.get("summary", ""),
                    timestamp=data.get("timestamp", ""),
                ))
        return messages

    def broadcast(self, msg: TeamMessage, all_members: list[str]) -> None:
        """Send *msg* to every member's mailbox."""
        for name in all_members:
            if name == msg.from_member:
                continue
            target = Mailbox(self._dir, name)
            msg.to_member = name
            target.send(msg)
