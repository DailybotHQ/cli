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

from dailybot_cli.api_client import TASKS_BULK_MAX_ITEMS, APIError, PaginatedResult
from dailybot_cli.commands._destructive import preview_then_confirm
from dailybot_cli.commands.public_api_helpers import (
    EXIT_NOT_AUTHENTICATED,
    EXIT_USER_ABORTED,
    emit_json,
    exit_for_api_error,
    exit_for_tasks_error,
    require_auth,
)
from dailybot_cli.commands.query_options import build_query_params, query_options
from dailybot_cli.config import get_agent_auth
from dailybot_cli.display import (
    console,
    present_untrusted,
    print_error,
    print_pagination_footer,
    print_success,
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
IDEMPOTENCY_TTL_HOURS: int = 24

LABEL_MODES: tuple[str, ...] = ("add", "remove", "replace")

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
      dailybot task get <task-uuid>
    """


@task.command("list")
@click.option("-b", "--board", default=None, help="Only tasks on this board.")
@click.option("--state", default=None, help="Only tasks in this workflow state.")
@click.option("--assignee", default=None, help="Only tasks assigned to this user.")
@click.option("--label", default=None, help="Only tasks carrying this label.")
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
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_list(
    board: str | None,
    state: str | None,
    assignee: str | None,
    label: str | None,
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
    Examples:
      dailybot task list --board <board-uuid> --state doing
      dailybot task list --assignee <user-uuid> --include labels --json
    """
    client = require_auth()
    filters: dict[str, Any] = {}
    if board:
        filters["board"] = board
    if state:
        filters["state"] = state
    if assignee:
        filters["assignee"] = assignee
    if label:
        filters["label"] = label
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
                fetch_all=spec.fetch_all,
                limit=spec.limit,
            )
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(_envelope(result))
        return
    print_tasks_table(result.results)
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))


@task.command("get")
@click.argument("task_uuid")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_get(task_uuid: str, json_mode: bool) -> None:
    """Show one task.

    \b
    Prints the API self-link. No web URL is shown: the web app owns its path
    shapes and they are not published, so a link built here would be a guess.

    \b
    Examples:
      dailybot task get <task-uuid>
      dailybot task get <task-uuid> --json
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


def _report_write(result: dict[str, Any], what: str) -> None:
    """Report a write, distinguishing a fresh one from a server-side replay.

    A replay means the server recognised the idempotency key and returned the
    ORIGINAL result without performing a new write. Saying "created" there would
    be a lie the caller may act on.
    """
    if result.get("_idempotency_replayed"):
        print_success(
            f"{what} — already applied (the server replayed a previous identical call; "
            "nothing new was written)."
        )
        return
    print_success(what)


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
@click.option("--assignee", default=None, help="User to assign it to.")
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
    assignee: str | None,
    due: str | None,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Create a task.

    \b
    An idempotency key is always sent, so a retry that times out cannot create a
    second task. The server keeps that key for 24 hours: reusing it inside the
    window replays the original result, and reusing it AFTER the window is a new
    write that will duplicate.

    \b
    Examples:
      dailybot task create --title "Fix the flaky test" --board <board-uuid>
      dailybot task create -t "Ship it" --idempotency-key deploy-42 --json
    """
    client = require_auth()
    try:
        with console.status("Creating the task..."):
            data: dict[str, Any] = client.create_task(
                title=title,
                board=board,
                description=description,
                state=state,
                executor=assignee,
                due_date=due,
                idempotency_key=idempotency_key,
            )
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    _report_write(data, f"Created {present_untrusted(data.get('title') or title)}")
    print_task_detail(data)


@task.command("update")
@click.argument("task_uuid")
@click.option("-t", "--title", default=None, help="New title.")
@click.option("-d", "--description", default=None, help="New description.")
@click.option("--state", default=None, help="New workflow state.")
@click.option("--due", default=None, help="New due date (YYYY-MM-DD).")
@click.option("--priority", default=None, help="New priority.")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_update(
    task_uuid: str,
    title: str | None,
    description: str | None,
    state: str | None,
    due: str | None,
    priority: str | None,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Change fields on a task.

    \b
    Only the fields you pass are sent — this is a partial update, never a
    full-object overwrite, so a field you omit keeps its current value.

    \b
    Examples:
      dailybot task update <task-uuid> --state done
      dailybot task update <task-uuid> -t "Clearer title" --json
    """
    fields: dict[str, Any] = {
        "title": title,
        "description": description,
        "state": state,
        "due_date": due,
        "priority": priority,
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
    _report_write(data, "Task updated")


@task.command("move")
@click.argument("task_uuid")
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
      dailybot task move <task-uuid> --state done
      dailybot task move <task-uuid> --board <board-uuid>
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
    _report_write(data, "Task moved")


@task.command("assign")
@click.argument("task_uuid")
@click.option("--to", "assignee", required=True, help="User uuid to assign the task to.")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_assign(
    task_uuid: str, assignee: str, idempotency_key: str | None, json_mode: bool
) -> None:
    """Assign a task to someone.

    \b
    Examples:
      dailybot task assign <task-uuid> --to <user-uuid>
    """
    client = require_auth()
    try:
        with console.status("Assigning the task..."):
            data: dict[str, Any] = client.update_task(
                task_uuid, executor=assignee, idempotency_key=idempotency_key
            )
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    _report_write(data, "Task assigned")


def _require_person_for(action: str) -> None:
    """Refuse a key on a person-only door.

    Published policy: two writes no organization API key may ever make — changing
    who can see, and changing who is notified. Participants are the second.
    """
    if get_agent_auth() == "api_key":
        print_error(
            f"`{action}` changes who is notified, and no organization API key may do that — "
            "there is no person behind it to be accountable. Run `dailybot login` and retry."
        )
        raise SystemExit(EXIT_NOT_AUTHENTICATED)


def _read_body(value: str) -> str:
    """Read a body argument, or stdin when it is `-`."""
    if value == "-":
        return click.get_text_stream("stdin").read().strip()
    return value


@task.command("comment")
@click.argument("task_uuid")
@click.argument("body")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_comment(task_uuid: str, body: str, idempotency_key: str | None, json_mode: bool) -> None:
    """Comment on a task. Pass `-` as the body to read it from stdin.

    \b
    Examples:
      dailybot task comment <task-uuid> "Deployed to staging"
      echo "long note" | dailybot task comment <task-uuid> -
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
    _report_write(data, "Comment posted")


@task.command("comments")
@click.argument("task_uuid")
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
      dailybot task comments <task-uuid>
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
                fetch_all=spec.fetch_all,
                limit=spec.limit,
            )
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(_envelope(result))
        return
    print_task_comments(result.results)
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))


@task.command("link")
@click.argument("task_uuid")
@click.argument("other_uuid")
@click.option("--type", "relation", required=True, help="Relation type, e.g. blocks / relates-to.")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_link(
    task_uuid: str, other_uuid: str, relation: str, idempotency_key: str | None, json_mode: bool
) -> None:
    """Relate one task to another.

    \b
    Examples:
      dailybot task link <task-uuid> <other-uuid> --type blocks
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
    _report_write(data, "Tasks linked")


@task.command("labels")
@click.argument("task_uuid")
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
      dailybot task labels <task-uuid> --mode add --label <label-uuid>
      dailybot task labels <task-uuid> --mode replace --label a,b
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
    _report_write(data, "Labels updated")


@task.group("participants")
def task_participants() -> None:
    """Manage who is notified about a task.

    \b
    Person-only: no organization API key may change who is notified, because
    there is no person behind it to be accountable. Run `dailybot login`.
    """


@task_participants.command("add")
@click.argument("task_uuid")
@click.option("--user", required=True, help="User uuid to add as a participant.")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def participants_add(
    task_uuid: str, user: str, idempotency_key: str | None, json_mode: bool
) -> None:
    """Add a participant to a task.

    \b
    Examples:
      dailybot task participants add <task-uuid> --user <user-uuid>
    """
    _require_person_for("task participants add")
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
    _report_write(data, "Participant added")


@task.command("archive")
@click.argument("task_uuid")
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
      dailybot task archive <task-uuid> --dry-run
      dailybot task archive <task-uuid> --yes
    """
    client = require_auth()
    if not preview_then_confirm(
        lambda: client.archive_task(task_uuid, dry_run=True),
        assume_yes=assume_yes,
        preview_only=dry_run,
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
    _report_write(data, "Task archived. Restore it with `dailybot task restore`.")


@task.command("delete")
@click.argument("task_uuid")
@click.option("--dry-run", is_flag=True, help="Show the consequence and exit without acting.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the prompt (still previews).")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_delete(task_uuid: str, dry_run: bool, assume_yes: bool, json_mode: bool) -> None:
    """Archive a task. An alias of `task archive` — nothing is destroyed.

    \b
    The server treats DELETE on a task as an archive: it is reversible and audited
    as `task.archived`. This command says "archived" for that reason, and names
    the restore path, rather than implying a deletion that does not happen.

    \b
    Examples:
      dailybot task delete <task-uuid> --dry-run
    """
    client = require_auth()
    if not preview_then_confirm(
        lambda: client.archive_task(task_uuid, dry_run=True),
        assume_yes=assume_yes,
        preview_only=dry_run,
    ):
        return
    try:
        with console.status("Archiving the task..."):
            # The DELETE alias IGNORES Idempotency-Key, so none is offered here.
            data: dict[str, Any] = client.archive_task(task_uuid, dry_run=False)
    except APIError as exc:
        _write_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    _report_write(data, "Task archived (delete is an alias of archive; it is reversible).")


@task.command("restore")
@click.argument("task_uuid")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_restore(task_uuid: str, idempotency_key: str | None, json_mode: bool) -> None:
    """Restore an archived task.

    \b
    Note: restoring a BOARD does not restore the tasks that cascade-archived with
    it. Those are restored one by one, here.

    \b
    Examples:
      dailybot task restore <task-uuid>
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
    _report_write(data, "Task restored")


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
        console.print(
            f"About to apply [bold]{click.style(operation, bold=True)}[/bold] to "
            f"[bold]{len(items)}[/bold] item(s). There is no dry run for bulk."
        )
        if not click.confirm("Proceed?", default=False):
            print_error("Aborted. Nothing was changed.")
            raise SystemExit(EXIT_USER_ABORTED)

    client = require_auth()
    try:
        with console.status(f"Applying {operation} to {len(items)} item(s)..."):
            data: dict[str, Any] = client.bulk_tasks(
                operation=operation, items=items, idempotency_key=idempotency_key
            )
    except APIError as exc:
        _write_error(exc, json_mode)

    if json_mode:
        emit_json(data)
        return

    results: Any = data.get("results") or []
    failed: list[dict[str, Any]] = [
        row for row in results if isinstance(row, dict) and row.get("status") == "error"
    ]
    _report_write(
        data, f"Bulk {operation}: {len(results) - len(failed)} succeeded, {len(failed)} failed"
    )
    for row in failed:
        console.print(
            f"  [red]failed[/red] {row.get('uuid', '?')} [dim]{row.get('code', '')}[/dim]"
        )
    if failed:
        # Multi-item calls tolerate partial progress; exiting 0 would hide it.
        raise SystemExit(1)
