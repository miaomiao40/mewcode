"""Role loader — scan three tiers for YAML+Markdown role definitions."""

import re
import sys
from pathlib import Path

import yaml

from mewcode.subagent.models import SubAgentRole

PROJECT_DIR = Path.cwd() / ".mewcode" / "roles"
USER_DIR = Path.home() / ".mewcode" / "roles"
BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class RoleLoader:
    """Loads sub-agent role definitions from three-tier directories."""

    def load_all(self) -> dict[str, SubAgentRole]:
        index: dict[str, SubAgentRole] = {}
        self._scan_dir(BUILTIN_DIR, index)
        self._scan_dir(USER_DIR, index)
        self._scan_dir(PROJECT_DIR, index)
        return index

    def _scan_dir(self, directory: Path, index: dict[str, SubAgentRole]) -> None:
        if not directory.exists():
            return
        for md_file in sorted(directory.glob("*.md")):
            role = self._parse(md_file)
            if role:
                index[role.name] = role

    def _parse(self, path: Path) -> SubAgentRole | None:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"Role [{path}]: 读取失败 — {exc}", file=sys.stderr)
            return None

        match = _FRONTMATTER_RE.match(text)
        if not match:
            print(f"Role [{path}]: 缺少 YAML frontmatter", file=sys.stderr)
            return None

        try:
            fm = yaml.safe_load(match.group(1))
        except yaml.YAMLError as exc:
            print(f"Role [{path}]: YAML 解析失败 — {exc}", file=sys.stderr)
            return None

        name = fm.get("name", path.stem)
        body = text[match.end():].strip()

        return SubAgentRole(
            name=name,
            description=fm.get("description", ""),
            tools_allow=fm.get("tools_allow"),
            tools_deny=fm.get("tools_deny", []),
            model=fm.get("model"),
            max_rounds=fm.get("max_rounds", 5),
            permission=fm.get("permission", "normal"),
            system_prompt=body,
            source=str(path),
        )
