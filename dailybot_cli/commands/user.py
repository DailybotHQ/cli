"""User directory commands for the user-scoped public API."""

import click

from dailybot_cli.commands.public_api_helpers import require_bearer_auth
from dailybot_cli.commands.user_scoped_actions import execute_user_list


@click.group()
def user() -> None:
    """Browse your organization with your Dailybot session.

    \b
    Acts as you — visibility and permissions match the webapp for your account.
    """


@user.command("list")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def user_list(json_mode: bool) -> None:
    """List team members in your organization.

    \b
    Acts as you. You can only see and act on what you could in the webapp.

    \b
    Examples:
      dailybot user list
      dailybot user list --json
    """
    client = require_bearer_auth()
    execute_user_list(client, json_mode=json_mode)
