"""Kudos commands for the user-scoped public API."""

from typing import Any

import click

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import (
    USER_SCOPED_MODEL_HELP,
    confirm_write,
    emit_json,
    exit_for_api_error,
    get_current_user_uuid,
    require_bearer_auth,
    resolve_user_by_name_or_uuid,
    EXIT_PERMISSION_DENIED,
    EXIT_USAGE_ERROR,
)
from dailybot_cli.display import (
    console,
    print_error,
    print_kudos_result,
)


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
    required=True,
    help="Receiver full name or UUID (resolved via GET /v1/users/).",
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
    receiver: str,
    message: str,
    value: str | None,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    """Give kudos to a teammate.

    \b
    {help}

    Receivers are resolved by name against your organization directory — never guessed.

    \b
    Examples:
      dailybot kudos give --to "Jane Doe" --message "Great release work!"
      dailybot kudos give --to <user_uuid> --message "Thanks!" --yes
    """.format(help=USER_SCOPED_MODEL_HELP)
    client = require_bearer_auth()

    try:
        with console.status("Resolving receiver..."):
            users: list[dict[str, Any]] = client.list_users()
            receiver_uuid, receiver_name = resolve_user_by_name_or_uuid(users, receiver)
            current_uuid: str | None = get_current_user_uuid(client)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    except ValueError as exc:
        if json_mode:
            emit_json({"error": str(exc), "status": 0})
        else:
            print_error(str(exc))
        raise SystemExit(EXIT_USAGE_ERROR) from exc

    if current_uuid and receiver_uuid == current_uuid:
        error_message: str = "You cannot give kudos to yourself."
        if json_mode:
            emit_json({"error": error_message, "status": 403})
        else:
            print_error(error_message)
        raise SystemExit(EXIT_PERMISSION_DENIED)

    summary_lines: list[str] = [
        f"To: {receiver_name}",
        f"Receiver UUID: {receiver_uuid}",
        f"Message: {message}",
    ]
    if value:
        summary_lines.append(f"Company value: {value}")

    confirm_write(summary_lines, assume_yes)

    try:
        with console.status("Sending kudos..."):
            result: dict[str, Any] = client.give_kudos(
                receivers=[receiver_uuid],
                content=message,
                company_value=value,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return

    print_kudos_result(receiver_name, result)
