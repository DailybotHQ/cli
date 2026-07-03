"""Kudos commands for the user-scoped public API."""

from typing import Any

import click

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    EXIT_PERMISSION_DENIED,
    EXIT_USAGE_ERROR,
    confirm_write,
    emit_json,
    exit_for_api_error,
    get_current_user_uuid,
    require_auth,
    resolve_team_by_name_or_uuid,
    resolve_user_by_name_or_uuid,
)
from dailybot_cli.display import (
    console,
    print_error,
    print_kudos_result,
)


def execute_kudos_give(
    client: DailyBotClient,
    message: str,
    *,
    user_receivers: list[tuple[str, str]] | None = None,
    team_receivers: list[tuple[str, str]] | None = None,
    current_uuid: str | None = None,
    value: str | None = None,
    assume_yes: bool = False,
    json_mode: bool = False,
    receiver_uuid: str | None = None,
    receiver_name: str | None = None,
) -> None:
    """Send kudos with already-resolved user / team receivers.

    ``receiver_uuid`` / ``receiver_name`` are a legacy single-user shortcut kept
    for interactive mode; new callers should use ``user_receivers`` /
    ``team_receivers`` lists of (uuid, display_name) pairs.
    """
    users: list[tuple[str, str]] = list(user_receivers or [])
    teams: list[tuple[str, str]] = list(team_receivers or [])

    if receiver_uuid:
        users.append((receiver_uuid, receiver_name or receiver_uuid))

    if current_uuid:
        for user_uuid, _name in users:
            if user_uuid == current_uuid:
                error_message: str = "You cannot give kudos to yourself."
                if json_mode:
                    emit_json({"error": error_message, "status": 403})
                else:
                    print_error(error_message)
                raise SystemExit(EXIT_PERMISSION_DENIED)

    if not users and not teams:
        error_message = "At least one --to or --team receiver is required."
        if json_mode:
            emit_json({"error": error_message, "status": 0})
        else:
            print_error(error_message)
        raise SystemExit(EXIT_USAGE_ERROR)

    summary_lines: list[str] = []
    if users:
        summary_lines.append("Users:")
        for user_uuid, name in users:
            summary_lines.append(f"  - {name} ({user_uuid})")
    if teams:
        summary_lines.append("Teams:")
        for team_uuid, team_name in teams:
            summary_lines.append(f"  - {team_name} ({team_uuid})")
    summary_lines.append(f"Message: {message}")
    if value:
        summary_lines.append(f"Company value: {value}")

    confirm_write(summary_lines, assume_yes)

    try:
        with console.status("Sending kudos..."):
            result: dict[str, Any] = client.give_kudos(
                content=message,
                user_uuid_receivers=[u for u, _ in users] or None,
                team_uuid_receivers=[t for t, _ in teams] or None,
                company_value=value,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return

    label_parts: list[str] = [name for _, name in users] + [f"team {name}" for _, name in teams]
    print_kudos_result(", ".join(label_parts) or "receiver", result)


@click.group()
def kudos() -> None:
    """Give kudos with your Dailybot session.

    \b
    Acts as you — visibility and permissions match the webapp for your account.
    """


@kudos.command("give")
@click.option(
    "--to",
    "-t",
    "receiver",
    default=None,
    help="User full name or UUID (resolved via GET /v1/users/).",
)
@click.option(
    "--team",
    "team_identifier",
    default=None,
    help="Team name or UUID (resolved via GET /v1/teams/).",
)
@click.option(
    "--message",
    "-m",
    required=True,
    help="Kudos message (team-visible).",
)
@click.option(
    "--value",
    default=None,
    help="Optional company value UUID.",
)
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def kudos_give(
    receiver: str | None,
    team_identifier: str | None,
    message: str,
    value: str | None,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    """Give kudos to a teammate, a team, or both.

    \b
    Acts as you. You can only see and act on what you could in the webapp.

    Receivers are resolved by name against your organization directory — never
    guessed. Teams are scoped by your role server-side (admins see all teams,
    members see only their own).

    \b
    Examples:
      dailybot kudos give --to "Jane Doe" --message "Great release work!"
      dailybot kudos give --team "Engineering" --message "Shipped flawlessly"
      dailybot kudos give --to "Alice" --team "QA" --message "Both nailed it"
    """
    if not receiver and not team_identifier:
        message_err: str = "At least one of --to or --team is required."
        if json_mode:
            emit_json({"error": message_err, "status": 0})
        else:
            print_error(message_err)
        raise SystemExit(EXIT_USAGE_ERROR)

    client = require_auth()

    user_receivers: list[tuple[str, str]] = []
    team_receivers: list[tuple[str, str]] = []
    current_uuid: str | None = None

    try:
        if receiver:
            with console.status("Resolving user receiver..."):
                users: list[dict[str, Any]] = client.list_users()
                user_uuid, user_name = resolve_user_by_name_or_uuid(users, receiver)
                user_receivers.append((user_uuid, user_name))
                current_uuid = get_current_user_uuid(client)
        if team_identifier:
            with console.status("Resolving team receiver..."):
                teams: list[dict[str, Any]] = client.list_teams()
                team_uuid, team_name = resolve_team_by_name_or_uuid(teams, team_identifier)
                team_receivers.append((team_uuid, team_name))
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    except ValueError as exc:
        if json_mode:
            emit_json({"error": str(exc), "status": 0})
        else:
            print_error(str(exc))
        raise SystemExit(EXIT_USAGE_ERROR) from exc

    execute_kudos_give(
        client,
        message,
        user_receivers=user_receivers,
        team_receivers=team_receivers,
        current_uuid=current_uuid,
        value=value,
        assume_yes=assume_yes,
        json_mode=json_mode,
    )
