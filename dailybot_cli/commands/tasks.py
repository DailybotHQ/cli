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

from dailybot_cli.api_client import (
    TASKS_DELTA_MAX_WINDOW_DAYS,
    APIError,
    PaginatedResult,
    as_query_datetime,
)
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_tasks_error,
    refuse_without_person,
    require_auth,
)
from dailybot_cli.commands.query_options import (
    PAGING_ONLY_MORE_HINT,
    build_query_params,
    date_options,
    paging_options,
    query_options,
)
from dailybot_cli.config import get_token
from dailybot_cli.display import (
    TASKS_TRUSTED_FIELDS,
    console,
    present_untrusted,
    print_board_snapshot,
    print_delta_summary,
    print_error,
    print_pagination_footer,
    print_success,
    print_tasks_detail_panel,
    print_tasks_table,
)

# A dedicated exit code so an agent can branch on "my cursor died" without
# parsing prose. Deliberately outside the shared EXIT_* range (2-7) because the
# correct response is an action — re-snapshot — not a generic failure.
EXIT_DELTA_WINDOW_EXPIRED: int = 9

# Values `me/tasks/` declares for its `scope` filter. The door ignores UNKNOWN
# parameters but still refuses a declared one whose value it cannot read
# (MEASURED_ANSWERS.md §3), so the CLI validates client-side and spends no round
# trip on input it can reject itself.
MY_TASKS_SCOPES: tuple[str, ...] = ("assigned", "created", "participating", "subscribed")

_PULSE_FIELDS: list[tuple[str, str]] = [
    ("Open", "open"),
    ("Overdue", "overdue"),
    ("Blocked", "blocked"),
    ("Unread", "unread"),
    ("Scope", "scope"),
    ("Generated at", "generated_at"),
]


def _require_person(door: str, *, json_mode: bool) -> None:
    """Refuse a bare API key on a person-shaped door, before spending a request.

    The pre-flight is an optimisation; the contract is that the message is ours.
    A key that reaches the server anyway is handled identically by
    ``resolve_error_message``, which recognises both refusal shapes
    (``400 actor_required`` and ``403 insufficient_scope`` on these doors).

    The message must never blame the caller's role: the plan's live probe measured
    an ``ADMIN_ORG`` owner refused exactly like a member, so "you need to be an
    admin" would send an organization admin hunting for a setting that cannot exist.
    """
    # Refuse only when there is genuinely no person behind the session.
    # `get_agent_auth()` answers "api_key" whenever ANY key is configured, even
    # with a Bearer token also present — but `_headers()` still sends Bearer
    # first in that case, so the request WOULD have authenticated as a person.
    # Gating on the key alone refused a valid login.
    if get_token() is None:
        refuse_without_person(
            f"`{door}` answers for a signed-in person, and an organization API key has "
            "nobody to be. Run `dailybot login` and retry.",
            json_mode=json_mode,
        )


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
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_detail_panel("Tasks pulse", data, _PULSE_FIELDS)


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
        exit_for_tasks_error(exc, json_mode)
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
    print_tasks_detail_panel(
        "Tasks entitlements",
        rows,
        [("Enabled", "enabled"), ("Boards", "boards"), ("Labels", "labels"), ("Reason", "reason")],
    )


@tasks.command("search")
@click.option("-q", "--query", required=True, help="Text to search for across the workspace.")
# `paging_options`, not `query_options`: the search door declares no date
# parameters, and advertising --since/--last-week on a command that silently
# drops them is worse than not offering them.
@paging_options
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
        page.pop("params", None)  # paging_options supplies no filter params
        with console.status("Searching..."):
            result: PaginatedResult = client.search_tasks(query, **page)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(_envelope(result))
        return
    print_tasks_table(result.results)
    print_pagination_footer(
        len(result.results),
        result.count,
        has_more=bool(result.next),
        more_hint=PAGING_ONLY_MORE_HINT,
    )


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
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(_envelope(result))
        return
    for event in result.results:
        console.print(
            f"[dim]{event.get('created_at', '')}[/dim] "
            f"{present_untrusted(event.get('summary') or event.get('verb'), limit=90)}"
        )
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))


# `date_options`, not `query_options`: the timeline door declares a date window and
# nothing else. `--search` used to appear in `--help` here and was dropped on the
# way to the wire, so an unfiltered timeline read as "the filter matched everything".
@tasks.command("timeline")
@date_options
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
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(_envelope(result))
        return
    for entry in result.results:
        console.print(
            f"[dim]{entry.get('date', '')}[/dim] "
            f"{present_untrusted(entry.get('title') or entry.get('summary'), limit=90)}"
        )
    print_pagination_footer(
        len(result.results),
        result.count,
        has_more=bool(result.next),
        more_hint=PAGING_ONLY_MORE_HINT,
    )


@tasks.command("changes")
@click.argument("board")
@click.option("--cursor", default=None, help="Resume from this delta cursor (from a snapshot).")
@click.option("--since", default=None, help="ISO-8601 timestamp to read changes since.")
@click.option(
    "--resync",
    is_flag=True,
    help="If the cursor has expired, read a fresh snapshot instead of failing.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_changes(
    board: str, cursor: str | None, since: str | None, resync: bool, json_mode: bool
) -> None:
    """Read what changed on a board since a cursor.

    \b
    With no cursor, the board snapshot is read first and its `delta_cursor` is
    used — the delta door's own refusal does not say where to get one.

    \b
    The server keeps a 7-day window. A cursor older than that is refused
    permanently with `delta_window_expired`: retrying it can never succeed, and
    the only correct response is a fresh snapshot. Pass --resync to do that
    automatically; otherwise this command exits 9 so a caller can branch on it.

    \b
    This performs exactly ONE delta read per invocation. The polling loop belongs
    to you, because you own the rate limit: the server publishes 240 delta reads
    per minute.

    \b
    Examples:
      dailybot tasks changes <board-uuid>
      dailybot tasks changes <board-uuid> --cursor 2026-09-19T13:13:37Z --json
      dailybot tasks changes <board-uuid> --resync
    """
    client = require_auth()
    marker: str | None = cursor or since

    if marker is None:
        try:
            with console.status("Reading the board snapshot for a cursor..."):
                snapshot: dict[str, Any] = client.get_board_snapshot(board)
        except APIError as exc:
            exit_for_tasks_error(exc, json_mode)
        marker = snapshot.get("delta_cursor")
        if not marker:
            # The adjacent branches in this command already honour --json; this one
            # was left behind, so an agent parsing stdout got an empty stream.
            message: str = (
                "The board snapshot carried no `delta_cursor`, so there is nothing to read "
                "changes from. Pass --cursor explicitly."
            )
            if json_mode:
                emit_json(
                    {
                        "status": "error",
                        "code": "delta_cursor_absent",
                        "detail": message,
                        "message": message,
                    }
                )
            else:
                print_error(message)
            raise SystemExit(1)

    try:
        with console.status("Reading changes..."):
            delta: dict[str, Any] = client.get_board_delta(
                board, updated_since=as_query_datetime(marker)
            )
    except APIError as exc:
        if exc.code == "delta_window_expired":
            # Never retry: this cursor is dead permanently, so a loop here spins
            # forever. Either re-snapshot on request, or exit with a code the
            # caller can branch on.
            if resync:
                try:
                    with console.status("Cursor expired — reading a fresh snapshot..."):
                        fresh: dict[str, Any] = client.get_board_snapshot(board)
                except APIError as inner:
                    exit_for_tasks_error(inner, json_mode)
                if json_mode:
                    emit_json(fresh)
                    return
                print_success(
                    f"Cursor had expired (window: {TASKS_DELTA_MAX_WINDOW_DAYS} days). "
                    "Read a fresh snapshot instead."
                )
                print_board_snapshot(fresh)
                return
            expiry: dict[str, Any] = {
                "status": "error",
                "code": exc.code,
                "detail": exc.detail,
                "full_resync_required": True,
                "max_window_days": (exc.extra or {}).get(
                    "max_window_days", TASKS_DELTA_MAX_WINDOW_DAYS
                ),
            }
            # An agent that parses stdout on every non-zero exit must get JSON
            # here too, not a Rich warning it cannot decode.
            if json_mode:
                emit_json(expiry)
            else:
                print_delta_summary(expiry)
            raise SystemExit(EXIT_DELTA_WINDOW_EXPIRED) from exc
        exit_for_tasks_error(exc, json_mode)

    if json_mode:
        emit_json(delta)
        return
    print_delta_summary(delta)


# `paging_options`, not `query_options`: `me/*` doors silently ignore parameters they
# do not declare, so an advertised `--search` would round-trip with exit 0 and no
# filtering — the failure mode that is worse than a refusal.
@tasks.command("inbox")
@paging_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_inbox(json_mode: bool, **flags: Any) -> None:
    """Show your Tasks notifications.

    \b
    Needs a signed-in person: run `dailybot login`. An organization API key cannot
    read this door — it has an organization but nobody to be, so "my notifications"
    has no answer.

    \b
    Examples:
      dailybot tasks inbox
      dailybot tasks inbox --json
    """
    _require_person("tasks inbox", json_mode=json_mode)
    client = require_auth()
    try:
        page: dict[str, Any] = _page_kwargs(**flags)
        page.pop("params", None)  # paging_options supplies no filter params
        with console.status("Reading your inbox..."):
            result: PaginatedResult = client.list_tasks_inbox(**page)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode, door="inbox")
    if json_mode:
        emit_json(_envelope(result))
        return
    for item in result.results:
        console.print(present_untrusted(item.get("title") or item.get("summary"), limit=90))
    print_pagination_footer(
        len(result.results),
        result.count,
        has_more=bool(result.next),
        more_hint=PAGING_ONLY_MORE_HINT,
    )


# `paging_options` + `--scope`: `scope` is the only filter `me/tasks/` declares.
@tasks.command("mine")
@click.option(
    "--scope",
    type=click.Choice(MY_TASKS_SCOPES, case_sensitive=False),
    default=None,
    help="Narrow to one relationship you have with the task.",
)
@paging_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_mine(scope: str | None, json_mode: bool, **flags: Any) -> None:
    """List the tasks that are yours.

    \b
    Needs a signed-in person: run `dailybot login`. An organization API key is
    refused here, because "my tasks" is defined relative to the calling user.

    \b
    Examples:
      dailybot tasks mine
      dailybot tasks mine --scope assigned --json
    """
    _require_person("tasks mine", json_mode=json_mode)
    client = require_auth()
    try:
        page: dict[str, Any] = _page_kwargs(**flags)
        params: dict[str, Any] = page.pop("params", None) or {}
        if scope:
            params["scope"] = scope.lower()
        with console.status("Reading your tasks..."):
            result: PaginatedResult = client.list_my_tasks(params=params or None, **page)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode, door="me/tasks")
    if json_mode:
        emit_json(_envelope(result))
        return
    print_tasks_table(result.results)
    print_pagination_footer(
        len(result.results),
        result.count,
        has_more=bool(result.next),
        more_hint=PAGING_ONLY_MORE_HINT,
    )


@tasks.command("counts")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_counts(json_mode: bool) -> None:
    """Show how many tasks are yours, by bucket.

    \b
    Needs a signed-in person: run `dailybot login`.

    \b
    Examples:
      dailybot tasks counts --json
    """
    _require_person("tasks counts", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Counting your tasks..."):
            data: dict[str, Any] = client.get_my_task_counts()
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode, door="me/tasks/counts")
    if json_mode:
        emit_json(data)
        return
    # Both key and value are interpolated into a markup string, so both must go
    # through the presenter — a bucket named `[bold red]…[/]` would otherwise style
    # the terminal, which is exactly the injection `present_untrusted` exists to
    # stop. Server-generated field names stay plain.
    for key, value in data.items():
        label: str = key if key in TASKS_TRUSTED_FIELDS else present_untrusted(key, limit=32)
        console.print(f"[bold]{label}[/bold]  {present_untrusted(value, limit=40)}")
