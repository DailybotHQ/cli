"""User directory commands for the user-scoped public API."""

import click

from dailybot_cli.commands.public_api_helpers import require_auth
from dailybot_cli.commands.user_scoped_actions import execute_user_list


@click.group()
def user() -> None:
    """Browse your organization with your Dailybot session.

    \b
    Acts as you — visibility and permissions match the webapp for your account.
    """


@user.command("list")
@click.option(
    "--include-inactive",
    is_flag=True,
    help="Also include deactivated members (default: active members only).",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def user_list(include_inactive: bool, json_mode: bool) -> None:
    """List team members in your organization.

    \b
    Acts as you. You can only see and act on what you could in the webapp.
    By default only active members are listed; pass --include-inactive to
    include deactivated accounts (useful for admin / audit flows).

    \b
    Examples:
      dailybot user list
      dailybot user list --include-inactive
      dailybot user list --json
    """
    client = require_auth()
    execute_user_list(client, json_mode=json_mode, include_inactive=include_inactive)
