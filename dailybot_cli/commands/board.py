"""Board commands (``/v1/tasks/boards/*``).

The snapshot is the intentionally dense door: one request gives an agent cold
context, and it is where every ``full_resync_required`` sends you back to. It
also carries ``delta_cursor`` — the only place a caller can obtain one, because
the delta door's own refusal for a missing cursor does not say where to get it.
That handoff is named in both commands' help on purpose.
"""

from collections.abc import Callable
from typing import Any

import click

from dailybot_cli.api_client import APIError, PaginatedResult
from dailybot_cli.commands._beta import mark_beta
from dailybot_cli.commands._destructive import preview_then_confirm
from dailybot_cli.commands._writes import named, report_write
from dailybot_cli.commands.public_api_helpers import (
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
    print_board_snapshot,
    print_boards_table,
    print_pagination_footer,
    print_tasks_detail_panel,
    print_tasks_rows,
    print_tasks_table,
)

_BOARD_FIELDS: list[tuple[str, str]] = [
    ("Name", "name"),
    ("Key", "key"),
    ("UUID", "uuid"),
    ("Archived", "is_archived"),
]


def _envelope(result: PaginatedResult) -> dict[str, Any]:
    return {
        "count": result.count,
        "next": result.next,
        "previous": result.previous,
        "results": result.results,
    }


@click.group()
def board() -> None:
    """Read Dailybot Tasks boards.

    \b
    `board snapshot` is the one call that gives cold context in a single request,
    and it carries the cursor `dailybot tasks changes` consumes.

    \b
    Examples:
      dailybot board list
      dailybot board snapshot <board-uuid>
    """


mark_beta(board)


@board.command("list")
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_list(json_mode: bool, **flags: Any) -> None:
    """List boards.

    \b
    Examples:
      dailybot board list
      dailybot board list --json
    """
    client = require_auth()
    try:
        spec = build_query_params(**flags)
        with console.status("Reading boards..."):
            result: PaginatedResult = client.list_boards(
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
    print_boards_table(result.results)
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))


@board.command("get")
@click.argument("board_uuid")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_get(board_uuid: str, json_mode: bool) -> None:
    """Show one board's metadata.

    \b
    Examples:
      dailybot board get <board-uuid>
    """
    client = require_auth()
    try:
        with console.status("Reading the board..."):
            data: dict[str, Any] = client.get_board(board_uuid)
    except APIError as exc:
        # Isolation is 404-not-403: routed through the shared mapper so the exit
        # code and the --json payload match the documented table.
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_detail_panel("Board", data, _BOARD_FIELDS)


@board.command("tasks")
@click.argument("board_uuid", metavar="BOARD")
@paging_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_tasks(board_uuid: str, json_mode: bool, **flags: Any) -> None:
    """List the tasks on one board.

    \b
    One page per call, like `task list`: follow `next` with --page. For the whole
    board in a single request (columns included), use `board snapshot`.

    \b
    Examples:
      dailybot board tasks <board-uuid>
      dailybot board tasks <board-uuid> --page 2 --json
    """
    client = require_auth()
    try:
        spec = build_query_params(**flags)
        with console.status("Reading the board's tasks..."):
            result: PaginatedResult = client.list_board_tasks(
                board_uuid,
                page=spec.page,
                page_size=spec.page_size,
                fetch_all=spec.fetch_all,
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


def _rows(data: Any) -> list[dict[str, Any]]:
    """The rows of a board sub-collection, whether it arrives as a list or an envelope."""
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return [row for row in data["results"] if isinstance(row, dict)]
    return []


def _require_person(action: str, reason: str, *, json_mode: bool) -> None:
    """Refuse an API key on a person-only board door, before any request is spent."""
    if get_token() is None:
        refuse_without_person(
            f"`{action}` {reason} Run `dailybot login` and retry as a signed-in person.",
            json_mode=json_mode,
        )


# Column specs for the board sub-collections: (header, field path, trusted).
_STATE_COLUMNS: list[tuple[str, str, bool]] = [
    ("Name", "name", False),
    ("Category", "category", True),
    ("Archived", "is_archived", True),
    ("UUID", "uuid", True),
]
_MEMBER_COLUMNS: list[tuple[str, str, bool]] = [
    ("Name", "user.name", False),
    ("Role", "role", True),
    ("User UUID", "user.uuid", True),
]
_LABEL_COLUMNS: list[tuple[str, str, bool]] = [
    ("Name", "name", False),
    ("Color", "color", True),
    ("UUID", "uuid", True),
]
_VIEW_COLUMNS: list[tuple[str, str, bool]] = [
    ("Name", "name", False),
    ("Kind", "kind", True),
    ("UUID", "uuid", True),
]


def _read_board_collection(
    board_uuid: str,
    read: Callable[[str], Any],
    *,
    spinner: str,
    title: str,
    columns: list[tuple[str, str, bool]],
    empty: str,
    json_mode: bool,
) -> None:
    """Shared body of the board sub-collection reads: one GET, raw JSON or a table."""
    try:
        with console.status(spinner):
            data: Any = read(board_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_rows(title, _rows(data), columns, empty=empty)


@board.command("states")
@click.argument("board_uuid", metavar="BOARD")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_states(board_uuid: str, json_mode: bool) -> None:
    """List a board's states (its columns), archived ones included.

    \b
    Examples:
      dailybot board states <board-uuid>
      dailybot board states <board-uuid> --json
    """
    client = require_auth()
    _read_board_collection(
        board_uuid,
        client.list_board_states,
        spinner="Reading the board's states...",
        title="States",
        columns=_STATE_COLUMNS,
        empty="This board has no states.",
        json_mode=json_mode,
    )


@board.command("members")
@click.argument("board_uuid", metavar="BOARD")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_members(board_uuid: str, json_mode: bool) -> None:
    """List who can see a board, and their role on it.

    \b
    Examples:
      dailybot board members <board-uuid>
      dailybot board members <board-uuid> --json
    """
    client = require_auth()
    _read_board_collection(
        board_uuid,
        client.list_board_members,
        spinner="Reading the board's members...",
        title="Members",
        columns=_MEMBER_COLUMNS,
        empty="This board has no explicit members.",
        json_mode=json_mode,
    )


@board.command("labels")
@click.argument("board_uuid", metavar="BOARD")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_labels(board_uuid: str, json_mode: bool) -> None:
    """List the labels available on a board. Needs `dailybot login`.

    \b
    Label usage counts are computed for the person asking, so an organization API
    key has no correct answer here and is refused before the request.

    \b
    Examples:
      dailybot board labels <board-uuid>
      dailybot board labels <board-uuid> --json
    """
    _require_person(
        "board labels",
        "counts label usage for the person asking, which an organization API key is not.",
        json_mode=json_mode,
    )
    client = require_auth()
    _read_board_collection(
        board_uuid,
        client.list_board_labels,
        spinner="Reading the board's labels...",
        title="Labels",
        columns=_LABEL_COLUMNS,
        empty="This board has no labels.",
        json_mode=json_mode,
    )


@board.command("views")
@click.argument("board_uuid", metavar="BOARD")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_views(board_uuid: str, json_mode: bool) -> None:
    """List the saved views on a board.

    \b
    Examples:
      dailybot board views <board-uuid>
      dailybot board views <board-uuid> --json
    """
    client = require_auth()
    _read_board_collection(
        board_uuid,
        client.list_board_views,
        spinner="Reading the board's views...",
        title="Views",
        columns=_VIEW_COLUMNS,
        empty="This board has no saved views.",
        json_mode=json_mode,
    )


@board.command("snapshot")
@click.argument("board_uuid")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_snapshot(board_uuid: str, json_mode: bool) -> None:
    """Show the whole board in one request — the cold-context read.

    \b
    The response carries `delta_cursor`. Pass it to `dailybot tasks changes` to
    read only what changed since; that command's own refusal for a missing cursor
    does not say where to get one, so this is the place.

    \b
    Examples:
      dailybot board snapshot <board-uuid>
      dailybot board snapshot <board-uuid> --json
    """
    client = require_auth()
    try:
        with console.status("Reading the board snapshot..."):
            data: dict[str, Any] = client.get_board_snapshot(board_uuid)
    except APIError as exc:
        # Isolation is 404-not-403: routed through the shared mapper so the exit
        # code and the --json payload match the documented table.
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_board_snapshot(data)


def _require_person_for_admin(action: str, *, json_mode: bool) -> None:
    """Refuse a key on a door that needs `tasks:admin`.

    The scope cannot be granted to an API key at all — the validator refuses to
    store it, and the door refuses it independently. The plan's live probe measured
    an `ADMIN_ORG` **owner** refused exactly like a member, so the message must
    blame the **credential kind**. Telling an organization admin they "need to be an
    admin" would send them looking for a setting that cannot exist.
    """
    # See tasks.py `_require_person`: gate on the absence of a person token.
    if get_token() is None:
        refuse_without_person(
            f"`{action}` needs the `tasks:admin` scope, which an organization API key can "
            "never hold — it cannot even be stored on one. Run `dailybot login` and retry "
            "as a signed-in person.",
            json_mode=json_mode,
            admin=True,
        )


@board.command("create")
@click.option("-n", "--name", required=True, help="Board name.")
@click.option("-d", "--description", default=None, help="Board description.")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_create(
    name: str, description: str | None, idempotency_key: str | None, json_mode: bool
) -> None:
    """Create a board. Needs a signed-in person.

    \b
    An organization API key cannot do this: the `tasks:admin` scope it requires can
    never be held by a key. Run `dailybot login` first.

    \b
    Examples:
      dailybot board create --name "Design"
    """
    _require_person_for_admin("board create", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Creating the board..."):
            data: dict[str, Any] = client.create_board(
                name=name, description=description, idempotency_key=idempotency_key
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Created board {named(data, name)}")


@board.command("archive")
@click.argument("board_uuid")
@click.option("--dry-run", is_flag=True, help="Show the consequence and exit without acting.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the prompt (still previews).")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_archive(
    board_uuid: str, dry_run: bool, assume_yes: bool, idempotency_key: str | None, json_mode: bool
) -> None:
    """Archive a board. Every live task on it is cascade-archived.

    \b
    Restoring the board does NOT restore those tasks — they stay archived and are
    restored one by one. The preview names how many will cascade.

    \b
    Examples:
      dailybot board archive <board-uuid> --dry-run
    """
    client = require_auth()
    if not preview_then_confirm(
        lambda: client.archive_board(board_uuid, dry_run=True),
        assume_yes=assume_yes,
        preview_only=dry_run,
        json_mode=json_mode,
    ):
        return
    try:
        with console.status("Archiving the board..."):
            data: dict[str, Any] = client.archive_board(
                board_uuid, dry_run=False, idempotency_key=idempotency_key
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(
        data,
        "Board archived. Restoring it will NOT restore the tasks that cascaded — "
        "those stay archived and are restored one by one.",
    )


@board.command("restore")
@click.argument("board_uuid")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_restore(board_uuid: str, idempotency_key: str | None, json_mode: bool) -> None:
    """Restore an archived board.

    \b
    Tasks that cascade-archived with it stay archived. Restore them with
    `dailybot task restore`.

    \b
    Examples:
      dailybot board restore <board-uuid>
    """
    client = require_auth()
    try:
        with console.status("Restoring the board..."):
            data: dict[str, Any] = client.restore_board(board_uuid, idempotency_key=idempotency_key)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Board restored. Cascaded tasks stay archived.")
