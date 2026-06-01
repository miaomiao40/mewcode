"""Session command — list, load, new, delete."""

from mewcode.commands.types import CommandMeta, CommandType, UIControl


def create(ui: UIControl) -> CommandMeta:
    async def handler(args: list[str]) -> str:
        if not args or args[0] == "list":
            sessions = ui.get_session_list()
            if not sessions:
                return "没有保存的会话"
            lines = ["会话列表:"]
            for s in sessions[:20]:
                sid = s.get("id", "?")[:12]
                title = s.get("title", "无标题")[:50]
                count = s.get("message_count", 0)
                last = s.get("last_active_at", "")[:16]
                lines.append(f"  {sid}  {title}  ({count} 条消息, {last})")
            lines.append("\n/session load <ID> 加载 | /session delete <ID> 删除")
            return "\n".join(lines)

        elif args[0] == "load":
            if len(args) < 2:
                return "用法: /session load <会话ID>"
            return ui.load_session(args[1])

        elif args[0] == "delete":
            if len(args) < 2:
                return "用法: /session delete <会话ID>"
            return ui.delete_session(args[1])

        elif args[0] == "new":
            return ui.new_session()

        return f"未知子命令: {args[0]}。可用: list, load, delete, new"

    return CommandMeta(
        name="session",
        aliases=["sess"],
        description="管理会话（list / load / delete / new）",
        usage="/session [list | load <id> | delete <id> | new]",
        cmd_type=CommandType.UI,
        handler=handler,
    )
