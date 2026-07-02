from typing import Final

COMMAND_CHECKINS: Final[str] = "checkins"
COMMAND_CLEAR: Final[str] = "clear"
COMMAND_DASHBOARD: Final[str] = "dashboard"
COMMAND_EXIT: Final[str] = "exit"
COMMAND_FORM: Final[str] = "form"
COMMAND_FORMS: Final[str] = "forms"
COMMAND_HELP: Final[str] = "help"
COMMAND_KUDOS: Final[str] = "kudos"
COMMAND_MOOD: Final[str] = "mood"
COMMAND_QUIT: Final[str] = "quit"
COMMAND_REPORT: Final[str] = "report"
COMMAND_STATUS: Final[str] = "status"
COMMAND_TEAM: Final[str] = "team"
COMMAND_TEAMS: Final[str] = "teams"
COMMAND_TIMEOFF: Final[str] = "timeoff"
COMMAND_USERS: Final[str] = "users"

EXIT_COMMANDS: Final[set[str]] = {COMMAND_EXIT, COMMAND_QUIT}
KNOWN_COMMANDS: Final[set[str]] = {
    COMMAND_CHECKINS,
    COMMAND_CLEAR,
    COMMAND_DASHBOARD,
    COMMAND_EXIT,
    COMMAND_FORM,
    COMMAND_FORMS,
    COMMAND_HELP,
    COMMAND_KUDOS,
    COMMAND_MOOD,
    COMMAND_QUIT,
    COMMAND_REPORT,
    COMMAND_STATUS,
    COMMAND_TEAM,
    COMMAND_TEAMS,
    COMMAND_TIMEOFF,
    COMMAND_USERS,
}

HELP_TEXT: Final[str] = """Commands
/help - Show this help.
/clear - Clear the local terminal transcript.
/status - Show login status and pending check-ins.
/dashboard - Show the Dailybot dashboard link.
/checkins - Complete pending check-ins.
/checkin edit - Edit today's submitted check-in.
/checkin reset - Delete today's submitted check-in after confirmation.
/kudos - Send kudos to users or teams.
/forms - List forms and choose an action.
/form submit - Submit a form response.
/form responses - Browse your form responses.
/form update - Update one of your form responses.
/form transition - Move a workflow form response.
/form delete - Delete a form response after confirmation.
/users - Browse organization members.
/teams - Browse teams.
/team - Pick a team and show its members.
/mood - Track today's mood.
/report - Submit a free-text progress update.
/timeoff - Time-off native flow is not available in this terminal yet.
/exit - Leave the session.

Natural language goes to Dailybot.
"""

TERMINAL_COMMANDS: Final[list[dict[str, str]]] = [
    {"name": "/help", "description": "Show the command catalog."},
    {"name": "/clear", "description": "Clear the local terminal transcript."},
    {"name": "/status", "description": "Show login status and pending check-ins."},
    {"name": "/dashboard", "description": "Show the Dailybot dashboard URL."},
    {"name": "/checkins", "description": "Complete pending check-ins with numbered prompts."},
    {"name": "/checkin edit", "description": "Edit today's submitted check-in answers."},
    {"name": "/checkin reset", "description": "Delete today's submitted check-in response after confirmation."},
    {"name": "/kudos", "description": "Send kudos to users or teams from the terminal."},
    {"name": "/forms", "description": "List forms and submit or manage responses."},
    {"name": "/form submit", "description": "Submit a form response question by question."},
    {"name": "/form responses", "description": "Browse form responses visible to the user."},
    {"name": "/form update", "description": "Update a form response question by question."},
    {"name": "/form transition", "description": "Move a workflow form response to an allowed state."},
    {"name": "/form delete", "description": "Delete a form response after confirmation."},
    {"name": "/users", "description": "Browse organization members."},
    {"name": "/teams", "description": "Browse teams."},
    {"name": "/team", "description": "Show details and members for a team."},
    {"name": "/mood", "description": "Track today's mood score."},
    {"name": "/report", "description": "Submit a free-text progress update."},
    {"name": "/timeoff", "description": "Explain time-off terminal flow availability."},
    {"name": "/exit", "description": "Leave the session."},
]
COMMAND_COMPLETIONS: Final[list[str]] = [command["name"] for command in TERMINAL_COMMANDS]


def parse_command(raw_value: str) -> str | None:
    """Return a normalized slash command, or None for normal chat text."""
    value: str = raw_value.strip()
    if not value.startswith("/"):
        return None
    command: str = value[1:].split(maxsplit=1)[0].lower()
    return command or COMMAND_HELP


def parse_command_args(raw_value: str) -> list[str]:
    """Return slash-command arguments without the command itself."""
    value: str = raw_value.strip()
    if not value.startswith("/"):
        return []
    parts: list[str] = value[1:].split()
    return parts[1:]
