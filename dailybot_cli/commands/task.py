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
from typing import Any, NoReturn

import click
from rich.console import Console
from rich.markup import escape

from dailybot_cli.api_client import (
    TASKS_BULK_MAX_ITEMS,
    APIError,
    PaginatedResult,
)
from dailybot_cli.commands._beta import mark_beta
from dailybot_cli.commands._destructive import preview_then_confirm
from dailybot_cli.commands._writes import IDEMPOTENCY_TTL_HOURS, named, report_write
from dailybot_cli.commands.public_api_helpers import (
    EXIT_USER_ABORTED,
    emit_json,
    exit_for_tasks_error,
    refuse_without_person,
    require_auth,
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
    print_deprecation,
    print_error,
    print_pagination_footer,
    print_task_comments,
    print_task_detail,
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
@click.option("--priority", default=None, help="New priority.")
@click.option("--owner", default=None, help=OWNER_HELP)
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_update(
    task_uuid: str,
    title: str | None,
    description: str | None,
    state: str | None,
    due: str | None,
    priority: str | None,
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
@click.option("--state", default=None, help="Target workflow state (column).")
@click.option("--board", default=None, help="Target board.")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_move(
    task_uuid: str,
    state: str | None,
    board: str | None,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Move a task to another column or board.

    \b
    Examples:
      dailybot task move ENG-142 --state done
      dailybot task move ENG-142 --board <board-uuid>
    """
    if state is None and board is None:
        raise click.UsageError("Pass --state or --board (or both) to say where it should go.")
    client = require_auth()
    fields: dict[str, Any] = {k: v for k, v in {"state": state, "board": board}.items() if v}
    try:
        with console.status("Moving the task..."):
            data: dict[str, Any] = client.move_task(
                task_uuid, idempotency_key=idempotency_key, **fields
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
@click.option("--type", "relation", required=True, help="Relation type, e.g. blocks / relates-to.")
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
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def participants_add(
    task_uuid: str, user: str, idempotency_key: str | None, json_mode: bool
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
                task_uuid, user_uuid=user, idempotency_key=idempotency_key
            )
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Participant added")


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


@task.command("bulk")
@click.option("--operation", required=True, help="Operation to apply to every item.")
@click.option(
    "-f",
    "--file",
    "batch_file",
    required=True,
    type=click.File("r"),
    help="JSON file with the item list, or `-` for stdin.",
)
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the confirmation.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_bulk(
    operation: str, batch_file: Any, idempotency_key: str | None, assume_yes: bool, json_mode: bool
) -> None:
    """Apply one operation to many tasks in a single call.

    \b
    This is the only door that REQUIRES an idempotency key, so one is always sent:
    a batch that times out can be retried without applying twice. A replay returns
    the original result and writes once.

    \b
    There is NO dry run for bulk. The blast radius is bounded instead by the
    server's cap of 100 items per call, which this command enforces before
    sending.

    \b
    The item shape is the contract's, not a bespoke format.

    \b
    Examples:
      dailybot task bulk --operation archive -f batch.json --yes
      echo '[{"uuid":"..."}]' | dailybot task bulk --operation archive -f - --json
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

    if not assume_yes:
        # `--operation` is free-form caller input, so it must be escaped before it
        # reaches a Rich markup string: `[/bold][red]x` otherwise raises MarkupError
        # before the HTTP call and the root safety net blames the CLI for a bug.
        #
        # Under --json the warning and the prompt go to stderr, exactly as
        # `_destructive.preview_then_confirm` does: stdout must stay a single
        # parseable document, and the record of what was about to happen must survive.
        notice: Console = error_console if json_mode else console
        notice.print(
            f"About to apply [bold]{escape(operation)}[/bold] to "
            f"[bold]{len(items)}[/bold] item(s). There is no dry run for bulk."
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
                operation=operation, items=items, idempotency_key=idempotency_key
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
            f"  [red]failed[/red] {escape(str(row.get('uuid', '?')))} "
            f"[dim]{escape(str(row.get('code', '')))}[/dim]"
        )
    if failed:
        raise SystemExit(1)
