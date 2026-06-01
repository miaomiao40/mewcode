"""Session command — list, switch, new session."""

from mewcode.commands.types import CommandMeta, CommandType, UIControl


def create(ui: UIControl) -> CommandMeta:
    async def handler(args: list[str]) -> str:
        if not args or args[0] == "list":
            sessions = ui.get_session_list()
            if not sessions:
                return "没有保存的会话"
            lines = ["会话列表:"]
            for s in sessions[:20]:
                sid = s.get("id", "?")[:8]
                title = s.get("title", "无标题")[:50]
                count = s.get("message_count", 0)
                last = s.get("last_active_at", "")[:16]
                lines.append(f"  {sid}  {title}  ({count} 条消息, {last})")
            return "\n".join(lines)

        elif args[0] == "new":
            return "新会话已创建（重启后生效）"

        elif args[0] == "switch":
            if len(args) < 2:
                return "用法: /session switch <会话ID>"
            return ui.switch_session(args[1])

        return f"未知子命令: {args[0]}。可用: list, new, switch"

    return CommandMeta(
        name="session",
        aliases=["sess"],
        description="管理会话（list / new / switch）",
        usage="/session [list | new | switch <id>]",
        cmd_type=CommandType.UI,
        handler=handler,
    )
