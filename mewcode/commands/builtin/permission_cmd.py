"""Permission command — show security rules."""

from mewcode.commands.types import CommandMeta, CommandType, UIControl
from mewcode.security.models import SecurityLevel


def create(ui: UIControl) -> CommandMeta:
    async def handler(args: list[str]) -> str:
        return (
            f"当前安全等级: {ui.get_security_level()}\n"
            f"可用操作:\n"
            f"  /mode security <strict|normal|permissive>  切换等级\n"
            f"  项目规则: .mewcode-security.yaml\n"
        )

    return CommandMeta(
        name="permission",
        aliases=["perm", "acl"],
        description="查看安全权限状态",
        usage="/permission",
        cmd_type=CommandType.LOCAL,
        handler=handler,
    )
