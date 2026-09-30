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
from dailybot_cli.display import console, print_send_test_preview


def _destination_sentence(what: str, preview: dict[str, Any]) -> str:
    channel: Any = preview.get("channel")
    people: list[Any] = preview.get("email_recipients") or []
    parts: list[str] = []
    if isinstance(channel, dict):
        parts.append(f"the channel {channel.get('name')} ({channel.get('external_id')})")
    if people:
        parts.append(f"{len(people)} email recipient(s)")
    if not parts:
        parts.append("you")
    return f"This sends a real {what} to {' and '.join(parts)}."


def send_test_flow(
    send: Callable[[bool], dict[str, Any]],
    *,
    what: str,
    dry_run: bool,
    assume_yes: bool,
    json_mode: bool,
    door: str | None = None,
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
    if not json_mode:
        print_send_test_preview(preview)
    confirm_without_preview(
        _destination_sentence(what, preview),
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
