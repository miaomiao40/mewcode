"""Worktree management command."""

from pathlib import Path

from mewcode.commands.types import CommandMeta, CommandType
from mewcode.worktree.manager import GitWorktreeManager
from mewcode.worktree.initializer import WorktreeInitializer


def create(manager: GitWorktreeManager) -> CommandMeta:
    initializer = WorktreeInitializer(manager._repo_root)

    async def handler(args: list[str]) -> str:
        if not args or args[0] == "status":
            info = await manager.status()
            if info is None:
                return "当前不在工作目录中（位于主仓库）"
            return (
                f"当前工作目录: {info.name}\n"
                f"路径: {info.path}\n"
                f"分支: {info.branch}\n"
                f"HEAD: {info.head_commit[:12]}\n"
                f"有修改: {'是' if info.has_changes else '否'}"
            )

        elif args[0] == "list":
            worktrees = await manager.list_worktrees()
            if not worktrees:
                return "没有工作目录"
            lines = ["工作目录列表:"]
            for wt in worktrees:
                marker = "●" if wt.is_active else "○"
                dirty = " *" if wt.has_changes else ""
                lines.append(f"  {marker} {wt.name}{dirty}  ({wt.branch})")
            return "\n".join(lines)

        elif args[0] == "create":
            if len(args) < 2:
                return "用法: /worktree create <名称> [分支]"
            name = args[1]
            branch = args[2] if len(args) > 2 else ""
            info, err = await manager.create(name, branch)
            if info:
                initializer.initialize(Path(info.path))
                return f"工作目录已创建: {info.name}\n路径: {info.path}\n分支: {info.branch}"
            return f"创建失败: {err}"

        elif args[0] == "enter":
            if len(args) < 2:
                return "用法: /worktree enter <名称>"
            ok, msg = await manager.enter(args[1])
            if ok:
                return f"已进入工作目录: {args[1]}（请重启 MewCode 使切换生效）"
            return f"进入失败: {msg}"

        elif args[0] == "exit":
            force = "--force" in args
            name = next((a for a in args if not a.startswith("-") and a != "exit"), manager.active)
            if not name:
                return "用法: /worktree exit <名称> [--force]"
            ok, msg = await manager.exit(name, force=force)
            return msg if ok else f"退出失败: {msg}"

        return f"未知子命令: {args[0]}。可用: status, list, create, enter, exit"

    return CommandMeta(
        name="worktree",
        aliases=["wt"],
        description="管理 Git 工作目录（status/list/create/enter/exit）",
        usage="/worktree [status | list | create <name> [branch] | enter <name> | exit <name> [--force]]",
        cmd_type=CommandType.UI,
        handler=handler,
    )
