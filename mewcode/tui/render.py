"""Message rendering helpers for the TUI."""

from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style

USER_PREFIX = "\n\nYou: "
AI_PREFIX = "\n\nMewCode: "
THINKING_PREFIX = ""  # prefix is now generated dynamically by app.py

#: Style sheet applied to the conversation display.
STYLE = Style.from_dict(
    {
        "user-prefix": "bold green",
        "ai-prefix": "bold blue",
        "thinking": "fg:#888888 italic",
        "error": "fg:#ff4444 bold",
        "info": "fg:#aaaaaa",
        "warning": "fg:#ffaa00",
    }
)


def format_user_message(text: str) -> FormattedText:
    """Format a user message for display."""
    return FormattedText([
        ("class:user-prefix", USER_PREFIX),
        ("", text),
    ])


def format_ai_message(text: str) -> FormattedText:
    """Format an AI assistant message for display."""
    return FormattedText([
        ("class:ai-prefix", AI_PREFIX),
        ("", text),
    ])


def format_thinking(text: str) -> FormattedText:
    """Format a thinking block for display."""
    return FormattedText([
        ("class:thinking", THINKING_PREFIX + text),
    ])


def format_error(text: str) -> FormattedText:
    """Format an error message for display."""
    return FormattedText([
        ("class:error", f"\n\nError: {text}"),
    ])


def format_info(text: str) -> FormattedText:
    """Format an informational system message."""
    return FormattedText([
        ("class:info", f"\n{text}"),
    ])


def format_warning(text: str) -> FormattedText:
    """Format a warning message."""
    return FormattedText([
        ("class:warning", f"\n⚠ {text}"),
    ])
