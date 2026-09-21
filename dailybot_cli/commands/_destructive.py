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
from dailybot_cli.commands.public_api_helpers import (
    EXIT_USER_ABORTED,
    emit_json,
    resolve_error_message,
    tasks_write_exit_code,
)
from dailybot_cli.display import console, print_dry_run_consequence, print_error


def preview_then_confirm(
    preview_call: Callable[[], dict[str, Any]],
    *,
    assume_yes: bool,
    preview_only: bool,
    json_mode: bool = False,
) -> bool:
    """Fetch and render the server's dry-run preview, then decide whether to act.

    ``preview_call`` is a zero-argument callable so each command supplies its own
    door; returns True when the caller should proceed.
    """
    try:
        with console.status("Previewing the consequence..."):
            preview: dict[str, Any] = preview_call()
    except APIError as exc:
        message: str = (
            "Could not preview the consequence, so nothing was changed. "
            f"{resolve_error_message(exc, tasks_surface=True)}"
        )
        if json_mode:
            # A caller that parses stdout on every exit must not get an empty
            # stream just because the failure happened before the mutation.
            emit_json(
                {
                    "status": "error",
                    "code": getattr(exc, "code", None),
                    "detail": exc.detail,
                    "message": message,
                }
            )
        else:
            print_error(message)
        # The documented table, not a flat 1: `dailybot task archive <gone> --yes`
        # must exit 5 like every other not-found, or an agent branching
        # "5 → skip, 1 → alert" pages on every already-archived object.
        raise SystemExit(tasks_write_exit_code(exc)) from exc

    if json_mode and preview_only:
        # --dry-run --json must emit the blast radius as data. Printing only the
        # Rich panel forced an agent to scrape formatted output for the counts.
        emit_json(preview)
        return False
    # Under --json the mutation still emits its own JSON document on stdout, so the
    # panel goes to stderr: the human record survives and `json.loads(stdout)` works.
    print_dry_run_consequence(preview, to_stderr=json_mode)
    if preview_only:
        return False
    if assume_yes:
        return True
    if not click.confirm("Proceed?", default=False, err=json_mode):
        print_error("Aborted. Nothing was changed.")
        raise SystemExit(EXIT_USER_ABORTED)
    return True
