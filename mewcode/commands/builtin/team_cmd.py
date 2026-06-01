"""Team management command."""

from mewcode.commands.types import CommandMeta, CommandType
from mewcode.teams.persistence import get_team_dir, list_team_defs, load_team_def


def create() -> CommandMeta:
    async def handler(args: list[str]) -> str:
        if not args or args[0] == "list":
            teams = list_team_defs()
            if not teams:
                return "没有已定义的 Team。在 ~/.mewcode/teams/ 创建 JSON 定义文件。"
            lines = ["已定义的 Team:"]
            for name in teams:
                tdef = load_team_def(name)
                if tdef:
                    count = len(tdef.members)
                    lines.append(f"  {name} — {tdef.description} ({count} 成员)")
            return "\n".join(lines)

        elif args[0] == "show":
            if len(args) < 2:
                return "用法: /team show <名称>"
            tdef = load_team_def(args[1])
            if tdef is None:
                return f"Team '{args[1]}' 不存在"
            members = "\n".join(
                f"  - {m.name} (role={m.role}, backend={m.backend}, wt={m.worktree})"
                for m in tdef.members
            )
            return (
                f"Team: {tdef.name}\n描述: {tdef.description}\n"
                f"Lead 角色: {tdef.lead_role}\n调度模式: {tdef.dispatch_mode}\n\n"
                f"成员:\n{members}"
            )

        elif args[0] == "dir":
            if len(args) < 2:
                return "用法: /team dir <名称>"
            d = get_team_dir(args[1])
            return f"Team 工作目录: {d}"

        return f"未知子命令: {args[0]}。可用: list, show, dir"

    return CommandMeta(
        name="team",
        aliases=["tm"],
        description="管理 Agent Team（list / show / dir）",
        usage="/team [list | show <名称> | dir <名称>]",
        cmd_type=CommandType.LOCAL,
        handler=handler,
    )
