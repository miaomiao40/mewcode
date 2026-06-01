"""Command system — registry, parser, dispatcher, built-in commands."""

from mewcode.commands.types import CommandType, CommandMeta, UIControl
from mewcode.commands.registry import CommandRegistry
from mewcode.commands.parser import parse, is_command
from mewcode.commands.dispatcher import CommandDispatcher

__all__ = [
    "CommandType", "CommandMeta", "UIControl",
    "CommandRegistry",
    "parse", "is_command",
    "CommandDispatcher",
    "register_builtins",
]


def register_builtins(registry: CommandRegistry, ui: UIControl, note_manager=None, skill_registry=None, task_manager=None, worktree_manager=None) -> None:
    """Register all built-in commands with the given registry."""
    from mewcode.commands.builtin.help_cmd import create as _help
    from mewcode.commands.builtin.compress_cmd import create as _compress
    from mewcode.commands.builtin.clear_cmd import create as _clear
    from mewcode.commands.builtin.mode_cmd import create as _mode
    from mewcode.commands.builtin.session_cmd import create as _session
    from mewcode.commands.builtin.memory_cmd import create as _memory
    from mewcode.commands.builtin.permission_cmd import create as _permission
    from mewcode.commands.builtin.status_cmd import create as _status
    from mewcode.commands.builtin.review_cmd import create as _review
    from mewcode.commands.builtin.skill_cmd import create as _skill
    from mewcode.commands.builtin.tasks_cmd import create as _tasks
    from mewcode.commands.builtin.worktree_cmd import create as _worktree
    from mewcode.commands.builtin.team_cmd import create as _team

    registry.register(_help(registry))
    registry.register(_compress(ui))
    registry.register(_clear(ui))
    registry.register(_mode(ui))
    registry.register(_session(ui))
    registry.register(_permission(ui))
    registry.register(_status(ui))
    registry.register(_review())
    if skill_registry:
        registry.register(_skill(skill_registry, ui))
    if note_manager:
        registry.register(_memory(note_manager))
    if task_manager:
        registry.register(_tasks(task_manager))
    if worktree_manager:
        registry.register(_worktree(worktree_manager))
    registry.register(_team())
