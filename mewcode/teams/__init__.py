"""Team system — multi-agent orchestration with shared tasks and messaging."""

from mewcode.teams.models import TeamDef, MemberDef, TeamTask, TeamMessage, MemberStatus, TaskStatus
from mewcode.teams.lead import LeadAgent
from mewcode.teams.member import TeamMember
from mewcode.teams.tasks import SharedTaskList
from mewcode.teams.mailbox import Mailbox
from mewcode.teams.registry import NameRegistry
from mewcode.teams.merger import GitMerger
from mewcode.teams.scheduler import DispatchScheduler
from mewcode.teams.persistence import load_team_def, list_team_defs, get_team_dir

__all__ = [
    "TeamDef", "MemberDef", "TeamTask", "TeamMessage", "MemberStatus", "TaskStatus",
    "LeadAgent", "TeamMember", "SharedTaskList", "Mailbox", "NameRegistry",
    "GitMerger", "DispatchScheduler",
    "load_team_def", "list_team_defs", "get_team_dir",
]
