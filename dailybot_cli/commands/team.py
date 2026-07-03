"""Team directory commands for the user-scoped public API."""

from typing import Any

import click

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    EXIT_USAGE_ERROR,
    emit_json,
    exit_for_api_error,
    print_error,
    require_auth,
    resolve_team_by_name_or_uuid,
)
from dailybot_cli.display import (
    console,
    print_team_detail,
    print_teams_table,
)


def _resolve_team_arg(
    client: DailyBotClient,
    identifier: str,
    *,
    json_mode: bool,
) -> tuple[str, str]:
    """Return (team_uuid, team_name) from a UUID or name. Exits on failure."""
    try:
        teams: list[dict[str, Any]] = client.list_teams()
        return resolve_team_by_name_or_uuid(teams, identifier)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    except ValueError as exc:
        if json_mode:
            emit_json({"error": str(exc), "status": 0})
        else:
            print_error(str(exc))
        raise SystemExit(EXIT_USAGE_ERROR) from exc


@click.group()
def team() -> None:
    """Browse teams with your Dailybot session.

    \b
    Acts as you — visibility is scoped server-side by your role.
    Admins see all org teams; members see only their own.
    """


@team.command("list")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def team_list(json_mode: bool) -> None:
    """List teams visible to you.

    \b
    Visibility is enforced server-side by GET /v1/teams/. The CLI shows the
    server's response verbatim — no client-side filter.

    \b
    Examples:
      dailybot team list
      dailybot team list --json
    """
    client = require_auth()
    try:
        with console.status("Fetching teams..."):
            teams: list[dict[str, Any]] = client.list_teams()
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(teams)
        return
    print_teams_table(teams)


@team.command("get")
@click.argument("team_identifier")
@click.option(
    "--with-members",
    is_flag=True,
    help="Also fetch and display the team's member list.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def team_get(team_identifier: str, with_members: bool, json_mode: bool) -> None:
    """Get a single team by UUID or name (case-insensitive).

    \b
    Examples:
      dailybot team get <team_uuid>
      dailybot team get "Engineering"
      dailybot team get "Engineering" --with-members --json
    """
    client = require_auth()
    team_uuid, _team_name = _resolve_team_arg(client, team_identifier, json_mode=json_mode)

    try:
        with console.status("Loading team..."):
            data: dict[str, Any] = client.get_team(team_uuid)
            members: list[dict[str, Any]] | None = None
            if with_members:
                members = client.list_team_members(team_uuid)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        payload: dict[str, Any] = dict(data)
        if members is not None:
            payload["members"] = members
        emit_json(payload)
        return

    print_team_detail(data, members)
