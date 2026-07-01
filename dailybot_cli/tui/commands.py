from typing import Final

COMMAND_CHECKINS: Final[str] = "checkins"
COMMAND_CLEAR: Final[str] = "clear"
COMMAND_EXIT: Final[str] = "exit"
COMMAND_HELP: Final[str] = "help"
COMMAND_QUIT: Final[str] = "quit"
COMMAND_REPORT: Final[str] = "report"
COMMAND_STATUS: Final[str] = "status"

EXIT_COMMANDS: Final[set[str]] = {COMMAND_EXIT, COMMAND_QUIT}
KNOWN_COMMANDS: Final[set[str]] = {
    COMMAND_CHECKINS,
    COMMAND_CLEAR,
    COMMAND_EXIT,
    COMMAND_HELP,
    COMMAND_QUIT,
    COMMAND_REPORT,
    COMMAND_STATUS,
}

HELP_TEXT: Final[str] = """Commands
/help - Show this help.
/clear - Clear the local terminal transcript.
/status - Show the current login/session status.
/checkins - Show pending check-ins.
/report - Submit a free-text progress update.
/exit - Leave the session.

Natural language goes to Dailybot.
"""


def parse_command(raw_value: str) -> str | None:
    """Return a normalized slash command, or None for normal chat text."""
    value: str = raw_value.strip()
    if not value.startswith("/"):
        return None
    command: str = value[1:].split(maxsplit=1)[0].lower()
    return command or COMMAND_HELP
