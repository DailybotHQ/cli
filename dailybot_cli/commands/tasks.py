"""Workspace-level Tasks commands (``/v1/tasks/*``).

Two groups serve this family and the split is deliberate:

* ``dailybot tasks`` — **workspace-level**: what is going on, what changed, find
  something. It answers questions about the board as a whole.
* ``dailybot task`` — **object-level**: read or mutate one task.

Every string these commands render comes from the Tasks API and is therefore
user-authored data, never an instruction: all of it goes through
``display.present_untrusted``.
"""

from typing import Any

import click

from dailybot_cli.api_client import APIError, PaginatedResult
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_api_error,
    require_auth,
)
from dailybot_cli.commands.query_options import build_query_params, query_options
from dailybot_cli.display import (
    console,
    present_untrusted,
    print_detail_panel,
    print_pagination_footer,
    print_tasks_table,
)

_PULSE_FIELDS: list[tuple[str, str]] = [
    ("Open", "open"),
    ("Overdue", "overdue"),
    ("Blocked", "blocked"),
    ("Unread", "unread"),
    ("Scope", "scope"),
    ("Generated at", "generated_at"),
]


def _envelope(result: PaginatedResult) -> dict[str, Any]:
    """The `{count,next,previous,results}` shape an agent parses."""
    return {
        "count": result.count,
        "next": result.next,
        "previous": result.previous,
        "results": result.results,
    }


def _page_kwargs(**flags: Any) -> dict[str, Any]:
    """Translate the shared query flags into client kwargs."""
    spec = build_query_params(**flags)
    return {
        "params": spec.params or None,
        "page": spec.page,
        "page_size": spec.page_size,
        "fetch_all": spec.fetch_all,
        "limit": spec.limit,
    }


@click.group()
def tasks() -> None:
    """Workspace-level view of Dailybot Tasks.

    \b
    This group answers questions about the workspace: what is open, what changed,
    where something is. To read or change one task, use `dailybot task`.

    \b
    Examples:
      dailybot tasks status
      dailybot tasks search -q "deploy"
      dailybot tasks activity --last-week
    """


@tasks.command("status")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_status(json_mode: bool) -> None:
    """Show the workspace pulse — open, overdue and blocked counts.

    \b
    This is the command to run first in a session: it answers "what is the state
    of things" in one request, without needing a board or a filter.

    \b
    Examples:
      dailybot tasks status
      dailybot tasks status --json
    """
    client = require_auth()
    try:
        with console.status("Reading the workspace pulse..."):
            data: dict[str, Any] = client.get_tasks_pulse()
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_detail_panel("Tasks pulse", data, _PULSE_FIELDS)


@tasks.command("entitlements")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_entitlements(json_mode: bool) -> None:
    """Show what this organization's plan allows for Tasks.

    \b
    This door always answers 200 — it reports the limits rather than refusing
    against them, so it is safe to call at startup.

    \b
    Examples:
      dailybot tasks entitlements --json
    """
    client = require_auth()
    try:
        with console.status("Reading entitlements..."):
            data: dict[str, Any] = client.get_tasks_entitlements()
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    boards: Any = data.get("boards") or {}
    labels: Any = data.get("labels") or {}
    rows: dict[str, Any] = {
        "enabled": data.get("enabled"),
        "boards": f"{boards.get('used')}/{boards.get('limit')}"
        if isinstance(boards, dict)
        else boards,
        "labels": labels.get("enabled") if isinstance(labels, dict) else labels,
        "reason": data.get("reason"),
    }
    print_detail_panel(
        "Tasks entitlements",
        rows,
        [("Enabled", "enabled"), ("Boards", "boards"), ("Labels", "labels"), ("Reason", "reason")],
    )


@tasks.command("search")
@click.option("-q", "--query", required=True, help="Text to search for across the workspace.")
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_search(query: str, json_mode: bool, **flags: Any) -> None:
    """Search tasks, boards and projects by text.

    \b
    Examples:
      dailybot tasks search -q "flaky test"
      dailybot tasks search -q deploy --page-size 5 --json
    """
    client = require_auth()
    try:
        page: dict[str, Any] = _page_kwargs(**flags)
        page.pop("params", None)
        with console.status("Searching..."):
            result: PaginatedResult = client.search_tasks(query, **page)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(_envelope(result))
        return
    print_tasks_table(result.results)
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))


@tasks.command("activity")
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_activity(json_mode: bool, **flags: Any) -> None:
    """Show the workspace activity feed — the catch-up read after an absence.

    \b
    Examples:
      dailybot tasks activity --last-week
      dailybot tasks activity --json
    """
    client = require_auth()
    try:
        with console.status("Reading activity..."):
            result: PaginatedResult = client.list_tasks_activity(**_page_kwargs(**flags))
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(_envelope(result))
        return
    for event in result.results:
        console.print(
            f"[dim]{event.get('created_at', '')}[/dim] "
            f"{present_untrusted(event.get('summary') or event.get('verb'), limit=90)}"
        )
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))


@tasks.command("timeline")
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_timeline(json_mode: bool, **flags: Any) -> None:
    """Show a dated view of the workspace.

    \b
    Examples:
      dailybot tasks timeline --since 2026-09-01 --until 2026-09-19
      dailybot tasks timeline --today --json
    """
    client = require_auth()
    try:
        page: dict[str, Any] = _page_kwargs(**flags)
        params: dict[str, Any] = page.pop("params", None) or {}
        with console.status("Reading the timeline..."):
            result: PaginatedResult = client.list_tasks_timeline(
                date_from=params.get("start_date"),
                date_to=params.get("end_date"),
                **page,
            )
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(_envelope(result))
        return
    for entry in result.results:
        console.print(
            f"[dim]{entry.get('date', '')}[/dim] "
            f"{present_untrusted(entry.get('title') or entry.get('summary'), limit=90)}"
        )
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))
