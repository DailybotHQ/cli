"""``conversation`` command group — open a Slack group DM (MPIM) that includes
the Dailybot bot, and optionally post a message to it.

Wraps ``POST /v1/open-conversation/`` (Slack-only, org-admin-only, idempotent)
and chains the existing ``POST /v1/send-message/`` path with
``channel_type=group_chat`` when ``--message`` is given. Authenticated with a
login Bearer token or an org API key. Participants can be named by UUID, email,
or name — non-UUID identifiers are resolved client-side via ``GET /v1/users/``.
"""

from typing import Any, NoReturn

import click

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    UUID_PATTERN,
    emit_json,
    require_auth,
    resolve_user_by_name_or_uuid,
)
from dailybot_cli.display import (
    console,
    print_conversation_result,
    print_error,
)

GROUP_CHAT_TYPE: str = "group_chat"
MAX_CONVERSATION_PARTICIPANTS: int = 7  # Slack MPIM limit: 8 total, minus the bot


def _split_identifiers(values: tuple[str, ...]) -> list[str]:
    """Flatten repeatable and comma-separated option values into a clean list."""
    out: list[str] = []
    for value in values:
        out.extend(part.strip() for part in value.split(",") if part.strip())
    return out


def _resolve_participants(client: DailyBotClient, identifiers: list[str]) -> list[tuple[str, str]]:
    """Resolve each identifier (UUID, email, or name) to a (uuid, name) pair.

    The user directory is fetched only when at least one identifier is not a bare
    UUID, so an all-UUID call avoids the extra round-trip. Order is preserved and
    duplicate UUIDs are dropped (keeping the first occurrence).
    """
    needs_directory: bool = any(not UUID_PATTERN.match(ident) for ident in identifiers)
    directory: list[dict[str, Any]] = (
        client.list_users(include_email=True) if needs_directory else []
    )
    resolved: list[tuple[str, str]] = []
    seen: set[str] = set()
    for ident in identifiers:
        uuid, name = resolve_user_by_name_or_uuid(directory, ident)
        if uuid in seen:
            continue
        seen.add(uuid)
        resolved.append((uuid, name))
    return resolved


def _exit_for_conversation_error(exc: APIError, json_mode: bool) -> NoReturn:
    """Translate an open-conversation / send failure to a friendly message + exit."""
    code: str | None = getattr(exc, "code", None)
    if code == "open_conversation_not_supported" or exc.status_code == 406:
        message: str = "Group conversations are only supported for Slack workspaces."
    elif code == "one_or_more_users_not_found":
        message = "One or more users were not found or aren't active in your organization."
    elif code == "no_valid_users":
        message = "The participant list contains invalid user UUIDs."
    elif code == "conversation_too_many_participants":
        message = (
            f"Too many participants. Slack group DMs support at most "
            f"{MAX_CONVERSATION_PARTICIPANTS} users plus the Dailybot bot (8 total)."
        )
    elif code == "conversation_can_not_be_opened":
        message = "Slack rejected the request. A participant may be deactivated on the Slack side."
    elif exc.status_code == 403:
        message = "This command requires organization admin privileges."
    elif exc.status_code == 401:
        message = "Session expired. Run: dailybot login"
    elif exc.status_code == 429:
        message = "Rate limit exceeded. Wait a moment and try again."
    else:
        message = exc.detail
    if json_mode:
        payload: dict[str, Any] = {"error": message, "status": exc.status_code}
        if code:
            payload["code"] = code
        emit_json(payload)
    else:
        print_error(message)
    raise SystemExit(1)


@click.group(name="conversation")
def conversation() -> None:
    """Open Slack group DMs (with the Dailybot bot) and post to them.

    \b
    Slack only, organization admin only. Opens a private group DM (MPIM) that
    includes the Dailybot bot plus the users you name, then optionally posts a
    message. Opening is idempotent — the same set of users returns the same
    channel.
    """


@conversation.command("open")
@click.option(
    "--user",
    "--users",
    "-u",
    "users_raw",
    multiple=True,
    help="Participant by UUID, email, or name (repeatable or comma-separated).",
)
@click.option(
    "--email",
    "--emails",
    "-e",
    "emails_raw",
    multiple=True,
    help="Participant by email (repeatable or comma-separated); resolved to a UUID.",
)
@click.option(
    "--message",
    "-m",
    default=None,
    help="Optional message to post to the group right after opening it.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def conversation_open(
    users_raw: tuple[str, ...],
    emails_raw: tuple[str, ...],
    message: str | None,
    json_mode: bool,
) -> None:
    """Open (or fetch) a Slack group DM and optionally post a message.

    \b
    Slack only, org admin only. Idempotent — the same participants return the
    same channel. Participants accept UUID, email, or name; --emails is a
    convenience alias that only takes emails.

    \b
    Examples:
      dailybot conversation open -u <uuid1> -u <uuid2>
      dailybot conversation open -u Mauricio -m "Report on the latest analysis"
      dailybot conversation open --emails ana@co.com,luis@co.com --json
    """
    identifiers: list[str] = _split_identifiers(users_raw) + _split_identifiers(emails_raw)
    if not identifiers:
        print_error("Provide at least one participant with --user (UUID, email, or name).")
        raise SystemExit(1)

    if len(identifiers) > MAX_CONVERSATION_PARTICIPANTS:
        print_error(
            f"Too many participants ({len(identifiers)}). "
            f"Slack group DMs support at most {MAX_CONVERSATION_PARTICIPANTS} "
            "users plus the Dailybot bot (8 total)."
        )
        raise SystemExit(1)

    client: DailyBotClient = require_auth()
    try:
        participants: list[tuple[str, str]] = _resolve_participants(client, identifiers)
    except ValueError as exc:
        print_error(str(exc))
        raise SystemExit(1)

    uuids: list[str] = [uuid for uuid, _name in participants]
    if len(uuids) > MAX_CONVERSATION_PARTICIPANTS:
        print_error(
            f"Too many participants ({len(uuids)}). "
            f"Slack group DMs support at most {MAX_CONVERSATION_PARTICIPANTS} "
            "users plus the Dailybot bot (8 total)."
        )
        raise SystemExit(1)
    try:
        with console.status("Opening group conversation..."):
            result: dict[str, Any] = client.open_conversation(uuids)
    except APIError as exc:
        _exit_for_conversation_error(exc, json_mode)

    channel: str = str(result.get("channel", ""))
    message_sent: bool = False
    if message:
        payload: dict[str, Any] = {
            "message": message,
            "target_channels": [{"id": channel, "channel_type": GROUP_CHAT_TYPE}],
        }
        try:
            with console.status("Sending message..."):
                client.send_chat_message(payload)
        except APIError as exc:
            _exit_for_conversation_error(exc, json_mode)
        message_sent = True

    if json_mode:
        emit_json(
            {
                "channel": channel,
                "participants": [{"uuid": uuid, "name": name} for uuid, name in participants],
                "message_sent": message_sent,
            }
        )
        return
    print_conversation_result(channel, participants, message_sent=message_sent)
