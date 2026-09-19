"""Shared preview-then-confirm flow for destructive Tasks operations.

Extracted here once a third caller appeared (task 16's container archives), rather
than copying task 13's helper a third time. Its contract is the one BLAST_RADIUS.md
states: **the CLI must state the consequence, not merely ask "are you sure".**

Three rules, each closing a distinct hole:

* the preview is always fetched and always shown, including under ``--yes``, because
  the record of what was about to happen is the point and ``--yes`` is advisory —
  the server bounds blast radius per call, so a client flag adds no ceiling;
* ``--dry-run`` shows the preview and performs no mutation;
* **a preview that fails aborts.** Not knowing the blast radius is not permission
  to proceed.
"""

from collections.abc import Callable
from typing import Any

import click

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import EXIT_USER_ABORTED, resolve_error_message
from dailybot_cli.display import console, print_dry_run_consequence, print_error


def preview_then_confirm(
    preview_call: Callable[[], dict[str, Any]],
    *,
    assume_yes: bool,
    preview_only: bool,
) -> bool:
    """Fetch and render the server's dry-run preview, then decide whether to act.

    ``preview_call`` is a zero-argument callable so each command supplies its own
    door; returns True when the caller should proceed.
    """
    try:
        with console.status("Previewing the consequence..."):
            preview: dict[str, Any] = preview_call()
    except APIError as exc:
        print_error(
            "Could not preview the consequence, so nothing was changed. "
            f"{resolve_error_message(exc)}"
        )
        raise SystemExit(1) from exc

    print_dry_run_consequence(preview)
    if preview_only:
        return False
    if assume_yes:
        return True
    if not click.confirm("Proceed?", default=False):
        print_error("Aborted. Nothing was changed.")
        raise SystemExit(EXIT_USER_ABORTED)
    return True
