"""Check-in commands for the user-scoped public API."""

import click

from dailybot_cli.commands.public_api_helpers import require_auth
from dailybot_cli.commands.user_scoped_actions import execute_checkin_complete, execute_checkin_list

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
