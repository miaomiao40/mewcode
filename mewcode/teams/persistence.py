"""Team persistence — save/load team state from disk."""

import json
from pathlib import Path

from mewcode.teams.models import MemberDef, TeamDef

PROJECT_TEAMS_DIR = Path.cwd() / ".mewcode" / "teams"
USER_TEAMS_DIR = Path.home() / ".mewcode" / "teams"


def load_team_def(name: str) -> TeamDef | None:
    """Load a team definition from user-level directory."""
    path = USER_TEAMS_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    members = []
    for m in data.get("members", []):
        members.append(MemberDef(
            name=m.get("name", ""), role=m.get("role", ""),
            worktree=m.get("worktree", ""), backend=m.get("backend", "coro"),
            needs_approval=m.get("needs_approval", False),
            model=m.get("model", ""),
        ))

    return TeamDef(
        name=data.get("name", name), description=data.get("description", ""),
        lead_role=data.get("lead_role", ""), members=members,
        dispatch_mode=data.get("dispatch_mode", False),
        max_rounds_per_member=data.get("max_rounds_per_member", 10),
    )


def list_team_defs() -> list[str]:
    """List available team definition names."""
    if not USER_TEAMS_DIR.exists():
        return []
    return [p.stem for p in USER_TEAMS_DIR.glob("*.json")]


def get_team_dir(name: str) -> Path:
    """Get the project-level working directory for a team."""
    d = PROJECT_TEAMS_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    return d
