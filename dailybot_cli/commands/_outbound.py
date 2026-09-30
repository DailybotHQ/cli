"""The one flow every outbound send-test goes through: preview first, confirm, then send.

A send-test posts a real message (to a channel, to recipients' email, to your DM). So it never goes out
cold: the CLI always asks the door for ``dry_run=true`` first, shows the destination and the rendered
content, and only calls the real door after a confirmation or ``--yes``. A preview that fails, or that the
server answers as if it had already acted, stops the command before anything is sent.
"""

from collections.abc import Callable
from typing import Any

from dailybot_cli.api_client import APIError
from dailybot_cli.commands._destructive import confirm_without_preview, report_preview_not_honoured
from dailybot_cli.commands.public_api_helpers import emit_json, exit_for_tasks_error
from dailybot_cli.display import (
    console,
    error_console,
    plain_text,
    present_untrusted,
    print_error,
    print_send_test_preview,
)

EXIT_PARTIAL: int = 1  # the documented partial-failure exit
NOT_CONFIRMED_MESSAGE: str = (
    "The API did not confirm the send (no `sent: true` in its answer), so it may not have gone out. "
    "Check the delivery history before trying again."
)


def _destination_sentence(what: str, preview: dict[str, Any], default_target: str) -> str:
    """The consent sentence: the destination comes from the preview, names quoted as data."""
    channel: Any = preview.get("channel")
    people: list[Any] = preview.get("email_recipients") or []
    parts: list[str] = []
    if isinstance(channel, dict):
        parts.append(
            f"the channel {present_untrusted(channel.get('name'), limit=60)} "
            f"({plain_text(channel.get('external_id'))})"
        )
    if people:
        parts.append(f"{len(people)} email recipient(s)")
    if not parts:
        parts.append(default_target)
    return f"This sends a real {what} to {' and '.join(parts)}."


def _show_preview(preview: dict[str, Any], *, json_mode: bool) -> None:
    """Show what would be sent: on stdout, or on stderr under --json (stdout stays one document)."""
    if not json_mode:
        print_send_test_preview(preview)
        return
    with console.capture() as captured:
        print_send_test_preview(preview)
    error_console.print(captured.get(), markup=False, highlight=False, end="")


def send_test_flow(
    send: Callable[[bool], dict[str, Any]],
    *,
    what: str,
    dry_run: bool,
    assume_yes: bool,
    json_mode: bool,
    door: str | None = None,
    default_target: str = "its configured destination",
) -> None:
    """Preview (``dry_run=True``), confirm, then send (``dry_run=False``); ``--dry-run`` stops after the preview."""
    try:
        with console.status("Rendering the preview..."):
            preview: dict[str, Any] = send(True)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode, door=door)
    if not isinstance(preview, dict) or preview.get("dry_run") is not True:
        report_preview_not_honoured(json_mode)
    if dry_run:
        if json_mode:
            emit_json(preview)
        else:
            print_send_test_preview(preview)
        return
    _show_preview(preview, json_mode=json_mode)
    confirm_without_preview(
        _destination_sentence(what, preview, default_target),
        assume_yes=assume_yes,
        dry_run=False,
        json_mode=json_mode,
    )
    try:
        with console.status("Sending..."):
            result: dict[str, Any] = send(False)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode, door=door)
    if json_mode:
        emit_json(result)
    else:
        print_send_test_preview(result)
    if not (isinstance(result, dict) and result.get("sent") is True):
        if not json_mode:
            print_error(NOT_CONFIRMED_MESSAGE)
        raise SystemExit(EXIT_PARTIAL)
