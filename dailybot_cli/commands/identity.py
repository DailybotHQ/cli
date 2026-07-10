"""Identity read commands: `me` and `org` (whoami / organization context)."""

from typing import Any

import click

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    enforce_plan_access,
    exit_for_api_error,
    require_auth,
)
from dailybot_cli.display import console, print_detail_panel

_ME_FIELDS: list[tuple[str, str]] = [
    ("Name", "full_name"),
    ("Role", "role"),
    ("Email", "email"),
    ("Organization", "organization_name"),
    ("Org UUID", "organization_uuid"),
    ("Timezone", "timezone"),
    ("UUID", "uuid"),
]

_ORG_FIELDS: list[tuple[str, str]] = [
    ("Name", "name"),
    ("UUID", "uuid"),
    ("Platform", "platform"),
    ("Timezone", "timezone"),
]


@click.command(name="me")
@click.option("--include-email", is_flag=True, help="Include your email address.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def me(include_email: bool, json_mode: bool) -> None:
    """Show the authenticated user and organization context.

    \b
    Examples:
      dailybot me
      dailybot me --include-email --json
    """
    enforce_plan_access("me", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Fetching your profile..."):
            data: dict[str, Any] = client.get_me(include_email=include_email)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_detail_panel("You", data, _ME_FIELDS)


@click.command(name="org")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def org(json_mode: bool) -> None:
    """Show the organization the current credential is scoped to.

    \b
    Examples:
      dailybot org
      dailybot org --json
    """
    enforce_plan_access("organization", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Fetching organization..."):
            data: dict[str, Any] = client.get_organization()
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_detail_panel("Organization", data, _ORG_FIELDS)
