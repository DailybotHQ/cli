"""Object-level Tasks commands (``dailybot task``).

Sibling of ``dailybot tasks`` (workspace-level). This group reads and mutates
**one** task. Every string it renders is user-authored and goes through
``display.present_untrusted``.

`/v1/tasks/tasks/` is **strict** about parameters and names the one it refuses,
unlike `me/tasks/` which silently ignores unknown ones. So every filter flag here
maps to a parameter the contract declares — a convenience flag that invents a
parameter name would produce a 400.
"""

import json as _json
import mimetypes
import re
from pathlib import Path
from typing import Any, NoReturn

import click
from rich.console import Console
from rich.markup import escape

from dailybot_cli.api_client import (
    ATTACHMENT_MAX_SIZE_BYTES,
    ATTACHMENT_MULTIPART_MAX_BYTES,
    TASKS_BULK_MAX_ITEMS,
    APIError,
    PaginatedResult,
    as_query_datetime,
)
from dailybot_cli.commands._beta import mark_beta
from dailybot_cli.commands._destructive import confirm_without_preview, preview_then_confirm
from dailybot_cli.commands._writes import IDEMPOTENCY_TTL_HOURS, named, report_write
from dailybot_cli.commands.public_api_helpers import (
    EXIT_USAGE_ERROR,
    EXIT_USER_ABORTED,
    emit_json,
    exit_for_tasks_error,
    refuse_without_person,
    require_auth,
    rows_of,
)
from dailybot_cli.commands.query_options import (
    PAGING_ONLY_MORE_HINT,
    build_query_params,
    paging_options,
    query_options,
    resolve_fetch_all,
)
from dailybot_cli.config import get_token
from dailybot_cli.display import (
    console,
    error_console,
    print_bulk_preview,
    print_deprecation,
    print_error,
    print_pagination_footer,
    print_success,
    print_task_comments,
    print_task_detail,
    print_tasks_rows,
    print_tasks_table,
)

# Parameters `/v1/tasks/tasks/` declares. `has_dates` is here deliberately: it was
# honoured for two years, never declared, and refused the moment the door became
# strict (MEASURED_ANSWERS.md §3). The declared set is the contract, not the
# historically-tolerated set.
TASK_INCLUDE_VALUES: tuple[str, ...] = ("labels", "participants", "subtasks")

# The server's idempotency slot lives for 24 hours. Reusing a key inside that
# window REPLAYS the original write; reusing it after expiry is a NEW write and
# duplicates. Both halves are stated in the help, because only knowing the first
# one is how a retry loop quietly creates duplicates on day two.
# Owned by `_writes.py`, which prints the same number in the post-write hint — two
# copies would drift and the help would contradict the CLI's own output.

LABEL_MODES: tuple[str, ...] = ("add", "remove", "replace")

# The accountable person is `owner` on the wire, both as the list filter and as the
# written field. `assignee` is refused by the strict list door, and `executor` is
# read-only (who is doing the work, an agent or a person) — writing it is refused.
# The old flags survive only as hidden aliases that map onto `owner`.
OWNER_HELP: str = "Owner: a user uuid, or `me`."
OWNER_FILTER_HELP: str = (
    "Only tasks owned by this user (uuid, `me` or `unowned`). Repeat to OR several."
)
# The values `/v1/tasks/tasks/` accepts for `sort`; a leading `-` sorts descending.
TASK_SORT_FIELDS: tuple[str, ...] = (
    "rank",
    "priority",
    "due_date",
    "updated_at",
    "created_at",
    "completed_at",
)


# Task priority on the wire: 1=urgent, 2=high, 3=medium, 4=low, 5=none.
PRIORITY_HELP: str = "Priority 1-5: 1 urgent, 2 high, 3 medium, 4 low, 5 none."
PRIORITY_TYPE: click.IntRange = click.IntRange(min=1, max=5)

# Relation types the contract declares. `relates-to` (the spelling this CLI's help
# once taught) is accepted and normalised, so an old script keeps working.
# What `task duplicate --include` may copy. The server's default (no --include) is
# title, description and labels.
DUPLICATE_FIELDS: tuple[str, ...] = (
    "title",
    "description",
    "labels",
    "priority",
    "estimate",
    "owner",
    "start_date",
    "due_date",
)

# Operations `/v1/tasks/tasks/bulk/` declares. `delete` is the alias of archive.
BULK_OPERATIONS: tuple[str, ...] = (
    "create",
    "move",
    "update",
    "archive",
    "restore",
    "set_labels",
    "set_owner",
    "set_priority",
    "set_due_date",
    "set_parent",
    "delete",
)

PARTICIPANT_ROLES: tuple[str, ...] = ("participant", "watcher")

RELATION_TYPES: tuple[str, ...] = ("blocks", "relates_to", "duplicates")

# A column's fixed meaning. `move/` takes a state uuid only, so a name or one of
# these is resolved client-side against the board's live columns.
STATE_CATEGORIES: tuple[str, ...] = ("backlog", "todo", "in_progress", "done", "canceled")
_UUID_RE: re.Pattern[str] = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _parse_relation(_ctx: click.Context, _param: click.Parameter, value: str) -> str:
    """Normalise `relates-to` to `relates_to` and refuse anything undeclared."""
    normalised: str = value.strip().lower().replace("-", "_")
    if normalised not in RELATION_TYPES:
        raise click.BadParameter(
            f"{value!r} is not a relation. Use one of: {', '.join(RELATION_TYPES)}."
        )
    return normalised


def _board_of(task: dict[str, Any]) -> str:
    """The board uuid a task sits on (a string, or an object carrying `uuid`)."""
    board: Any = task.get("board")
    if isinstance(board, dict):
        board = board.get("uuid")
    if not board:
        raise click.ClickException("The task did not say which board it is on; pass --board.")
    return str(board)


def resolve_state(states: Any, value: str) -> str:
    """Turn a column name or category into the state uuid `move/` requires.

    A uuid passes through. Otherwise: a case-insensitive name match among live
    columns wins; failing that, a category picks its lowest-position live column.
    An ambiguous name or no match is a usage error that lists what exists, so the
    caller can retry with a uuid. Resolving here keeps scripts working across a
    column rename only when they pass the category or the uuid — which is the point
    of the category.
    """
    if _UUID_RE.match(value):
        return value
    live: list[dict[str, Any]] = [row for row in rows_of(states) if not row.get("is_archived")]
    wanted: str = value.strip().casefold()
    named: list[dict[str, Any]] = [r for r in live if str(r.get("name", "")).casefold() == wanted]
    if len(named) == 1:
        return str(named[0]["uuid"])
    if len(named) > 1:
        candidates: str = ", ".join(f"{r.get('name')} ({r.get('uuid')})" for r in named)
        raise click.UsageError(
            f"{value!r} names more than one column: {candidates}. Pass the uuid."
        )
    if wanted in STATE_CATEGORIES:
        in_category: list[dict[str, Any]] = sorted(
            (r for r in live if r.get("category") == wanted),
            key=lambda r: int(r.get("position") or 0),
        )
        if in_category:
            return str(in_category[0]["uuid"])
    columns: str = ", ".join(f"{r.get('name')} [{r.get('category')}]" for r in live) or "none"
    raise click.UsageError(
        f"No column named {value!r} on this board. Columns: {columns}. "
        f"Pass a name, a category ({', '.join(STATE_CATEGORIES)}) or a state uuid."
    )


def _parse_sort(_ctx: click.Context, _param: click.Parameter, value: str | None) -> str | None:
    """Accept `field` or `-field` for a declared sort field; say what is allowed otherwise."""
    if value is None:
        return None
    field: str = value[1:] if value.startswith("-") else value
    if field not in TASK_SORT_FIELDS:
        allowed: str = ", ".join(TASK_SORT_FIELDS)
        raise click.BadParameter(
            f"{value!r} is not a sort field. Use one of: {allowed} "
            "(prefix with - for descending, e.g. -updated_at)."
        )
    return value


ASSIGNEE_DEPRECATION: str = "`--assignee` is deprecated; use `--owner` (same value)."
ASSIGN_DEPRECATION: str = (
    "`dailybot task assign` is deprecated; use `dailybot task set-owner <task> <user|me>`."
)

# Short aliases owned by the shared `query_options` decorator: -a (--all),
# -l (--limit), -s (--search), -S (--since), -U (--until), -p (--page).
# Filter flags on this group are therefore long-only except `-b`, which is free.
# Click only *warns* about a duplicate short flag, so the collision is silent at
# runtime and the wrong option wins — a regression test pins it instead.


def _envelope(result: PaginatedResult) -> dict[str, Any]:
    return {
        "count": result.count,
        "next": result.next,
        "previous": result.previous,
        "results": result.results,
    }


@click.group()
def task() -> None:
    """Read and change one Dailybot task.

    \b
    For workspace-level questions — what is open, what changed, search — use
    `dailybot tasks` instead.

    \b
    Examples:
      dailybot task list --board <board-uuid>
      dailybot task get ENG-142

    \b
    TASK is a task key (ENG-142) or a uuid. The API resolves both, including a key
    retired by a board rename.
    """


mark_beta(task)


@task.command("list")
@click.option("-b", "--board", default=None, help="Only tasks on this board.")
@click.option("--state", default=None, help="Only tasks in this workflow state.")
@click.option("--owner", "owners", multiple=True, help=OWNER_FILTER_HELP)
@click.option("--assignee", "assignees", multiple=True, hidden=True, help=ASSIGNEE_DEPRECATION)
@click.option("--label", default=None, help="Only tasks carrying this label.")
@click.option(
    "--sort",
    default=None,
    callback=_parse_sort,
    help="Order by rank, priority, due_date, updated_at, created_at or completed_at; "
    "prefix with - for descending.",
)
@click.option(
    "--has-dates/--no-has-dates",
    "has_dates",
    default=None,
    help="Only tasks that do (or do not) carry dates.",
)
@click.option(
    "--include",
    type=click.Choice(TASK_INCLUDE_VALUES, case_sensitive=False),
    multiple=True,
    help="Ask for a roll-up. Nothing is included by default — absence is a real answer.",
)
# `paging_options`, not `query_options`: `/v1/tasks/tasks/` is strict and declares
# none of the shared text/date filters. Advertising --search / --last-week on a
# command that silently drops them lets a caller believe filtering worked.
@paging_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_list(
    board: str | None,
    state: str | None,
    owners: tuple[str, ...],
    assignees: tuple[str, ...],
    label: str | None,
    sort: str | None,
    has_dates: bool | None,
    include: tuple[str, ...],
    json_mode: bool,
    **flags: Any,
) -> None:
    """List tasks.

    \b
    Roll-ups are NOT requested by default. A field you did not ask for is absent
    from the payload, which is different from null and different from zero — ask
    for it with --include when you want it.

    \b
    Paging is one page per call: this command has no `--all`, and `--limit` sizes
    that single page (server cap 100) rather than walking the list. Follow `next`
    with `--page` when you need more — a bounded read is deliberate here, because
    a workspace's task list has no natural ceiling.

    \b
    Examples:
      dailybot task list --board <board-uuid> --state doing
      dailybot task list --owner me --owner unowned --include labels --json
      dailybot task list --sort -updated_at --limit 10
    """
    client = require_auth()
    filters: dict[str, Any] = {}
    if board:
        filters["board"] = board
    if state:
        filters["state"] = state
    if assignees:
        print_deprecation(ASSIGNEE_DEPRECATION)
    owner_values: list[str] = [*owners, *assignees]
    if owner_values:
        filters["owner"] = owner_values
    if label:
        filters["label"] = label
    if sort:
        filters["sort"] = sort
    if has_dates is not None:
        filters["has_dates"] = has_dates
    if include:
        filters["include"] = ",".join(sorted({value.lower() for value in include}))

    try:
        spec = build_query_params(**flags)
        # `/v1/tasks/tasks/` is strict and refuses any parameter it does not
        # declare, and it declares none of the shared text/date filters. Forwarding
        # them would spend a round trip to earn a 400 whose message blames the
        # *value*, not the parameter name. Drop them here instead.
        merged: dict[str, Any] = dict(filters)
        with console.status("Reading tasks..."):
            result: PaginatedResult = client.list_tasks(
                filters=merged or None,
                page=spec.page,
                page_size=spec.page_size,
                fetch_all=spec.fetch_all,  # @paging_options: one page per call, as the help says
                limit=spec.limit,
            )
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


@task.command("get")
@click.argument("task_uuid", metavar="TASK")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_get(task_uuid: str, json_mode: bool) -> None:
    """Show one task.

    \b
    Prints the API self-link. No web URL is shown: the web app owns its path
    shapes and they are not published, so a link built here would be a guess.

    \b
    Examples:
      dailybot task get ENG-142
      dailybot task get ENG-142 --json
    """
    client = require_auth()
    try:
        with console.status("Reading the task..."):
            data: dict[str, Any] = client.get_task(task_uuid)
    except APIError as exc:
        # Isolation is 404-not-403: an invisible object and a nonexistent one must
        # be indistinguishable. Routed through the shared mapper so the exit code
        # and the --json payload match the documented table.
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_task_detail(data)


def _write_error(exc: APIError, json_mode: bool = False) -> NoReturn:
    """Surface a write refusal and stop. Never retries.

    Delegates the status -> exit mapping to the shared helper so this module
    cannot drift from `exit_for_api_error` or from the exit table in
    `docs/API_REFERENCE.md`.
    """
    exit_for_tasks_error(exc, json_mode)


@task.command("create")
@click.option("-t", "--title", required=True, help="Task title.")
@click.option("-b", "--board", default=None, help="Board to create it on.")
@click.option("-d", "--description", default=None, help="Task description.")
@click.option("--state", default=None, help="Initial workflow state.")
@click.option("--owner", default=None, help=OWNER_HELP)
@click.option("--assignee", default=None, hidden=True, help=ASSIGNEE_DEPRECATION)
@click.option("--due", default=None, help="Due date (YYYY-MM-DD).")
@click.option("--priority", type=PRIORITY_TYPE, default=None, help=PRIORITY_HELP)
@click.option(
    "--idempotency-key",
    default=None,
    help=(
        "Reuse a key to make a retry safe. Generated automatically when omitted. "
        f"The server keeps it for {IDEMPOTENCY_TTL_HOURS}h: reusing it inside that "
        "window replays the original result, reusing it after duplicates."
    ),
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_create(
    title: str,
    board: str | None,
    description: str | None,
    state: str | None,
    owner: str | None,
    assignee: str | None,
    due: str | None,
    priority: int | None,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Create a task.

    \b
    An idempotency key is always sent, and the one used is printed (and returned as
    `_idempotency_key` under --json). Pass it back with --idempotency-key to make a
    retry safe: re-running this command without it mints a NEW key, which the server
    cannot recognise, so a retry after a timeout WOULD create a second task. The
    server keeps a key for 24 hours — reusing it inside the window replays the
    original result, and reusing it AFTER the window is a new write that duplicates.

    \b
    Examples:
      dailybot task create --title "Fix the flaky test" --board <board-uuid> --owner me
      dailybot task create -t "Ship it" --idempotency-key deploy-42 --json
    """
    if assignee:
        print_deprecation(ASSIGNEE_DEPRECATION)
    client = require_auth()
    try:
        with console.status("Creating the task..."):
            data: dict[str, Any] = client.create_task(
                title=title,
                board=board,
                description=description,
                state=state,
                owner=owner or assignee,
                due_date=due,
                priority=priority,
                idempotency_key=idempotency_key,
            )
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Created {named(data, title, field='title')}")
    print_task_detail(data)


@task.command("update")
@click.argument("task_uuid", metavar="TASK")
@click.option("-t", "--title", default=None, help="New title.")
@click.option("-d", "--description", default=None, help="New description.")
@click.option("--state", default=None, help="New workflow state.")
@click.option("--due", default=None, help="New due date (YYYY-MM-DD).")
@click.option("--priority", type=PRIORITY_TYPE, default=None, help=PRIORITY_HELP)
@click.option("--owner", default=None, help=OWNER_HELP)
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_update(
    task_uuid: str,
    title: str | None,
    description: str | None,
    state: str | None,
    due: str | None,
    priority: int | None,
    owner: str | None,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Change fields on a task.

    \b
    Only the fields you pass are sent — this is a partial update, never a
    full-object overwrite, so a field you omit keeps its current value.

    \b
    Examples:
      dailybot task update ENG-142 --state done
      dailybot task update ENG-142 -t "Clearer title" --json
    """
    fields: dict[str, Any] = {
        "title": title,
        "description": description,
        "state": state,
        "due_date": due,
        "priority": priority,
        "owner": owner,
    }
    supplied: dict[str, Any] = {k: v for k, v in fields.items() if v is not None}
    if not supplied:
        raise click.UsageError(
            "Nothing to update. Pass at least one field, e.g. --title or --state."
        )
    client = require_auth()
    try:
        with console.status("Updating the task..."):
            data: dict[str, Any] = client.update_task(
                task_uuid, idempotency_key=idempotency_key, **supplied
            )
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Task updated")


@task.command("move")
@click.argument("task_uuid", metavar="TASK")
@click.option(
    "--state",
    default=None,
    help="Target column: a name, a category (todo, in_progress, done, …) or a state uuid.",
)
@click.option("--board", default=None, help="Target board, for a move to another board.")
@click.option(
    "--idempotency-key",
    default=None,
    help="Reuse a key to make a retry safe (same-board moves; a cross-board move takes none).",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_move(
    task_uuid: str,
    state: str | None,
    board: str | None,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Move a task to another column, or to another board.

    \b
    --state takes a column name (case-insensitive), a category — which picks that
    category's first column — or a state uuid. A name or category costs one read
    of the board's columns; a uuid costs none.

    \b
    With --board the task changes board; without --state it lands in the column
    with the same category there.

    \b
    Examples:
      dailybot task move ENG-142 --state done
      dailybot task move ENG-142 --state "In review" --json
      dailybot task move ENG-142 --board <board-uuid>
    """
    if state is None and board is None:
        raise click.UsageError("Pass --state or --board (or both) to say where it should go.")
    client = require_auth()
    try:
        state_uuid: str | None = None
        if state is not None:
            if _UUID_RE.match(state):
                state_uuid = state
            else:
                with console.status("Reading the board's columns..."):
                    target: str = board or _board_of(client.get_task(task_uuid))
                    state_uuid = resolve_state(client.list_board_states(target), state)
        with console.status("Moving the task..."):
            if board is not None:
                data: dict[str, Any] = client.move_task_to_board(
                    task_uuid, board=board, state=state_uuid
                )
            else:
                data = client.move_task(
                    task_uuid, idempotency_key=idempotency_key, state=state_uuid
                )
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Task moved")


def _set_owner(task_ref: str, owner: str, idempotency_key: str | None, json_mode: bool) -> None:
    """PATCH the task's `owner`, the one writable field for the accountable person."""
    client = require_auth()
    try:
        with console.status("Setting the owner..."):
            data: dict[str, Any] = client.update_task(
                task_ref, owner=owner, idempotency_key=idempotency_key
            )
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Owner set")


@task.command("set-owner")
@click.argument("task_ref", metavar="TASK")
@click.argument("owner", metavar="USER")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_set_owner(task_ref: str, owner: str, idempotency_key: str | None, json_mode: bool) -> None:
    """Make someone the task's owner — the accountable person.

    \b
    TASK is a key (ENG-142) or a uuid. USER is a user uuid, or `me`. Who is doing
    the work (a person or an agent) is a separate, read-only fact the server keeps;
    this command never writes it.

    \b
    Examples:
      dailybot task set-owner ENG-142 me
      dailybot task set-owner ENG-142 <user-uuid> --json
    """
    _set_owner(task_ref, owner, idempotency_key, json_mode)


@task.command("assign", hidden=True)
@click.argument("task_ref", metavar="TASK")
@click.option("--to", "owner", required=True, help=OWNER_HELP)
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_assign(task_ref: str, owner: str, idempotency_key: str | None, json_mode: bool) -> None:
    """Deprecated alias of `dailybot task set-owner`.

    \b
    Examples:
      dailybot task set-owner ENG-142 <user-uuid>
    """
    print_deprecation(ASSIGN_DEPRECATION)
    _set_owner(task_ref, owner, idempotency_key, json_mode)


def _require_person_for(action: str, *, json_mode: bool) -> None:
    """Refuse a key on a person-only door.

    Published policy: two writes no organization API key may ever make — changing
    who can see, and changing who is notified. Participants are the second.
    """
    # See tasks.py `_require_person`: gate on the absence of a person token, not
    # on the presence of a key — both can be configured at once.
    if get_token() is None:
        refuse_without_person(
            f"`{action}` changes who is notified, and no organization API key may do that — "
            "there is no person behind it to be accountable. Run `dailybot login` and retry.",
            json_mode=json_mode,
        )


def _read_body(value: str) -> str:
    """Read a body argument, or stdin when it is `-`."""
    if value == "-":
        return click.get_text_stream("stdin").read().strip()
    return value


@task.command("comment")
@click.argument("task_uuid", metavar="TASK")
@click.argument("body")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_comment(task_uuid: str, body: str, idempotency_key: str | None, json_mode: bool) -> None:
    """Comment on a task. Pass `-` as the body to read it from stdin.

    \b
    Examples:
      dailybot task comment ENG-142 "Deployed to staging"
      echo "long note" | dailybot task comment ENG-142 -
    """
    client = require_auth()
    try:
        with console.status("Posting the comment..."):
            data: dict[str, Any] = client.comment_on_task(
                task_uuid, body=_read_body(body), idempotency_key=idempotency_key
            )
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Comment posted")


@task.command("comments")
@click.argument("task_uuid", metavar="TASK")
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_comments(task_uuid: str, json_mode: bool, **flags: Any) -> None:
    """List a task's comments.

    \b
    Comment bodies are user-authored text. They are rendered as quoted data, and
    `provenance: typed` is shown as attribution — a person typed it, which does
    not make it an instruction.

    \b
    Examples:
      dailybot task comments ENG-142
    """
    client = require_auth()
    try:
        spec = build_query_params(**flags)
        with console.status("Reading comments..."):
            result: PaginatedResult = client.list_task_comments(
                task_uuid,
                params=spec.params or None,
                page=spec.page,
                page_size=spec.page_size,
                fetch_all=resolve_fetch_all(spec),
                limit=spec.limit,
            )
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(_envelope(result))
        return
    print_task_comments(result.results)
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))


@task.command("link")
@click.argument("task_uuid", metavar="TASK")
@click.argument("other_uuid", metavar="OTHER_TASK")
@click.option(
    "--type",
    "relation",
    required=True,
    callback=_parse_relation,
    help="blocks, relates_to or duplicates.",
)
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_link(
    task_uuid: str, other_uuid: str, relation: str, idempotency_key: str | None, json_mode: bool
) -> None:
    """Relate one task to another.

    \b
    Examples:
      dailybot task link ENG-142 ENG-99 --type blocks
    """
    client = require_auth()
    try:
        with console.status("Linking the tasks..."):
            data: dict[str, Any] = client.relate_tasks(
                task_uuid, other=other_uuid, relation=relation, idempotency_key=idempotency_key
            )
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Tasks linked")


@task.command("labels")
@click.argument("task_uuid", metavar="TASK")
@click.option(
    "--mode",
    type=click.Choice(LABEL_MODES, case_sensitive=False),
    required=True,
    help="add, remove or replace the task's labels.",
)
@click.option(
    "--label",
    "labels",
    multiple=True,
    required=True,
    help="Label uuid. Repeatable, or comma-separated.",
)
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_labels(
    task_uuid: str, mode: str, labels: tuple[str, ...], idempotency_key: str | None, json_mode: bool
) -> None:
    """Add, remove or replace a task's labels.

    \b
    Flag vocabulary matches `dailybot label batch` so the two read consistently.

    \b
    Examples:
      dailybot task labels ENG-142 --mode add --label <label-uuid>
      dailybot task labels ENG-142 --mode replace --label a,b
    """
    resolved: list[str] = []
    for raw in labels:
        resolved.extend(part.strip() for part in raw.split(",") if part.strip())
    client = require_auth()
    try:
        with console.status("Updating labels..."):
            data: dict[str, Any] = client.batch_task_labels(
                task_uuid,
                mode=mode.lower(),
                labels=list(dict.fromkeys(resolved)),
                idempotency_key=idempotency_key,
            )
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Labels updated")


@task.group("participants")
def task_participants() -> None:
    """Manage who is notified about a task.

    \b
    Person-only: no organization API key may change who is notified, because
    there is no person behind it to be accountable. Run `dailybot login`.
    """


@task_participants.command("add")
@click.argument("task_uuid", metavar="TASK")
@click.option("--user", required=True, help="User uuid to add as a participant.")
@click.option(
    "--role",
    type=click.Choice(PARTICIPANT_ROLES),
    default=None,
    help="`participant` is on the card (default); `watcher` follows it without being on it.",
)
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def participants_add(
    task_uuid: str, user: str, role: str | None, idempotency_key: str | None, json_mode: bool
) -> None:
    """Add a participant to a task.

    \b
    Examples:
      dailybot task participants add ENG-142 --user <user-uuid>
    """
    _require_person_for("task participants add", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Adding the participant..."):
            data: dict[str, Any] = client.add_task_participant(
                task_uuid, user_uuid=user, role=role, idempotency_key=idempotency_key
            )
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Participant added")


_PARTICIPANT_COLUMNS: list[tuple[str, str, bool]] = [
    ("Name", "member.name", False),
    ("Role", "role", True),
    ("Source", "source", True),
    ("Muted", "is_muted", True),
    ("User UUID", "member.uuid", True),
]
_RELATION_COLUMNS: list[tuple[str, str, bool]] = [
    ("Relation", "relation_type", True),
    ("Direction", "direction", True),
    ("Task", "other_task.key", True),
    ("Title", "other_task.title", False),
    ("Relation UUID", "uuid", True),
]


@task_participants.command("list")
@click.argument("task_uuid", metavar="TASK")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def participants_list(task_uuid: str, json_mode: bool) -> None:
    """List who is on a task and who watches it.

    \b
    The owner and the creator are not repeated as rows unless they muted the card.

    \b
    Examples:
      dailybot task participants list ENG-142
      dailybot task participants list ENG-142 --json
    """
    client = require_auth()
    try:
        with console.status("Reading the participants..."):
            data: Any = client.list_task_participants(task_uuid)
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_rows(
        "Participants", rows_of(data), _PARTICIPANT_COLUMNS, empty="Nobody else is on this task."
    )


@task_participants.command("remove")
@click.argument("task_uuid", metavar="TASK")
@click.argument("user_uuid", metavar="USER")
@click.option("--dry-run", is_flag=True, help="Say what would happen and send nothing.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the confirmation.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def participants_remove(
    task_uuid: str, user_uuid: str, dry_run: bool, assume_yes: bool, json_mode: bool
) -> None:
    """Take someone off a task. To stay on it quietly, use `task mute` instead.

    \b
    Examples:
      dailybot task participants remove ENG-142 <user-uuid> --dry-run
      dailybot task participants remove ENG-142 <user-uuid> --yes
    """
    _require_person_for("task participants remove", json_mode=json_mode)
    if not confirm_without_preview(
        f"take user {user_uuid} off task {task_uuid}; they stop being notified about it.",
        assume_yes=assume_yes,
        dry_run=dry_run,
        json_mode=json_mode,
    ):
        return
    client = require_auth()
    try:
        with console.status("Removing the participant..."):
            client.remove_task_participant(task_uuid, user_uuid)
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json({"removed": True, "task": task_uuid, "user": user_uuid})
        return
    print_success("Participant removed.")


def _set_own_mute(task_uuid: str, muted: bool, json_mode: bool) -> None:
    """Record the caller's mute on a task: POST participants/ for yourself with `is_muted`."""
    action: str = "task mute" if muted else "task unmute"
    _require_person_for(action, json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Reading who you are..."):
            me: dict[str, Any] = client.get_me()
        my_uuid: Any = me.get("uuid")
        if not my_uuid:
            raise click.ClickException("Could not tell who you are from `dailybot me`.")
        with console.status("Muting the task..." if muted else "Unmuting the task..."):
            data: dict[str, Any] = client.add_task_participant(
                task_uuid, user_uuid=str(my_uuid), is_muted=muted
            )
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Muted — you stay on the task." if muted else "Unmuted.")


@task.command("mute")
@click.argument("task_uuid", metavar="TASK")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_mute(task_uuid: str, json_mode: bool) -> None:
    """Stop notifications from a task while staying on it. Needs `dailybot login`.

    \b
    Examples:
      dailybot task mute ENG-142
    """
    _set_own_mute(task_uuid, True, json_mode)


@task.command("unmute")
@click.argument("task_uuid", metavar="TASK")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_unmute(task_uuid: str, json_mode: bool) -> None:
    """Resume notifications from a task you muted. Needs `dailybot login`.

    \b
    Examples:
      dailybot task unmute ENG-142
    """
    _set_own_mute(task_uuid, False, json_mode)


@task.command("watch")
@click.argument("task_uuid", metavar="TASK")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_watch(task_uuid: str, json_mode: bool) -> None:
    """Follow a task's notifications without being on it. Needs `dailybot login`.

    \b
    Watching is private: nobody is told you started following the task.

    \b
    Examples:
      dailybot task watch ENG-142
    """
    _require_person_for("task watch", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Watching the task..."):
            data: dict[str, Any] = client.subscribe_task(task_uuid)
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_success("Watching.")


@task.command("unwatch")
@click.argument("task_uuid", metavar="TASK")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_unwatch(task_uuid: str, json_mode: bool) -> None:
    """Stop following a task. Needs `dailybot login`.

    \b
    Examples:
      dailybot task unwatch ENG-142
    """
    _require_person_for("task unwatch", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Unwatching the task..."):
            client.unsubscribe_task(task_uuid)
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json({"subscribed": False, "task": task_uuid})
        return
    print_success("No longer watching.")


@task.command("relations")
@click.argument("task_uuid", metavar="TASK")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_relations(task_uuid: str, json_mode: bool) -> None:
    """List a task's links to other tasks.

    \b
    `blocks` + `incoming` is what "blocked by" means. Unlink with the relation
    uuid shown here: `dailybot task unlink <task> <relation-uuid>`.

    \b
    Examples:
      dailybot task relations ENG-142
      dailybot task relations ENG-142 --json
    """
    client = require_auth()
    try:
        with console.status("Reading the relations..."):
            data: Any = client.list_task_relations(task_uuid)
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_rows("Relations", rows_of(data), _RELATION_COLUMNS, empty="No linked tasks.")


@task.command("unlink")
@click.argument("task_uuid", metavar="TASK")
@click.argument("relation_uuid", metavar="RELATION")
@click.option("--dry-run", is_flag=True, help="Say what would happen and send nothing.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the confirmation.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_unlink(
    task_uuid: str, relation_uuid: str, dry_run: bool, assume_yes: bool, json_mode: bool
) -> None:
    """Remove a link between two tasks. Recreate it with `task link`.

    \b
    Examples:
      dailybot task unlink ENG-142 <relation-uuid> --dry-run
      dailybot task unlink ENG-142 <relation-uuid> --yes
    """
    if not confirm_without_preview(
        f"remove relation {relation_uuid} from task {task_uuid}.",
        assume_yes=assume_yes,
        dry_run=dry_run,
        json_mode=json_mode,
    ):
        return
    client = require_auth()
    try:
        with console.status("Unlinking..."):
            client.delete_task_relation(task_uuid, relation_uuid)
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json({"unlinked": True, "task": task_uuid, "relation": relation_uuid})
        return
    print_success("Unlinked.")


@task.command("comment-edit")
@click.argument("task_uuid", metavar="TASK")
@click.argument("comment_uuid", metavar="COMMENT")
@click.argument("body")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_comment_edit(task_uuid: str, comment_uuid: str, body: str, json_mode: bool) -> None:
    """Replace a comment's text. `-` reads the new body from stdin.

    \b
    Mention somebody with `<@DB@{user-uuid}>`. The comment is marked edited.

    \b
    Examples:
      dailybot task comment-edit ENG-142 <comment-uuid> "Deployed to staging and prod"
      echo "corrected note" | dailybot task comment-edit ENG-142 <comment-uuid> -
    """
    text: str = _read_body(body)
    if not text:
        raise click.UsageError("The new comment body is empty.")
    client = require_auth()
    try:
        with console.status("Editing the comment..."):
            data: dict[str, Any] = client.update_task_comment(task_uuid, comment_uuid, body=text)
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Comment edited")


@task.command("comment-delete")
@click.argument("task_uuid", metavar="TASK")
@click.argument("comment_uuid", metavar="COMMENT")
@click.option("--dry-run", is_flag=True, help="Say what would happen and send nothing.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the confirmation.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_comment_delete(
    task_uuid: str, comment_uuid: str, dry_run: bool, assume_yes: bool, json_mode: bool
) -> None:
    """Delete a comment. Its text is blanked; the entry stays so history resolves.

    \b
    Examples:
      dailybot task comment-delete ENG-142 <comment-uuid> --dry-run
      dailybot task comment-delete ENG-142 <comment-uuid> --yes
    """
    if not confirm_without_preview(
        f"delete comment {comment_uuid} on task {task_uuid}; its text cannot be recovered.",
        assume_yes=assume_yes,
        dry_run=dry_run,
        json_mode=json_mode,
    ):
        return
    client = require_auth()
    try:
        with console.status("Deleting the comment..."):
            client.delete_task_comment(task_uuid, comment_uuid)
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json({"deleted": True, "task": task_uuid, "comment": comment_uuid})
        return
    print_success("Comment deleted.")


_EVENT_COLUMNS: list[tuple[str, str, bool]] = [
    ("When", "created_at", True),
    ("Type", "type", True),
    ("Actor", "actor.name", False),
]


@task.command("children")
@click.argument("task_uuid", metavar="TASK")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_children(task_uuid: str, json_mode: bool) -> None:
    """List a task's direct sub-tasks.

    \b
    Examples:
      dailybot task children ENG-142
      dailybot task children ENG-142 --json
    """
    client = require_auth()
    try:
        with console.status("Reading the sub-tasks..."):
            data: Any = client.list_task_children(task_uuid)
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_table(rows_of(data))


@task.command("duplicate")
@click.argument("task_uuid", metavar="TASK")
@click.option(
    "--include",
    type=click.Choice(DUPLICATE_FIELDS),
    multiple=True,
    help="Fields to copy (repeatable). Default: title, description and labels.",
)
@click.option(
    "--idempotency-key",
    default=None,
    help="Reuse a key to make a retry safe. Generated automatically when omitted.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_duplicate(
    task_uuid: str, include: tuple[str, ...], idempotency_key: str | None, json_mode: bool
) -> None:
    """Copy a task into the same column, with a new key.

    \b
    An idempotency key is always sent and printed (`_idempotency_key` under --json).
    Pass it back with --idempotency-key when retrying after a timeout: the server
    then returns the same copy instead of making a second one.

    \b
    Examples:
      dailybot task duplicate ENG-142
      dailybot task duplicate ENG-142 --include title --include owner --include due_date --json
      dailybot task duplicate ENG-142 --idempotency-key copy-eng-142
    """
    client = require_auth()
    try:
        with console.status("Duplicating the task..."):
            data: dict[str, Any] = client.duplicate_task(
                task_uuid,
                include=list(include) if include else None,
                idempotency_key=idempotency_key,
            )
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Duplicated as {data.get('key') or data.get('uuid') or 'a new task'}")


@task.command("events")
@click.argument("task_uuid", metavar="TASK")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_events(task_uuid: str, json_mode: bool) -> None:
    """List a task's raw event history (created, moved, owner changed, …).

    \b
    For the readable feed with before/after values, use `dailybot task activity`.

    \b
    Examples:
      dailybot task events ENG-142
      dailybot task events ENG-142 --json
    """
    client = require_auth()
    try:
        with console.status("Reading the events..."):
            data: Any = client.list_task_events(task_uuid)
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_rows("Events", rows_of(data), _EVENT_COLUMNS, empty="No events.")


@task.command("activity")
@click.argument("task_uuid", metavar="TASK")
@click.option(
    "--updated-since",
    "updated_since",
    default=None,
    help="Only activity after this ISO-8601 timestamp.",
)
@click.option("--type", "event_type", default=None, help="Only this kind of activity.")
@paging_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_activity(
    task_uuid: str,
    updated_since: str | None,
    event_type: str | None,
    json_mode: bool,
    **flags: Any,
) -> None:
    """Show one task's activity feed — what changed, who changed it, from and to.

    \b
    Examples:
      dailybot task activity ENG-142
      dailybot task activity ENG-142 --updated-since 2026-09-20T00:00:00Z --json
    """
    params: dict[str, Any] = {}
    if updated_since:
        params["updated_since"] = as_query_datetime(updated_since)
    if event_type:
        params["type"] = event_type
    client = require_auth()
    try:
        spec = build_query_params(**flags)
        with console.status("Reading the activity..."):
            result: PaginatedResult = client.list_task_activity(
                task_uuid,
                params=params or None,
                page=spec.page,
                page_size=spec.page_size,
                fetch_all=spec.fetch_all,
                limit=spec.limit,
            )
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(_envelope(result))
        return
    print_tasks_rows("Activity", result.results, _EVENT_COLUMNS, empty="No activity.")
    print_pagination_footer(
        len(result.results),
        result.count,
        has_more=bool(result.next),
        more_hint=PAGING_ONLY_MORE_HINT,
    )


_ATTACHMENT_COLUMNS: list[tuple[str, str, bool]] = [
    ("File", "filename", False),
    ("Type", "content_type", True),
    ("Bytes", "size", True),
    ("Status", "status", True),
    ("UUID", "uuid", True),
]
_MIB: int = 1024 * 1024
DEFAULT_CONTENT_TYPE: str = "application/octet-stream"


def _guess_content_type(path: Path) -> str:
    """The file's MIME type from its name; `application/octet-stream` when unknown."""
    guessed, _encoding = mimetypes.guess_type(path.name)
    return guessed or DEFAULT_CONTENT_TYPE


@task.command("attach")
@click.argument("task_uuid", metavar="TASK")
@click.argument(
    "file_path",
    metavar="FILE",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
)
@click.option(
    "--caption",
    default=None,
    help=f"Short caption. Uses the one-request upload, limited to "
    f"{ATTACHMENT_MULTIPART_MAX_BYTES // _MIB} MiB.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_attach(task_uuid: str, file_path: Path, caption: str | None, json_mode: bool) -> None:
    """Attach a file to a task.

    \b
    One command for three steps: reserve an upload target, send the bytes there,
    confirm. Files up to 25 MiB (5 MiB on a server without object storage). Your
    Dailybot credentials are only ever sent to the Dailybot API, never to the
    storage host, and a redirect during the upload is refused, not followed.

    \b
    Examples:
      dailybot task attach ENG-142 ./crash.log
      dailybot task attach ENG-142 ./screenshot.png --caption "After the fix" --json
    """
    size: int = file_path.stat().st_size
    limit: int = ATTACHMENT_MULTIPART_MAX_BYTES if caption else ATTACHMENT_MAX_SIZE_BYTES
    if size == 0:
        raise click.UsageError(f"{file_path.name} is empty; there is nothing to attach.")
    if size > limit:
        where: str = "with --caption" if caption else "per file"
        raise click.UsageError(
            f"{file_path.name} is {size / _MIB:.1f} MiB; the limit {where} is "
            f"{limit // _MIB} MiB. Nothing was uploaded."
        )
    content_type: str = _guess_content_type(file_path)
    data: bytes = file_path.read_bytes()
    client = require_auth()
    try:
        if caption:
            with console.status("Uploading the file..."):
                result: dict[str, Any] = client.upload_attachment_multipart(
                    task_uuid,
                    filename=file_path.name,
                    content_type=content_type,
                    data=data,
                    caption=caption,
                )
        else:
            with console.status("Reserving an upload target..."):
                presign: dict[str, Any] = client.presign_attachment(
                    task_uuid, filename=file_path.name, content_type=content_type, size=size
                )
            attachment_uuid: str = str((presign.get("attachment") or {}).get("uuid") or "")
            if not attachment_uuid:
                raise click.ClickException(
                    "The server reserved no attachment, so nothing was uploaded."
                )
            with console.status("Uploading the file..."):
                client.upload_attachment_bytes(presign, data)
            with console.status("Confirming..."):
                result = client.confirm_attachment(task_uuid, attachment_uuid)
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(result)
        return
    print_success(f"Attached {file_path.name} ({size} bytes).")


@task.command("attachments")
@click.argument("task_uuid", metavar="TASK")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_attachments(task_uuid: str, json_mode: bool) -> None:
    """List a task's attachments.

    \b
    Examples:
      dailybot task attachments ENG-142
      dailybot task attachments ENG-142 --json
    """
    client = require_auth()
    try:
        with console.status("Reading the attachments..."):
            data: Any = client.list_task_attachments(task_uuid)
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_rows("Attachments", rows_of(data), _ATTACHMENT_COLUMNS, empty="No attachments.")


@task.group("attachment")
def task_attachment() -> None:
    """Download or delete one attachment.

    \b
    Examples:
      dailybot task attachment get ENG-142 <attachment-uuid> -o ./crash.log
      dailybot task attachment delete ENG-142 <attachment-uuid> --dry-run
    """


@task_attachment.command("get")
@click.argument("task_uuid", metavar="TASK")
@click.argument("attachment_uuid", metavar="ATTACHMENT")
@click.option(
    "-o",
    "--output",
    "output",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    required=True,
    help="Where to write the file.",
)
@click.option("--force", is_flag=True, help="Overwrite the output file if it exists.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def attachment_get(
    task_uuid: str, attachment_uuid: str, output: Path, force: bool, json_mode: bool
) -> None:
    """Download an attachment to a file. Never overwrites without --force.

    \b
    Examples:
      dailybot task attachment get ENG-142 <attachment-uuid> -o ./crash.log
      dailybot task attachment get ENG-142 <attachment-uuid> -o ./crash.log --force --json
    """
    if output.exists() and not force:
        raise click.UsageError(f"{output} already exists. Pass --force to overwrite it.")
    client = require_auth()
    try:
        with console.status("Downloading..."):
            content: bytes = client.download_attachment(task_uuid, attachment_uuid)
    except APIError as exc:
        _write_error(exc, json_mode)
    output.write_bytes(content)
    if json_mode:
        emit_json({"path": str(output), "bytes": len(content), "attachment": attachment_uuid})
        return
    print_success(f"Saved {len(content)} bytes to {output}.")


@task_attachment.command("delete")
@click.argument("task_uuid", metavar="TASK")
@click.argument("attachment_uuid", metavar="ATTACHMENT")
@click.option("--dry-run", is_flag=True, help="Say what would happen and send nothing.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the confirmation.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def attachment_delete(
    task_uuid: str, attachment_uuid: str, dry_run: bool, assume_yes: bool, json_mode: bool
) -> None:
    """Remove an attachment from a task. This cannot be undone.

    \b
    Examples:
      dailybot task attachment delete ENG-142 <attachment-uuid> --dry-run
      dailybot task attachment delete ENG-142 <attachment-uuid> --yes
    """
    if not confirm_without_preview(
        f"delete attachment {attachment_uuid} from task {task_uuid}; the stored file goes too "
        "unless something else uses it.",
        assume_yes=assume_yes,
        dry_run=dry_run,
        json_mode=json_mode,
    ):
        return
    client = require_auth()
    try:
        with console.status("Deleting the attachment..."):
            client.delete_task_attachment(task_uuid, attachment_uuid)
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json({"deleted": True, "task": task_uuid, "attachment": attachment_uuid})
        return
    print_success("Attachment deleted.")


@task.command("archive")
@click.argument("task_uuid", metavar="TASK")
@click.option("--dry-run", is_flag=True, help="Show the consequence and exit without acting.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the prompt (still previews).")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_archive(
    task_uuid: str, dry_run: bool, assume_yes: bool, idempotency_key: str | None, json_mode: bool
) -> None:
    """Archive a task. Reversible.

    \b
    The server is asked to preview the consequence first, and that preview is
    always shown — including with --yes. It is the only place the cascade count
    and the restore path appear.

    \b
    Examples:
      dailybot task archive ENG-142 --dry-run
      dailybot task archive ENG-142 --yes
    """
    client = require_auth()
    if not preview_then_confirm(
        lambda: client.archive_task(task_uuid, dry_run=True),
        assume_yes=assume_yes,
        preview_only=dry_run,
        json_mode=json_mode,
    ):
        return
    try:
        with console.status("Archiving the task..."):
            data: dict[str, Any] = client.archive_task(
                task_uuid, dry_run=False, idempotency_key=idempotency_key
            )
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Task archived. Restore it with `dailybot task restore`.")


@task.command("delete")
@click.argument("task_uuid", metavar="TASK")
@click.option("--dry-run", is_flag=True, help="Show the consequence and exit without acting.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the prompt (still previews).")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_delete(
    task_uuid: str,
    dry_run: bool,
    assume_yes: bool,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Archive a task. An alias of `task archive` — nothing is destroyed.

    \b
    The server treats DELETE on a task as an archive: it is reversible and audited
    as `task.archived`. This command says "archived" for that reason, and names
    the restore path, rather than implying a deletion that does not happen.

    \b
    Examples:
      dailybot task delete ENG-142 --dry-run
    """
    client = require_auth()
    if not preview_then_confirm(
        lambda: client.archive_task(task_uuid, dry_run=True),
        assume_yes=assume_yes,
        preview_only=dry_run,
        json_mode=json_mode,
    ):
        return
    try:
        with console.status("Archiving the task..."):
            # This alias posts to the SAME archive door, which honours the header —
            # so it takes the same flag. Without it the CLI printed a key and told
            # the caller to pass it back through an option that did not exist.
            data: dict[str, Any] = client.archive_task(
                task_uuid, dry_run=False, idempotency_key=idempotency_key
            )
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Task archived (delete is an alias of archive; it is reversible).")


@task.command("restore")
@click.argument("task_uuid", metavar="TASK")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_restore(task_uuid: str, idempotency_key: str | None, json_mode: bool) -> None:
    """Restore an archived task.

    \b
    Note: restoring a BOARD does not restore the tasks that cascade-archived with
    it. Those are restored one by one, here.

    \b
    Examples:
      dailybot task restore ENG-142
    """
    client = require_auth()
    try:
        with console.status("Restoring the task..."):
            data: dict[str, Any] = client.restore_task(task_uuid, idempotency_key=idempotency_key)
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Task restored")


def _bulk_preview(operation: str, items: list[Any], board: str | None, json_mode: bool) -> None:
    """Show what a bulk call would do, via the server's run-and-roll-back dry run."""
    client = require_auth()
    try:
        with console.status(f"Previewing {escape(operation)} on {len(items)} item(s)..."):
            preview: dict[str, Any] = client.bulk_tasks(
                operation=operation, items=items, board=board, dry_run=True
            )
    except APIError as exc:
        if exc.code == "idempotency_key_required":
            # A server that predates the dry run treated this as a real bulk and refused
            # it for want of a key — which is exactly why nothing was written.
            message: str = (
                "This server cannot preview a bulk call yet (it has no bulk dry run), so "
                "nothing was sent for real and nothing changed. Run without --dry-run to "
                "apply, after checking the batch yourself."
            )
            if json_mode:
                emit_json(
                    {
                        "status": "error",
                        "code": "bulk_dry_run_unsupported",
                        "detail": exc.detail,
                        "message": message,
                    }
                )
            else:
                print_error(message)
            raise SystemExit(EXIT_USAGE_ERROR) from exc
        _write_error(exc, json_mode)
    refused: list[Any] = [r for r in preview.get("refused") or [] if isinstance(r, dict)]
    if json_mode:
        emit_json(preview)
    else:
        print_bulk_preview(preview)
    if refused:
        # The real call would fail for these items; an agent branching on the exit
        # must see that without parsing the preview.
        raise SystemExit(1)


@task.command("bulk")
@click.option(
    "--operation",
    required=True,
    type=click.Choice(BULK_OPERATIONS),
    help="Operation to apply to every item.",
)
@click.option(
    "-f",
    "--file",
    "batch_file",
    required=True,
    type=click.File("r"),
    help="JSON file with the item list, or `-` for stdin.",
)
@click.option(
    "--board",
    default=None,
    help="Board (uuid or key) every created task lands on. Required for --operation create.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Run the batch on the server and roll it back: shows each change, writes nothing.",
)
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the confirmation.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_bulk(
    operation: str,
    batch_file: Any,
    board: str | None,
    dry_run: bool,
    idempotency_key: str | None,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    """Apply one operation to up to 100 tasks in a single call.

    \b
    Preview first with --dry-run: the server runs the whole batch and rolls it back,
    so the changes and refusals it shows are the real ones, and nothing is written.
    A preview that predicts refusals exits 1.

    \b
    The real call always sends an idempotency key, so a batch that times out can be
    retried without applying twice. Items follow the contract: `{"task": "ENG-142",
    ...}` for most operations, `{"title": ...}` for create (with --board).

    \b
    Examples:
      dailybot task bulk --operation set_owner -f batch.json --dry-run
      dailybot task bulk --operation create --board ENG -f todo.json --yes --json
      echo '[{"task":"ENG-142"}]' | dailybot task bulk --operation archive -f - --json
    """
    try:
        items: Any = _json.load(batch_file)
    except ValueError as exc:
        raise click.BadParameter(f"Could not read the batch as JSON: {exc}") from exc
    if not isinstance(items, list) or not items:
        raise click.BadParameter("The batch must be a non-empty JSON array of items.")
    if len(items) > TASKS_BULK_MAX_ITEMS:
        raise click.BadParameter(
            f"{len(items)} items exceeds the server cap of {TASKS_BULK_MAX_ITEMS} per call. "
            "Split the batch and send it in chunks."
        )
    if operation == "create" and not board:
        raise click.UsageError("--operation create needs --board: every task lands on one board.")

    if dry_run:
        _bulk_preview(operation, items, board, json_mode)
        return

    if not assume_yes:
        # `--operation` is validated, but items echo caller input, so the notice is
        # escaped markup either way. Under --json it goes to stderr so stdout stays one
        # parseable document, exactly as `_destructive.preview_then_confirm` does.
        notice: Console = error_console if json_mode else console
        notice.print(
            f"About to apply [bold]{escape(operation)}[/bold] to "
            f"[bold]{len(items)}[/bold] item(s). Preview it first with --dry-run."
        )
        if not click.confirm("Proceed?", default=False, err=json_mode):
            aborted: str = "Aborted. Nothing was changed."
            if json_mode:
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

    client = require_auth()
    try:
        with console.status(f"Applying {escape(operation)} to {len(items)} item(s)..."):
            data: dict[str, Any] = client.bulk_tasks(
                operation=operation, items=items, board=board, idempotency_key=idempotency_key
            )
    except APIError as exc:
        _write_error(exc, json_mode)

    # The failed-row scan happens BEFORE the --json branch: a partial failure must
    # exit non-zero in both modes. It used to be human-only, so an agent reading
    # only the process exit saw 0 while the same call told a person it had failed.
    results: Any = data.get("results") or []
    failed: list[dict[str, Any]] = [
        row for row in results if isinstance(row, dict) and row.get("status") == "error"
    ]

    if json_mode:
        emit_json(data)
        # Multi-item calls tolerate partial progress; exiting 0 would hide it.
        raise SystemExit(1 if failed else 0)

    report_write(
        data,
        f"Bulk {escape(operation)}: {len(results) - len(failed)} succeeded, {len(failed)} failed",
    )
    for row in failed:
        # Both values are echoed from the caller's own batch file, so both are
        # untrusted for markup purposes — the same footgun as `--operation`, except
        # this one fires *after* the success line has already printed.
        console.print(
            f"  [red]failed[/red] {escape(str(row.get('task') or row.get('uuid') or '?'))} "
            f"[dim]{escape(str(row.get('code', '')))}[/dim]"
        )
    if failed:
        raise SystemExit(1)
