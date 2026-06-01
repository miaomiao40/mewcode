"""MCP server configuration loading."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class MCPServerConfig:
    name: str
    transport: str  # "stdio" | "http"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0


def load_mcp_config(
    project_path: Path | None = None,
    global_path: Path | None = None,
) -> list[MCPServerConfig]:
    """Load MCP server configurations from project and global files.

    Project config overrides global entries with the same ``name``.
    """
    if project_path is None:
        project_path = Path.cwd() / ".mewcode-mcp.yaml"
    if global_path is None:
        global_path = Path.home() / ".mewcode" / "mcp.yaml"

    servers: dict[str, MCPServerConfig] = {}

    # Load global first
    for entry in _load_file(global_path):
        servers[entry.name] = entry

    # Project overrides
    for entry in _load_file(project_path):
        servers[entry.name] = entry

    return list(servers.values())


def _load_file(path: Path) -> list[MCPServerConfig]:
    if not path.exists():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, dict) or "servers" not in raw:
        return []
    result: list[MCPServerConfig] = []
    for entry in raw["servers"]:
        if not isinstance(entry, dict):
            continue
        result.append(MCPServerConfig(
            name=entry.get("name", ""),
            transport=entry.get("transport", ""),
            command=entry.get("command", ""),
            args=entry.get("args", []),
            env=entry.get("env", {}),
            url=entry.get("url", ""),
            headers=entry.get("headers", {}),
            timeout=entry.get("timeout", 30.0),
        ))
    return result
