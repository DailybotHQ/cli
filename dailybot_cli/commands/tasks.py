"""Workspace-level Tasks commands (``/v1/tasks/*``).

Two groups serve this family and the split is deliberate:

* ``dailybot tasks`` — **workspace-level**: what is going on, what changed, find
  something. It answers questions about the board as a whole.
* ``dailybot task`` — **object-level**: read or mutate one task.

Every string these commands render comes from the Tasks API and is therefore
user-authored data, never an instruction: all of it goes through
``display.present_untrusted``.
"""

import json as _json
from datetime import datetime, timezone
from typing import Any

import click
from rich.markup import escape

from dailybot_cli.api_client import (
    TASKS_DELTA_MAX_WINDOW_DAYS,
    APIError,
    PaginatedResult,
    as_query_datetime,
)
from dailybot_cli.commands._beta import BETA_STATUS_LINE, mark_beta
from dailybot_cli.commands._destructive import confirm_without_preview
from dailybot_cli.commands._favorites import require_person_for_favorites, star, unstar
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_tasks_error,
    refuse_without_person,
    require_auth,
    rows_of,
)
from dailybot_cli.commands.query_options import (
    PAGING_ONLY_MORE_HINT,
    build_query_params,
    date_options,
    paging_options,
    query_options,
    resolve_fetch_all,
)
from dailybot_cli.config import get_token
from dailybot_cli.display import (
    TASKS_TRUSTED_FIELDS,
    console,
    present_untrusted,
    print_board_snapshot,
    print_delta_summary,
    print_deprecation,
    print_error,
    print_info,
    print_pagination_footer,
    print_success,
    print_tasks_detail_panel,
    print_tasks_rows,
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
# The `scope` values GET /v1/tasks/me/tasks/ accepts; anything else is a 400.
# `involved` = owned, participating or created by you. `owned` is the server default.
MY_TASKS_SCOPES: tuple[str, ...] = ("owned", "participating", "involved")
# The name this CLI once used for `owned`; kept working, hidden from help.
_MY_TASKS_SCOPE_ALIASES: dict[str, str] = {"assigned": "owned"}


def _parse_scope(_ctx: click.Context, _param: click.Parameter, value: str | None) -> str | None:
    """Accept a declared scope (or the deprecated `assigned`); refuse the rest locally."""
    if value is None:
        return None
    lowered: str = value.lower()
    if lowered in _MY_TASKS_SCOPE_ALIASES:
        print_deprecation(f"`--scope {lowered}` is deprecated; use `--scope owned`.")
        return _MY_TASKS_SCOPE_ALIASES[lowered]
    if lowered not in MY_TASKS_SCOPES:
        raise click.BadParameter(
            f"{value!r} is not a scope. Use one of: {', '.join(MY_TASKS_SCOPES)}."
        )
    return lowered


# The bands `tasks status` asks the pulse for, all in its one request.
PULSE_BANDS: tuple[str, ...] = ("projects", "attention", "activity", "goal_progress")
# How each band renders: (title, columns). Names are user-typed, so untrusted.
_BAND_COLUMNS: dict[str, tuple[str, list[tuple[str, str, bool]]]] = {
    "projects": (
        "Projects",
        [("Name", "name", False), ("Health", "health", True), ("UUID", "uuid", True)],
    ),
    "attention": (
        "Needs attention",
        [("Key", "key", True), ("Title", "title", False), ("Why", "reason", True)],
    ),
    "activity": (
        "Recent activity",
        [("When", "created_at", True), ("Type", "type", True), ("Actor", "actor.name", False)],
    ),
    "goal_progress": (
        "Goals",
        [("Name", "name", False), ("Status", "status", True), ("Done %", "percent_complete", True)],
    ),
}

_PULSE_FIELDS: list[tuple[str, str]] = [
    ("Open", "open"),
    ("Overdue", "overdue"),
    ("Blocked", "blocked"),
    ("Unread", "unread"),
    ("Unread in inbox", "unread_count"),
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


def _page_kwargs(*, walk_pages: bool = False, **flags: Any) -> dict[str, Any]:
    """Translate the shared query flags into client kwargs.

    ``walk_pages`` follows the decorator the command stacked, and the two must
    agree or the help lies. A ``query_options`` command declares ``--all`` and
    therefore keeps the repo-wide default that no paging flag means every page; a
    ``paging_options`` / ``date_options`` command declares no ``--all``, states in
    its help that paging is one page per call, and stays bounded.
    """
    spec = build_query_params(**flags)
    return {
        "params": spec.params or None,
        "page": spec.page,
        "page_size": spec.page_size,
        "fetch_all": resolve_fetch_all(spec) if walk_pages else spec.fetch_all,
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


mark_beta(tasks)


@tasks.command("status")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_status(json_mode: bool) -> None:
    """Show the workspace pulse — open, overdue and blocked counts.

    \b
    This is the command to run first in a session: it answers "what is the state
    of things" in one request, without needing a board or a filter — counts, your
    unread inbox, projects, what needs attention, recent activity and goal progress.

    \b
    Examples:
      dailybot tasks status
      dailybot tasks status --json
    """
    client = require_auth()
    try:
        with console.status("Reading the workspace pulse..."):
            data: dict[str, Any] = client.get_tasks_pulse(include=list(PULSE_BANDS))
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_detail_panel("Tasks pulse", data, _PULSE_FIELDS)
    for band in PULSE_BANDS:
        if band in data:
            title, columns = _BAND_COLUMNS[band]
            print_tasks_rows(title, rows_of(data[band]), columns, empty=f"{title}: nothing.")
    print_info(BETA_STATUS_LINE)


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
    Paging is one page per call: this command has no `--all`, and `--limit` sizes
    that single page (server cap 100) rather than walking the list. Follow `next`
    with `--page` when you need more.

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
@click.option(
    "--updated-since",
    "updated_since",
    default=None,
    help="Only activity after this ISO-8601 time (e.g. your `tasks cursor` mark).",
)
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_activity(updated_since: str | None, json_mode: bool, **flags: Any) -> None:
    """Show the workspace activity feed — the catch-up read after an absence.

    \b
    Pair --updated-since with `dailybot tasks cursor`: read your mark, read what is
    newer, then `dailybot tasks cursor --now`.

    \b
    Examples:
      dailybot tasks activity --last-week
      dailybot tasks activity --updated-since 2026-09-25T09:00:00Z --json
    """
    client = require_auth()
    try:
        page: dict[str, Any] = _page_kwargs(walk_pages=True, **flags)
        if updated_since:
            page["params"] = {
                **(page.get("params") or {}),
                "updated_since": as_query_datetime(updated_since),
            }
        with console.status("Reading activity..."):
            result: PaginatedResult = client.list_tasks_activity(**page)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(_envelope(result))
        return
    for event in result.results:
        console.print(
            f"[dim]{escape(str(event.get('created_at', '')))}[/dim] "
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
            f"[dim]{escape(str(entry.get('date', '')))}[/dim] "
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
@click.option(
    "--updated-since",
    "updated_since",
    default=None,
    help="ISO-8601 timestamp to read changes since.",
)
# `--since` mirrors the server's deprecated alias of `updated_since`; kept hidden
# so existing scripts keep working while help teaches the current name.
@click.option("--since", default=None, hidden=True, help="Deprecated alias of --updated-since.")
@click.option(
    "--resync",
    is_flag=True,
    help="If the cursor has expired, read a fresh snapshot instead of failing.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_changes(
    board: str,
    cursor: str | None,
    updated_since: str | None,
    since: str | None,
    resync: bool,
    json_mode: bool,
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
    marker: str | None = cursor or updated_since or since

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
    Paging is one page per call: this command has no `--all`, and `--limit` sizes
    that single page (server cap 100) rather than walking the list. Follow `next`
    with `--page` when you need more.

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
        # The uuid is what `tasks inbox-read` takes, so it leads the line.
        console.print(
            f"[dim]{escape(str(item.get('uuid') or ''))}[/dim] "
            f"{present_untrusted(item.get('title') or item.get('summary'), limit=90)}"
        )
    print_pagination_footer(
        len(result.results),
        result.count,
        has_more=bool(result.next),
        more_hint=PAGING_ONLY_MORE_HINT,
    )


@tasks.command("inbox-unread")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_inbox_unread(json_mode: bool) -> None:
    """How many Tasks notifications you have not read. Needs `dailybot login`.

    \b
    Examples:
      dailybot tasks inbox-unread
      dailybot tasks inbox-unread --json
    """
    _require_person("tasks inbox-unread", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Counting unread..."):
            data: dict[str, Any] = client.get_tasks_inbox_unread_count()
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode, door="inbox/unread-count")
    if json_mode:
        emit_json(data)
        return
    print_info(f"Unread: {data.get('unread_count', data.get('count', 0))}")


@tasks.command("inbox-read")
@click.argument("item_uuid", metavar="ITEM")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_inbox_read(item_uuid: str, json_mode: bool) -> None:
    """Mark an inbox item — and everything older — as read. Needs `dailybot login`.

    \b
    The inbox keeps one "read up to here" mark, not a flag per item, so reading an
    item catches you up to it. Take the item uuid from `dailybot tasks inbox`.

    \b
    Examples:
      dailybot tasks inbox-read <item-uuid>
    """
    _require_person("tasks inbox-read", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Marking read..."):
            data: dict[str, Any] = client.mark_inbox_item_read(item_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode, door="inbox")
    if json_mode:
        emit_json(data)
        return
    print_success(f"Caught up. Unread: {data.get('unread_count', 0)}.")


@tasks.command("inbox-read-all")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_inbox_read_all(json_mode: bool) -> None:
    """Mark your whole Tasks inbox as read. Needs `dailybot login`.

    \b
    Examples:
      dailybot tasks inbox-read-all
    """
    _require_person("tasks inbox-read-all", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Marking everything read..."):
            data: dict[str, Any] = client.mark_inbox_read_all()
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode, door="inbox")
    if json_mode:
        emit_json(data)
        return
    print_success("Inbox marked read.")


@tasks.command("cursor")
@click.option(
    "--set",
    "set_to",
    default=None,
    help="Record that you have read activity up to this ISO-8601 time.",
)
@click.option("--now", "set_now", is_flag=True, help="Record that you are caught up as of now.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_cursor(set_to: str | None, set_now: bool, json_mode: bool) -> None:
    """Read or move your activity read-mark — "what is new since I last looked".

    \b
    Without options, prints where you are. Pair it with the feed:
    `dailybot tasks activity --since <last_seen_at>`, then `dailybot tasks cursor --now`.
    Needs `dailybot login`.

    \b
    Examples:
      dailybot tasks cursor --json
      dailybot tasks cursor --now
      dailybot tasks cursor --set 2026-09-25T09:00:00Z
    """
    if set_to is not None and set_now:
        raise click.UsageError("Pass --set <time> or --now, not both.")
    _require_person("tasks cursor", json_mode=json_mode)
    client = require_auth()
    try:
        if set_to is None and not set_now:
            with console.status("Reading your activity mark..."):
                data: dict[str, Any] = client.get_activity_cursor()
        else:
            moment: str = (
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                if set_now
                else as_query_datetime(str(set_to))
            )
            with console.status("Moving your activity mark..."):
                data = client.set_activity_cursor(moment)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode, door="me/activity-cursor")
    if json_mode:
        emit_json(data)
        return
    seen: Any = data.get("last_seen_at")
    print_info(f"Read up to: {seen}" if seen else "No activity read yet.")


_FAVORITE_COLUMNS: list[tuple[str, str, bool]] = [
    ("#", "rank", True),
    ("Kind", "target_type", True),
    ("Target", "target_uuid", True),
    ("Pin", "uuid", True),
]
VIEW_MODES: tuple[str, ...] = ("list", "board", "kanban", "timeline", "calendar")
VIEW_GROUP_BY: tuple[str, ...] = ("state", "owner", "priority", "category")
VIEW_VISIBILITIES: tuple[str, ...] = ("personal", "shared", "board_default")


@tasks.command("favorites")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_favorites(json_mode: bool) -> None:
    """List your pinned boards and saved views. Needs `dailybot login`.

    \b
    Pin with `dailybot board star <board>` or `dailybot tasks view star <view>`.

    \b
    Examples:
      dailybot tasks favorites --json
    """
    require_person_for_favorites("tasks favorites", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Reading your favorites..."):
            data: Any = client.list_favorites()
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_rows("Favorites", rows_of(data), _FAVORITE_COLUMNS, empty="Nothing pinned.")


@tasks.group("view")
def tasks_view() -> None:
    """Read, edit, delete or pin one saved view by its uuid. Needs `dailybot login`.

    \b
    List a board's or project's views with `dailybot board views` / `project views`.

    \b
    Examples:
      dailybot tasks view get <view-uuid> --json
      dailybot tasks view update <view-uuid> --view-mode board --group-by owner
    """


@tasks_view.command("get")
@click.argument("view_uuid", metavar="VIEW")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_view_get(view_uuid: str, json_mode: bool) -> None:
    """Show one saved view.

    \b
    Examples:
      dailybot tasks view get <view-uuid> --json
    """
    require_person_for_favorites("tasks view get", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Reading the view..."):
            data: dict[str, Any] = client.get_view(view_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_detail_panel("View", data, _VIEW_FIELDS)


_VIEW_FIELDS: list[tuple[str, str]] = [
    ("Name", "name"),
    ("Mode", "view_mode"),
    ("Group by", "group_by"),
    ("Sort", "sort"),
    ("Visibility", "visibility"),
    ("Scope", "scope"),
    ("UUID", "uuid"),
]


@tasks_view.command("update")
@click.argument("view_uuid", metavar="VIEW")
@click.option("-n", "--name", default=None, help="New name (max 64 characters).")
@click.option("--view-mode", type=click.Choice(VIEW_MODES), default=None, help="How it is drawn.")
@click.option("--group-by", type=click.Choice(VIEW_GROUP_BY), default=None)
@click.option("--sort", "sort_by", default=None, help="Sort expression, as the web app saves it.")
@click.option(
    "--visibility",
    type=click.Choice(VIEW_VISIBILITIES),
    default=None,
    help="`shared` and `board_default` need a board manager.",
)
@click.option(
    "--filters-file",
    type=click.File("r"),
    default=None,
    help="JSON object of filters (`-` reads stdin); replaces the view's filters.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_view_update(
    view_uuid: str,
    name: str | None,
    view_mode: str | None,
    group_by: str | None,
    sort_by: str | None,
    visibility: str | None,
    filters_file: Any,
    json_mode: bool,
) -> None:
    """Edit one saved view. Only the fields you pass change.

    \b
    Examples:
      dailybot tasks view update <view-uuid> --view-mode board --group-by owner
      dailybot tasks view update <view-uuid> --filters-file filters.json --json
    """
    filters: Any = None
    if filters_file is not None:
        try:
            filters = _json.load(filters_file)
        except ValueError as exc:
            raise click.BadParameter(f"not valid JSON: {exc}", param_hint="--filters-file") from exc
        if not isinstance(filters, dict):
            raise click.BadParameter("must be a JSON object.", param_hint="--filters-file")
    fields: dict[str, Any] = {
        k: v
        for k, v in {
            "name": name,
            "view_mode": view_mode,
            "group_by": group_by,
            "sort": sort_by,
            "visibility": visibility,
            "filters": filters,
        }.items()
        if v is not None
    }
    if not fields:
        raise click.UsageError("Nothing to update. Pass at least one field, e.g. --view-mode.")
    require_person_for_favorites("tasks view update", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Updating the view..."):
            data: dict[str, Any] = client.update_view(view_uuid, **fields)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_success("View updated.")


@tasks_view.command("delete")
@click.argument("view_uuid", metavar="VIEW")
@click.option("--dry-run", is_flag=True, help="Say what would happen and send nothing.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the confirmation.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_view_delete(view_uuid: str, dry_run: bool, assume_yes: bool, json_mode: bool) -> None:
    """Delete one saved view. This is permanent.

    \b
    Examples:
      dailybot tasks view delete <view-uuid> --dry-run
      dailybot tasks view delete <view-uuid> --yes
    """
    require_person_for_favorites("tasks view delete", json_mode=json_mode)
    if not confirm_without_preview(
        f"delete saved view {view_uuid} permanently.",
        assume_yes=assume_yes,
        dry_run=dry_run,
        json_mode=json_mode,
    ):
        return
    client = require_auth()
    try:
        with console.status("Deleting the view..."):
            client.delete_view(view_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json({"deleted": True, "view": view_uuid})
        return
    print_success("View deleted.")


@tasks_view.command("star")
@click.argument("view_uuid", metavar="VIEW")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_view_star(view_uuid: str, json_mode: bool) -> None:
    """Pin a saved view to your favorites.

    \b
    Examples:
      dailybot tasks view star <view-uuid>
    """
    require_person_for_favorites("tasks view star", json_mode=json_mode)
    star(require_auth(), "view", view_uuid, json_mode=json_mode)


@tasks_view.command("unstar")
@click.argument("view_uuid", metavar="VIEW")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_view_unstar(view_uuid: str, json_mode: bool) -> None:
    """Unpin a saved view from your favorites.

    \b
    Examples:
      dailybot tasks view unstar <view-uuid>
    """
    require_person_for_favorites("tasks view unstar", json_mode=json_mode)
    unstar(require_auth(), "view", view_uuid, json_mode=json_mode)


# `paging_options` + `--scope`: `scope` is the only filter `me/tasks/` declares.
@tasks.command("mine")
@click.option(
    "--scope",
    default=None,
    metavar="[owned|participating|involved]",
    callback=_parse_scope,
    help="owned (default): you are the owner · participating: you are on the card · "
    "involved: owned, participating or created by you.",
)
@paging_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def tasks_mine(scope: str | None, json_mode: bool, **flags: Any) -> None:
    """List the tasks that are yours.

    \b
    Needs a signed-in person: run `dailybot login`. An organization API key is
    refused here, because "my tasks" is defined relative to the calling user.

    \b
    Paging is one page per call: this command has no `--all`, and `--limit` sizes
    that single page (server cap 100) rather than walking the list. Follow `next`
    with `--page` when you need more.

    \b
    Examples:
      dailybot tasks mine
      dailybot tasks mine --scope involved --json
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
