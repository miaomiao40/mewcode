"""Security policy — evaluates rules with session > project > global priority."""

import fnmatch
from pathlib import Path
from typing import Any

import yaml

from mewcode.security.models import (
    HITLDecision,
    RuleAction,
    RuleScope,
    SecurityLevel,
    SecurityRule,
)


# Default path globs allowed in STRICT mode (in addition to configured rules)
STRICT_DEFAULT_ALLOWED = [
    "*.py", "*.txt", "*.md", "*.yaml", "*.yml", "*.json", "*.toml", "*.cfg",
    "*.js", "*.ts", "*.tsx", "*.jsx", "*.css", "*.html",
    "src/**", "lib/**", "tests/**", "test/**", "docs/**",
]


class SecurityPolicy:
    """Evaluates security rules with three-tier priority."""

    def __init__(
        self,
        level: SecurityLevel = SecurityLevel.NORMAL,
        project_root: Path | None = None,
    ) -> None:
        self.level = level
        self._project_root = (project_root or Path.cwd()).resolve()
        self._session_rules: list[SecurityRule] = []
        self._project_rules: list[SecurityRule] = []
        self._global_rules: list[SecurityRule] = []

        # Load persistent rules
        self._load_project_rules()
        self._load_global_rules()

    # -- rule management -----------------------------------------------------

    def add_session_rule(self, rule: SecurityRule) -> None:
        rule.scope = RuleScope.SESSION
        self._session_rules.insert(0, rule)

    def add_permanent_rule(self, rule: SecurityRule) -> None:
        """Save a rule permanently to the project-level security file."""
        rule.scope = RuleScope.PROJECT
        self._project_rules.insert(0, rule)
        self._save_project_rules()

    def set_level(self, level: SecurityLevel) -> None:
        self.level = level

    # -- evaluation ----------------------------------------------------------

    def evaluate(
        self,
        tool_name: str,
        path: str | None = None,
        command: str | None = None,
    ) -> RuleAction:
        """Evaluate rules and return the effective action.

        Priority: session > project > global > mode default.
        """
        # 1. Check rules in priority order
        for rules in [self._session_rules, self._project_rules, self._global_rules]:
            for rule in rules:
                if rule.matches(tool_name, path=path, command=command):
                    return rule.action

        # 2. Mode-based default
        return self._mode_default(tool_name, path)

    def to_hitl_prompt(self, tool_name: str, params: dict[str, Any]) -> str:
        """Build the HITL prompt text."""
        args = ", ".join(f"{k}={v!r}" for k, v in params.items())
        return (
            f"⚠ 安全确认: {tool_name}({args})\n"
            f"  当前模式: {self.level.value}\n"
            f"  [A]llow once  [S]ession allow  [P]ermanent allow  [D]eny"
        )

    def hitl_to_rule(
        self, decision: HITLDecision, tool_name: str,
        path: str | None, command: str | None,
    ) -> SecurityRule | None:
        """Convert a HITL decision into a new security rule (if permanent)."""
        if decision == HITLDecision.ALLOW_PERMANENT:
            rule = SecurityRule(
                tool=tool_name,
                action=RuleAction.ALLOW,
                path_pattern=path,
                command_pattern=command,
                scope=RuleScope.PROJECT,
            )
            self.add_permanent_rule(rule)
            return rule
        elif decision == HITLDecision.ALLOW_SESSION:
            rule = SecurityRule(
                tool=tool_name,
                action=RuleAction.ALLOW,
                path_pattern=path,
                command_pattern=command,
                scope=RuleScope.SESSION,
            )
            self.add_session_rule(rule)
            return rule
        return None

    # -- internals -----------------------------------------------------------

    def _mode_default(self, tool_name: str, path: str | None) -> RuleAction:
        from mewcode.tools.base import ToolCategory
        # Determine if tool is read-only
        is_read = self._is_read_tool(tool_name)

        if self.level == SecurityLevel.STRICT:
            # In strict mode: only allow if path matches allowed globs
            if path and self._is_path_allowed(path):
                return RuleAction.ALLOW
            return RuleAction.ASK

        elif self.level == SecurityLevel.NORMAL:
            if is_read:
                return RuleAction.ALLOW
            # Write tools in normal mode: ask
            return RuleAction.ASK

        elif self.level == SecurityLevel.PERMISSIVE:
            return RuleAction.ALLOW

        return RuleAction.ASK

    def _is_read_tool(self, tool_name: str) -> bool:
        return tool_name in {"read_file", "glob", "grep"}

    def _is_path_allowed(self, path: str) -> bool:
        """Check path against strict-mode allowed globs."""
        for pattern in STRICT_DEFAULT_ALLOWED:
            if fnmatch.fnmatch(path, pattern):
                return True
        # Also check project/global rules for allow rules with path_pattern
        for rules in [self._project_rules, self._global_rules]:
            for rule in rules:
                if rule.action == RuleAction.ALLOW and rule.path_pattern:
                    if fnmatch.fnmatch(path, rule.path_pattern):
                        return True
        return False

    # -- persistence ---------------------------------------------------------

    def _project_config_path(self) -> Path:
        return self._project_root / ".mewcode-security.yaml"

    def _global_config_path(self) -> Path:
        return Path.home() / ".mewcode" / "security.yaml"

    def _load_project_rules(self) -> None:
        self._project_rules = self._load_rules_file(self._project_config_path())

    def _load_global_rules(self) -> None:
        self._global_rules = self._load_rules_file(self._global_config_path())

    def _load_rules_file(self, path: Path) -> list[SecurityRule]:
        if not path.exists():
            return []
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(raw, dict) or "rules" not in raw:
            return []
        rules: list[SecurityRule] = []
        for entry in raw["rules"]:
            action_str = entry.get("action", "ask")
            try:
                action = RuleAction(action_str)
            except ValueError:
                continue
            rule = SecurityRule(
                tool=entry.get("tool", "*"),
                action=action,
                path_pattern=entry.get("path_pattern"),
                command_pattern=entry.get("command_pattern"),
                scope=RuleScope.PROJECT,
            )
            rules.append(rule)
        return rules

    def _save_project_rules(self) -> None:
        path = self._project_config_path()
        entries: list[dict] = []
        for rule in self._project_rules:
            entry: dict = {"tool": rule.tool, "action": rule.action.value}
            if rule.path_pattern:
                entry["path_pattern"] = rule.path_pattern
            if rule.command_pattern:
                entry["command_pattern"] = rule.command_pattern
            entries.append(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.dump({"rules": entries}, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
