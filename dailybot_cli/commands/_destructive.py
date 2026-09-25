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
from rich.markup import escape

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import (
    EXIT_USER_ABORTED,
    emit_json,
    resolve_error_message,
    tasks_write_exit_code,
)
from dailybot_cli.display import console, print_dry_run_consequence, print_error


def _is_preview(payload: Any) -> bool:
    """True for a dry-run preview document, False for a mutated object."""
    if not isinstance(payload, dict):
        return False
    # Every preview shape the doors return carries at least one of these; a mutated
    # task / board / project / goal / milestone carries none of them.
    return payload.get("dry_run") is True or any(
        field in payload for field in ("consequence", "affects", "reversible")
    )


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

    if not _is_preview(preview):
        # The server ignored `?dry_run=true`, so this "preview" was the mutation
        # itself. Rendering it as a preview (or, worse, confirming and sending the
        # real call as well) would hide that a change already happened.
        unexpected: str = (
            "The server answered with a result instead of a preview, so the change may "
            "already have been applied. Nothing more was sent; check the object's state."
        )
        if json_mode:
            emit_json(
                {
                    "status": "error",
                    "code": "preview_not_honoured",
                    "detail": unexpected,
                    "message": unexpected,
                }
            )
        else:
            print_error(unexpected)
        raise SystemExit(1)

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
        aborted: str = "Aborted. Nothing was changed."
        if json_mode:
            # Same reason as the preview-failure branch above: a caller that parses
            # stdout on every non-zero exit must not get a JSONDecodeError for a
            # refusal it can act on.
            emit_json(
                {
                    "status": "error",
                    "code": "user_aborted",
                    "detail": aborted,
                    "message": aborted,
                }
            )
        else:
            print_error(aborted)
        raise SystemExit(EXIT_USER_ABORTED)
    return True


def confirm_without_preview(
    consequence: str,
    *,
    assume_yes: bool,
    dry_run: bool,
    json_mode: bool = False,
) -> bool:
    """Confirm a destructive write on a door that has no server-side dry run.

    The CLI cannot ask the server for the blast radius here, so it states the one
    thing it does know — the exact act — and never pretends to more. `--dry-run`
    prints that sentence and sends nothing; `--yes` skips the prompt. Returns True
    when the caller should proceed.
    """
    if dry_run:
        if json_mode:
            emit_json({"dry_run": True, "consequence": consequence, "previewed_by": "client"})
        else:
            # The sentence embeds caller-supplied ids, so it is data for Rich, never markup.
            console.print(
                f"[bold]Dry run[/bold] — nothing was changed. Would: {escape(consequence)}"
            )
        return False
    if assume_yes:
        return True
    if not click.confirm(f"{consequence} Proceed?", default=False, err=json_mode):
        aborted: str = "Aborted. Nothing was changed."
        if json_mode:
            emit_json(
                {"status": "error", "code": "user_aborted", "detail": aborted, "message": aborted}
            )
        else:
            print_error(aborted)
        raise SystemExit(EXIT_USER_ABORTED)
    return True
