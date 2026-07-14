"""Kudos commands for the user-scoped public API."""

from typing import Any

import click

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    EXIT_PERMISSION_DENIED,
    EXIT_USAGE_ERROR,
    confirm_write,
    emit_json,
    enforce_plan_access,
    exit_for_api_error,
    get_current_user_uuid,
    require_auth,
    resolve_team_by_name_or_uuid,
    resolve_user_by_name_or_uuid,
)
from dailybot_cli.commands.query_options import build_query_params, query_options, resolve_fetch_all
from dailybot_cli.display import (
    console,
    print_error,
    print_kudos_result,
    print_kudos_table,
    print_kudos_wall_of_fame,
    print_pagination_footer,
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


_KUDOS_FILTER_ALIASES: dict[str, str] = {
    "kudos_received": "kudos_received",
    "received": "kudos_received",
    "kudos_given": "kudos_given",
    "given": "kudos_given",
}


def normalize_kudos_filter(value: str | None) -> str | None:
    """Map a friendly ``--filter`` value to the token the API accepts.

    The API accepts only lowercase ``kudos_received`` / ``kudos_given``. The CLI
    has long advertised the uppercase ``KUDOS_RECEIVED`` / ``KUDOS_GIVEN`` forms,
    which the server rejects with ``400 "Not valid kudos filter"``. Unknown
    values pass through so the server stays the source of truth.
    """
    if value is None:
        return None
    return _KUDOS_FILTER_ALIASES.get(value.strip().lower(), value.strip())


@kudos.command("list")
@click.option(
    "--filter",
    "kudos_filter",
    default=None,
    help="Filter direction: received or given (KUDOS_RECEIVED / KUDOS_GIVEN also accepted).",
)
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def kudos_list(
    kudos_filter: str | None,
    page: int | None,
    page_size: int | None,
    fetch_all: bool,
    limit: int | None,
    search: str | None,
    since: str | None,
    until: str | None,
    on_date: str | None,
    last_week: bool,
    today: bool,
    json_mode: bool,
) -> None:
    """List kudos in your organization.

    \b
    Examples:
      dailybot kudos list
      dailybot kudos list --filter KUDOS_RECEIVED --since 2026-07-01
      dailybot kudos list --all --json
    """
    enforce_plan_access("kudos_list", json_mode=json_mode)
    try:
        spec = build_query_params(
            page=page,
            page_size=page_size,
            fetch_all=fetch_all,
            limit=limit,
            search=search,
            since=since,
            until=until,
            on_date=on_date,
            last_week=last_week,
            today=today,
        )
    except ValueError as exc:
        print_error(str(exc))
        raise SystemExit(EXIT_USAGE_ERROR)
    client = require_auth()
    resolved_fetch_all: bool = resolve_fetch_all(spec)
    meta: dict[str, Any] = {}
    try:
        with console.status("Fetching kudos..."):
            kudos_items: list[dict[str, Any]] = client.list_kudos(
                kudos_filter=normalize_kudos_filter(kudos_filter),
                search=spec.params.get("search"),
                start_date=spec.params.get("start_date"),
                end_date=spec.params.get("end_date"),
                page=spec.page,
                page_size=spec.page_size,
                fetch_all=resolved_fetch_all,
                limit=spec.limit,
                meta=meta,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(kudos_items)
        return
    print_kudos_table(kudos_items)
    print_pagination_footer(len(kudos_items), meta.get("count"), has_more=bool(meta.get("next")))


@kudos.command("org")
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def kudos_org(
    json_mode: bool,
    page: int | None,
    page_size: int | None,
    fetch_all: bool,
    limit: int | None,
    search: str | None,
    since: str | None,
    until: str | None,
    on_date: str | None,
    last_week: bool,
    today: bool,
) -> None:
    """Browse every kudos in the organization (admin only).

    \b
    The org-wide feed. `kudos list` shows only the ones you gave or received.
    Non-admins receive a 403.

    \b
    Examples:
      dailybot kudos org
      dailybot kudos org --page-size 20 --since 2026-07-01
      dailybot kudos org --search onboarding --json
    """
    enforce_plan_access("kudos_org", json_mode=json_mode)
    try:
        spec = build_query_params(
            page=page,
            page_size=page_size,
            fetch_all=fetch_all,
            limit=limit,
            search=search,
            since=since,
            until=until,
            on_date=on_date,
            last_week=last_week,
            today=today,
        )
    except ValueError as exc:
        print_error(str(exc))
        raise SystemExit(EXIT_USAGE_ERROR)
    client = require_auth()
    meta: dict[str, Any] = {}
    try:
        with console.status("Fetching organization kudos..."):
            kudos_items: list[dict[str, Any]] = client.list_kudos_organization(
                search=spec.params.get("search"),
                start_date=spec.params.get("start_date"),
                end_date=spec.params.get("end_date"),
                page=spec.page,
                page_size=spec.page_size,
                fetch_all=resolve_fetch_all(spec),
                limit=spec.limit,
                meta=meta,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(kudos_items)
        return
    print_kudos_table(kudos_items)
    print_pagination_footer(len(kudos_items), meta.get("count"), has_more=bool(meta.get("next")))


@kudos.command("wall-of-fame")
@click.option("--limit", "-l", type=int, default=None, help="Limit leaderboard entries.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def kudos_wall_of_fame(limit: int | None, json_mode: bool) -> None:
    """Show the kudos leaderboard (wall of fame).

    \b
    Examples:
      dailybot kudos wall-of-fame
      dailybot kudos wall-of-fame --limit 10 --json
    """
    enforce_plan_access("kudos_wall_of_fame", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Fetching wall of fame..."):
            data: dict[str, Any] = client.get_kudos_wall_of_fame(limit=limit)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_kudos_wall_of_fame(data)
