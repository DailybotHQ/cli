"""Check-in commands for the user-scoped public API."""

import sys

import click

from dailybot_cli.commands.public_api_helpers import require_auth
from dailybot_cli.commands.user_scoped_actions import (
    execute_checkin_complete,
    execute_checkin_edit,
    execute_checkin_history,
    execute_checkin_list,
    execute_checkin_reset,
    execute_checkin_show,
    execute_checkin_status,
)

_HELP: str = "Acts as you. You can only see and act on what you could in the webapp."


@click.group()
def checkin() -> None:
    """Manage check-ins with your Dailybot session.

    \b
    Acts as you — visibility and permissions match the webapp for your account.
    """


@checkin.command("list")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_list(json_mode: bool) -> None:
    """List pending check-ins for today.

    \b
    Acts as you. You can only see and act on what you could in the webapp.

    \b
    Examples:
      dailybot checkin list
      dailybot checkin list --json
    """
    client = require_auth()
    execute_checkin_list(client, json_mode=json_mode)


@checkin.command("complete")
@click.argument("followup_uuid")
@click.option(
    "--answer",
    "-a",
    multiple=True,
    help='Answer as "index=response" (0-based). Prompts when omitted.',
)
@click.option(
    "--response-date",
    default=None,
    help="Target a specific day (YYYY-MM-DD). Defaults to today.",
)
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_complete(
    followup_uuid: str,
    answer: tuple[str, ...],
    response_date: str | None,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    """Complete a pending check-in.

    \b
    Acts as you. You can only see and act on what you could in the webapp.

    \b
    Examples:
      dailybot checkin complete <followup_uuid>
      dailybot checkin complete <followup_uuid> -a 0="Shipped auth" -a 1="Reviewing migrations"
      dailybot checkin complete <followup_uuid> --yes
    """
    client = require_auth()
    execute_checkin_complete(
        client,
        followup_uuid,
        answer_flags=answer,
        response_date=response_date,
        assume_yes=assume_yes,
        json_mode=json_mode,
    )


@checkin.command("status")
@click.option(
    "--date", "date", default=None, help="Target a specific day (YYYY-MM-DD). Defaults to today."
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_status(date: str | None, json_mode: bool) -> None:
    """Show pending/completed status for your check-ins on a date.

    \b
    Examples:
      dailybot checkin status
      dailybot checkin status --date 2026-07-01 --json
    """
    client = require_auth()
    execute_checkin_status(client, date=date, json_mode=json_mode)


@checkin.command("show")
@click.argument("followup_uuid")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_show(followup_uuid: str, json_mode: bool) -> None:
    """Show a check-in's configuration and questions.

    \b
    Examples:
      dailybot checkin show <followup_uuid>
      dailybot checkin show <followup_uuid> --json
    """
    client = require_auth()
    execute_checkin_show(client, followup_uuid, json_mode=json_mode)


@checkin.command("history")
@click.argument("followup_uuid")
@click.option("--days", type=int, default=None, help="Look back N days from today.")
@click.option("--from", "date_from", default=None, help="Range start (YYYY-MM-DD).")
@click.option("--to", "date_to", default=None, help="Range end (YYYY-MM-DD).")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_history(
    followup_uuid: str,
    days: int | None,
    date_from: str | None,
    date_to: str | None,
    json_mode: bool,
) -> None:
    """Show your response history for a check-in.

    \b
    Examples:
      dailybot checkin history <followup_uuid> --days 7
      dailybot checkin history <followup_uuid> --from 2026-06-01 --to 2026-06-30 --json
    """
    client = require_auth()
    execute_checkin_history(
        client,
        followup_uuid,
        days=days,
        date_from=date_from,
        date_to=date_to,
        json_mode=json_mode,
    )


@checkin.command("reset")
@click.argument("followup_uuid")
@click.option("--date", "response_date", default=None, help="Target a specific day (YYYY-MM-DD).")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_reset(
    followup_uuid: str,
    response_date: str | None,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    """Delete (reset) your check-in response for a day.

    \b
    Examples:
      dailybot checkin reset <followup_uuid>
      dailybot checkin reset <followup_uuid> --date 2026-07-01 --yes
    """
    client = require_auth()
    execute_checkin_reset(
        client,
        followup_uuid,
        response_date=response_date,
        assume_yes=assume_yes,
        json_mode=json_mode,
    )


@checkin.command("edit")
@click.argument("followup_uuid")
@click.option(
    "--answer", "-a", multiple=True, help='Override an answer as "index=response" (0-based).'
)
@click.option("--date", "response_date", default=None, help="Target a specific day (YYYY-MM-DD).")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_edit(
    followup_uuid: str,
    answer: tuple[str, ...],
    response_date: str | None,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    """Edit an existing check-in response.

    \b
    With -a flags (or when a terminal is attached, prompts per question showing
    the current answer as the default).

    \b
    Examples:
      dailybot checkin edit <followup_uuid> -a 0="Updated answer" --yes
      dailybot checkin edit <followup_uuid>   # prompts each question
    """
    client = require_auth()
    execute_checkin_edit(
        client,
        followup_uuid,
        answer_flags=answer,
        response_date=response_date,
        assume_yes=assume_yes,
        json_mode=json_mode,
        interactive=(not answer and not json_mode and sys.stdin.isatty()),
    )
