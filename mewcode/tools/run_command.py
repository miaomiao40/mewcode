"""Run command tool — execute a shell command safely."""

import asyncio
from pathlib import Path

from mewcode.tools.base import BaseTool, ToolParameter, ToolResult

# Commands that are never allowed
_BLOCKED_COMMANDS = {
    "rm", "sudo", "chmod", "chown", "su", "shutdown", "reboot",
    "mkfs", "dd", ":(){",  # fork bomb pattern
}

# Commands that require no arguments to be interactive
_INTERACTIVE_COMMANDS = {
    "vim", "vi", "nano", "emacs", "ssh", "telnet", "top", "htop",
    "less", "more", "man",
}

OUTPUT_LIMIT = 10_000  # max chars of stdout/stderr to return


class RunCommandTool(BaseTool):
    """Execute a shell command within the project directory."""

    @property
    def name(self) -> str:
        return "run_command"

    @property
    def description(self) -> str:
        return (
            "在工作目录中执行一条 shell 命令。"
            "输出有长度限制，超出会截断。"
            "禁止交互式命令和危险命令（rm/sudo/chmod 等）。"
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter("command", "string", "要执行的 shell 命令。"),
        ]

    async def execute(self, command: str) -> ToolResult:
        cmd_name = command.strip().split()[0] if command.strip() else ""

        # Block dangerous commands
        if cmd_name in _BLOCKED_COMMANDS:
            return ToolResult(
                success=False,
                content="",
                error=f"禁止执行危险命令: {cmd_name}",
            )
        if cmd_name in _INTERACTIVE_COMMANDS:
            return ToolResult(
                success=False,
                content="",
                error=f"禁止交互式命令: {cmd_name}",
            )

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(Path.cwd()),
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=30.0
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                content="",
                error="命令执行超时（30s）",
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                content="",
                error=f"命令执行异常: {type(exc).__name__}: {exc}",
            )

        stdout = stdout_bytes.decode("utf-8", errors="replace")[:OUTPUT_LIMIT]
        stderr = stderr_bytes.decode("utf-8", errors="replace")[:OUTPUT_LIMIT]
        truncated = len(stdout) >= OUTPUT_LIMIT or len(stderr) >= OUTPUT_LIMIT

        result_lines = []
        if proc.returncode == 0:
            result_lines.append(f"退出码: 0")
        else:
            result_lines.append(f"退出码: {proc.returncode}（非零）")
        result_lines.append(f"\n--- stdout ---\n{stdout or '(无输出)'}")
        if stderr:
            result_lines.append(f"\n--- stderr ---\n{stderr}")
        if truncated:
            result_lines.append("\n(输出已截断)")

        return ToolResult(
            success=proc.returncode == 0,
            content="\n".join(result_lines),
        )
