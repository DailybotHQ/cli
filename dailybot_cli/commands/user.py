"""User directory commands for the user-scoped public API."""

from typing import Any

import click

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_api_error,
    require_auth,
)
from dailybot_cli.commands.user_scoped_actions import execute_user_list
from dailybot_cli.display import console, print_detail_panel

_USER_FIELDS: list[tuple[str, str]] = [
    ("Name", "full_name"),
    ("Role", "role"),
    ("Email", "email"),
    ("Active", "is_active"),
    ("Timezone", "timezone"),
    ("UUID", "uuid"),
]


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


@user.command("get")
@click.argument("user_uuid")
@click.option("--include-email", is_flag=True, help="Include the user's email address.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def user_get(user_uuid: str, include_email: bool, json_mode: bool) -> None:
    """Show a single user's profile by UUID.

    \b
    Examples:
      dailybot user get <user_uuid>
      dailybot user get <user_uuid> --include-email --json
    """
    client = require_auth()
    try:
        with console.status("Fetching user..."):
            data: dict[str, Any] = client.get_user(user_uuid, include_email=include_email)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_detail_panel("User", data, _USER_FIELDS)
