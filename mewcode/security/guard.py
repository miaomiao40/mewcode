"""SecurityGuard — orchestrates the full security check pipeline."""

import asyncio
from typing import Any

from mewcode.security.blacklist import check_blacklist
from mewcode.security.models import (
    HITLDecision,
    RuleAction,
    SecurityLevel,
)
from mewcode.security.policy import SecurityPolicy
from mewcode.security.sandbox import PathSandbox


class SecurityGuard:
    """Orchestrates blacklist → sandbox → policy → HITL for each tool call."""

    def __init__(
        self,
        policy: SecurityPolicy,
        sandbox: PathSandbox,
        level: SecurityLevel = SecurityLevel.NORMAL,
    ) -> None:
        self.policy = policy
        self.sandbox = sandbox
        self.level = level

    # -- main pipeline --------------------------------------------------------

    def check(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> tuple[bool, str]:
        """Run the full security pipeline.

        Returns:
            ``(allowed, reason)`` — *allowed* is True if the tool call may
            proceed.  *reason* explains why it was blocked (or "ok").
        """
        # Extract path and command from params for rule matching
        path = params.get("path") or params.get("file_path")
        command = params.get("command") or params.get("cmd")

        # ---- 1. Blacklist (always active) ----
        if command and tool_name == "run_command":
            blocked = check_blacklist(command)
            if blocked:
                return False, blocked

        # ---- 2. Path sandbox ----
        if path and tool_name in {"read_file", "write_file", "edit_file", "glob", "grep"}:
            safe, msg = self.sandbox.validate(path)
            if not safe:
                return False, msg

        # ---- 3. Policy evaluation ----
        action = self.policy.evaluate(tool_name, path=path, command=command)

        if action == RuleAction.ALLOW:
            return True, "ok"
        elif action == RuleAction.DENY:
            reason = f"安全策略拒绝: {tool_name}"
            if path:
                reason += f" (path={path})"
            if command:
                reason += f" (command={command})"
            return False, reason
        else:
            # ASK — handled by caller (AgentLoop via HITL)
            return True, "ask"

    def needs_hitl(self, tool_name: str, params: dict[str, Any]) -> bool:
        """Check whether this tool call requires human-in-the-loop."""
        path = params.get("path") or params.get("file_path")
        command = params.get("command") or params.get("cmd")
        action = self.policy.evaluate(tool_name, path=path, command=command)
        return action == RuleAction.ASK

    def build_hitl_prompt(self, tool_name: str, params: dict[str, Any]) -> str:
        return self.policy.to_hitl_prompt(tool_name, params)

    def apply_hitl(
        self,
        decision: HITLDecision,
        tool_name: str,
        params: dict[str, Any],
    ) -> None:
        """Apply the HITL decision (create session/permanent rules)."""
        path = params.get("path") or params.get("file_path")
        command = params.get("command") or params.get("cmd")
        self.policy.hitl_to_rule(decision, tool_name, path=path, command=command)

    def set_level(self, level: SecurityLevel) -> None:
        self.level = level
        self.policy.set_level(level)
