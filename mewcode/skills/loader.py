"""Skill loader — scan three tiers, parse YAML frontmatter + Markdown body."""

import re
import sys
from pathlib import Path

import yaml

from mewcode.skills.models import HistoryCarry, SkillDefinition, SkillMeta, SkillMode

#: Project-level skills directory
PROJECT_DIR = Path.cwd() / ".mewcode" / "skills"
#: User-level skills directory
USER_DIR = Path.home() / ".mewcode" / "skills"
#: Built-in skills directory (relative to this package)
BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class SkillLoader:
    """Scans three-tier skill directories, resolves overrides by name,
    and parses each valid skill file."""

    def load_all(self) -> list[SkillDefinition]:
        """Phase 1: load all skills (names + descriptions only, bodies deferred)."""
        index: dict[str, SkillDefinition] = {}

        # Built-in first (lowest priority)
        self._scan_dir(BUILTIN_DIR, index)
        # User next
        self._scan_dir(USER_DIR, index)
        # Project last (highest priority — overrides same name)
        self._scan_dir(PROJECT_DIR, index)

        return list(index.values())

    def load_one(self, source_path: str) -> SkillDefinition | None:
        """Hot-reload a single skill file. Returns None on parse failure."""
        return self._parse_file(Path(source_path))

    # -- internals -----------------------------------------------------------

    def _scan_dir(self, directory: Path, index: dict[str, SkillDefinition]) -> None:
        if not directory.exists():
            return

        # Single-file skills: *.md
        for md_file in sorted(directory.glob("*.md")):
            skill = self._parse_file(md_file)
            if skill:
                index[skill.meta.name] = skill  # override by name

        # Directory skills: subdirectories with skill.md
        for subdir in sorted(directory.iterdir()):
            if not subdir.is_dir():
                continue
            skill_md = subdir / "skill.md"
            if not skill_md.exists():
                continue
            skill = self._parse_file(skill_md)
            if skill:
                skill.directory = str(subdir)
                index[skill.meta.name] = skill

    def _parse_file(self, path: Path) -> SkillDefinition | None:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"Skill [{path}]: 读取失败 — {exc}", file=sys.stderr)
            return None

        match = _FRONTMATTER_RE.match(text)
        if not match:
            print(f"Skill [{path}]: 缺少 YAML frontmatter (--- ... ---)", file=sys.stderr)
            return None

        try:
            frontmatter = yaml.safe_load(match.group(1))
        except yaml.YAMLError as exc:
            print(f"Skill [{path}]: YAML 解析失败 — {exc}", file=sys.stderr)
            return None

        if not isinstance(frontmatter, dict):
            print(f"Skill [{path}]: frontmatter 不是字典", file=sys.stderr)
            return None

        name = frontmatter.get("name", path.stem)
        if not name:
            print(f"Skill [{path}]: 缺少 name 字段", file=sys.stderr)
            return None

        # Parse mode
        mode_str = frontmatter.get("mode", "shared").lower()
        try:
            mode = SkillMode(mode_str)
        except ValueError:
            print(f"Skill [{name}]: 无效 mode '{mode_str}'，使用 shared", file=sys.stderr)
            mode = SkillMode.SHARED

        # Parse history_carry
        hc_str = frontmatter.get("history_carry", "full").lower()
        try:
            history_carry = HistoryCarry(hc_str)
        except ValueError:
            history_carry = HistoryCarry.FULL

        meta = SkillMeta(
            name=name,
            description=frontmatter.get("description", ""),
            mode=mode,
            model=frontmatter.get("model"),
            tools=frontmatter.get("tools"),
            history_carry=history_carry,
            recent_count=frontmatter.get("recent_count", 10),
            source=str(path),
        )

        body = text[match.end():].strip()
        return SkillDefinition(meta=meta, body=body)
