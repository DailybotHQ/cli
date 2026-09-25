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
from dailybot_cli.commands._destructive import confirm_without_preview, preview_then_confirm
from dailybot_cli.commands._favorites import require_person_for_favorites, star, unstar
from dailybot_cli.commands._writes import named, report_write
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_tasks_error,
    load_json_input,
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
    print_board_snapshot,
    print_boards_table,
    print_info,
    print_pagination_footer,
    print_raw_value,
    print_success,
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


BOARD_VISIBILITIES: tuple[str, ...] = ("org", "members")
BOARD_ESTIMATE_SCALES: tuple[str, ...] = ("none", "fibonacci", "linear")
# Fixed by the server and never customer-editable; there is deliberately no `blocked`.
STATE_CATEGORIES: tuple[str, ...] = ("backlog", "todo", "in_progress", "done", "canceled")


def _envelope(result: PaginatedResult) -> dict[str, Any]:
    return {
        "count": result.count,
        "next": result.next,
        "previous": result.previous,
        "results": result.results,
    }


@click.group()
def board() -> None:
    """Read and administer Dailybot Tasks boards.

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
@click.argument("board_uuid", metavar="BOARD")
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


def _require_person(action: str, reason: str, *, json_mode: bool) -> None:
    """Refuse an API key on a person-only board door, before any request is spent."""
    if get_token() is None:
        refuse_without_person(
            f"`{action}` {reason} Run `dailybot login` and retry as a signed-in person.",
            json_mode=json_mode,
        )


# Column specs for the board sub-collections: (header, field path, trusted).
_STATE_COLUMNS: list[tuple[str, str, bool]] = [
    ("Pos", "position", True),
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
    print_tasks_rows(title, rows_of(data), columns, empty=empty)


@board.command("states")
@click.argument("board_uuid", metavar="BOARD")
@click.option("--include-archived", is_flag=True, help="Also list retired columns.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_states(board_uuid: str, include_archived: bool, json_mode: bool) -> None:
    """List a board's states (its columns), left to right.

    \b
    Retired columns are hidden unless you pass --include-archived. A state's
    `category` (backlog, todo, in_progress, done, canceled) is fixed; its name is not.

    \b
    Examples:
      dailybot board states <board-uuid>
      dailybot board states <board-uuid> --include-archived --json
    """
    client = require_auth()
    _read_board_collection(
        board_uuid,
        lambda ref: client.list_board_states(ref, include_archived=include_archived),
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
@click.option(
    "--etag",
    "etag_only",
    is_flag=True,
    help="Print only the ETag `board view save --if-match` needs, and nothing else.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_views(board_uuid: str, etag_only: bool, json_mode: bool) -> None:
    """List your saved views on a board, with the ETag a save needs.

    \b
    Examples:
      dailybot board views <board-uuid>
      dailybot board views <board-uuid> --json > views.json
      ETAG=$(dailybot board views <board-uuid> --etag)
    """
    _require_person(
        "board views",
        "lists saved views, which belong to a person, and an organization API key is not one.",
        json_mode=json_mode,
    )
    client = require_auth()
    try:
        with console.status("Reading the board's views..."):
            data, etag = client.list_board_views_with_etag(board_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if etag_only:
        # Raw, unstyled, one line: this is a value for a shell variable.
        print_raw_value(etag or "")
        return
    if json_mode:
        emit_json(data)
        return
    print_tasks_rows("Views", rows_of(data), _VIEW_COLUMNS, empty="This board has no saved views.")
    if etag:
        print_info(f"ETag: {etag} (pass it to `board view save --if-match`)")


_MENTIONABLE_COLUMNS: list[tuple[str, str, bool]] = [
    ("Name", "name", False),
    ("Kind", "kind", True),
    ("UUID", "uuid", True),
    ("Mention as", "mention", True),
]


@board.command("mentionables")
@click.argument("board_uuid", metavar="BOARD")
@click.option(
    "-q",
    "--query",
    default=None,
    help="Only people whose name contains this text (case-insensitive).",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_mentionables(board_uuid: str, query: str | None, json_mode: bool) -> None:
    """Who you can @mention on this board, with the token to write. Needs `dailybot login`.

    \b
    Resolve a name to a uuid here, then write `<@DB@{uuid}>` in a comment or a project
    update to mention that person.

    \b
    Examples:
      dailybot board mentionables <board-uuid> -q jane
      dailybot board mentionables <board-uuid> --json
    """
    _require_person(
        "board mentionables",
        "answers who THIS viewer may address, and an organization API key is nobody.",
        json_mode=json_mode,
    )
    client = require_auth()
    try:
        with console.status("Reading who you can mention..."):
            data: Any = client.list_board_mentionables(board_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    rows: list[dict[str, Any]] = rows_of(data)
    if query:
        wanted: str = query.casefold()
        rows = [row for row in rows if wanted in str(row.get("name", "")).casefold()]
    if json_mode:
        # Unfiltered: the server's payload as-is. Filtered: the matching rows, as a list.
        emit_json(rows if query else data)
        return
    shown: list[dict[str, Any]] = [
        {**row, "mention": f"<@DB@{row['uuid']}>"}
        if row.get("uuid") and row.get("kind") in (None, "user")
        else row
        for row in rows
    ]
    print_tasks_rows("Mentionable", shown, _MENTIONABLE_COLUMNS, empty="Nobody matches.")


@board.command("star")
@click.argument("board_uuid", metavar="BOARD")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_star(board_uuid: str, json_mode: bool) -> None:
    """Pin a board to your favorites. Needs `dailybot login`.

    \b
    Examples:
      dailybot board star <board-uuid>
    """
    require_person_for_favorites("board star", json_mode=json_mode)
    star(require_auth(), "board", board_uuid, json_mode=json_mode)


@board.command("unstar")
@click.argument("board_uuid", metavar="BOARD")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_unstar(board_uuid: str, json_mode: bool) -> None:
    """Unpin a board from your favorites. Needs `dailybot login`.

    \b
    Examples:
      dailybot board unstar <board-uuid>
    """
    require_person_for_favorites("board unstar", json_mode=json_mode)
    unstar(require_auth(), "board", board_uuid, json_mode=json_mode)


# ---------------------------------------------------------------------------
# Columns (workflow states)
# ---------------------------------------------------------------------------


@board.group("state")
def board_state() -> None:
    """Create, rename, reorder, retire and restore a board's columns.

    \b
    Examples:
      dailybot board state create <board-uuid> -n "In review" --category in_progress
      dailybot board state reorder <board-uuid> <state-1> <state-2> <state-3>
    """


@board_state.command("create")
@click.argument("board_uuid", metavar="BOARD")
@click.option("-n", "--name", required=True, help="Column name (max 48 characters).")
@click.option(
    "--category",
    type=click.Choice(STATE_CATEGORIES),
    required=True,
    help="Fixed meaning of the column; it survives renames and never changes.",
)
@click.option(
    "--position",
    type=click.IntRange(min=0),
    default=None,
    help="Insert at this 1-based place among live columns (0 counts as 1; past the end "
    "goes last; omitted appends). Later columns shift right.",
)
@click.option("--color", default=None, help="Column color, e.g. #3b82f6.")
@click.option("--default", "is_default", is_flag=True, help="New tasks land in this column.")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_state_create(
    board_uuid: str,
    name: str,
    category: str,
    position: int | None,
    color: str | None,
    is_default: bool,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Add a column to a board.

    \b
    Examples:
      dailybot board state create <board-uuid> -n "In review" --category in_progress
      dailybot board state create <board-uuid> -n Blocked --category todo --position 2 --json
    """
    _require_person_for_admin("board state create", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Adding the column..."):
            data: dict[str, Any] = client.create_board_state(
                board_uuid,
                name=name,
                category=category,
                position=position,
                color=color,
                is_default=True if is_default else None,
                idempotency_key=idempotency_key,
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Added column {named(data, name)}")


@board_state.command("update")
@click.argument("board_uuid", metavar="BOARD")
@click.argument("state_uuid", metavar="STATE")
@click.option("-n", "--name", default=None, help="New column name.")
@click.option("--color", default=None, help="New column color.")
@click.option(
    "--position",
    type=click.IntRange(min=0),
    default=None,
    help="Move the column to this 1-based place among live columns (0 counts as 1; past "
    "the end goes last).",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_state_update(
    board_uuid: str,
    state_uuid: str,
    name: str | None,
    color: str | None,
    position: int | None,
    json_mode: bool,
) -> None:
    """Rename, recolor or move one column. Its category cannot change.

    \b
    Examples:
      dailybot board state update <board-uuid> <state-uuid> --name "Shipped"
      dailybot board state update <board-uuid> <state-uuid> --position 1 --json
    """
    _require_person_for_admin("board state update", json_mode=json_mode)
    fields: dict[str, Any] = {
        k: v
        for k, v in {"name": name, "color": color, "position": position}.items()
        if v is not None
    }
    if not fields:
        raise click.UsageError("Nothing to update. Pass --name, --color or --position.")
    client = require_auth()
    try:
        with console.status("Updating the column..."):
            data: dict[str, Any] = client.update_board_state(board_uuid, state_uuid, **fields)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Column updated")


@board_state.command("archive")
@click.argument("board_uuid", metavar="BOARD")
@click.argument("state_uuid", metavar="STATE")
@click.option(
    "--migrate-to",
    default=None,
    help="Move this column's live tasks to another live column first (state uuid).",
)
@click.option("--dry-run", is_flag=True, help="Show the consequence and exit without acting.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the prompt (still previews).")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_state_archive(
    board_uuid: str,
    state_uuid: str,
    migrate_to: str | None,
    dry_run: bool,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    """Retire a column. Reversible with `board state restore`.

    \b
    A column that still holds live tasks is refused (`state_in_use`) unless you
    name --migrate-to: every card moves there in one update before the column goes.

    \b
    Examples:
      dailybot board state archive <board-uuid> <state-uuid> --dry-run
      dailybot board state archive <board-uuid> <state-uuid> --migrate-to <other-state> --yes
    """
    _require_person_for_admin("board state archive", json_mode=json_mode)
    client = require_auth()
    if not preview_then_confirm(
        lambda: client.archive_board_state(
            board_uuid, state_uuid, migrate_to=migrate_to, dry_run=True
        ),
        assume_yes=assume_yes,
        preview_only=dry_run,
        json_mode=json_mode,
    ):
        return
    try:
        with console.status("Retiring the column..."):
            data: dict[str, Any] = client.archive_board_state(
                board_uuid, state_uuid, migrate_to=migrate_to
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Column retired. Restore it with `dailybot board state restore`.")


@board_state.command("restore")
@click.argument("board_uuid", metavar="BOARD")
@click.argument("state_uuid", metavar="STATE")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_state_restore(board_uuid: str, state_uuid: str, json_mode: bool) -> None:
    """Bring a retired column back, after the live ones. A live column is a no-op.

    \b
    Examples:
      dailybot board state restore <board-uuid> <state-uuid>
    """
    _require_person_for_admin("board state restore", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Restoring the column..."):
            data: dict[str, Any] = client.restore_board_state(board_uuid, state_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Column restored")


@board_state.command("reorder")
@click.argument("board_uuid", metavar="BOARD")
@click.argument("state_uuids", metavar="STATE...", nargs=-1, required=True)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_state_reorder(board_uuid: str, state_uuids: tuple[str, ...], json_mode: bool) -> None:
    """Set the left-to-right order of every live column in one call.

    \b
    List EVERY live column exactly once. A partial list, an unknown uuid or a
    duplicate is refused (`states_reorder_invalid`); read the current set with
    `dailybot board states <board>`.

    \b
    Examples:
      dailybot board state reorder <board-uuid> <backlog> <todo> <doing> <done>
    """
    _require_person_for_admin("board state reorder", json_mode=json_mode)
    if len(set(state_uuids)) != len(state_uuids):
        raise click.UsageError("A column appears twice. List each live column exactly once.")
    client = require_auth()
    try:
        with console.status("Reordering the columns..."):
            data: Any = client.reorder_board_states(board_uuid, list(state_uuids))
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_rows("States", rows_of(data), _STATE_COLUMNS, empty="No live columns.")


# ---------------------------------------------------------------------------
# Members (who can see a board) — person-only writes
# ---------------------------------------------------------------------------

_MEMBER_WRITE_REASON: str = (
    "changes who can see the board, and no organization API key may do that — there is "
    "no person behind it to be accountable."
)


@board.group("member")
def board_member() -> None:
    """Add or remove the people who can see a board. Needs `dailybot login`.

    \b
    There is no board-level role: organization roles plus board visibility are the
    whole access model, so a membership can be added or removed but not edited.

    \b
    Examples:
      dailybot board member add <board-uuid> <user-uuid>
      dailybot board member remove <board-uuid> <user-uuid> --dry-run
    """


@board_member.command("add")
@click.argument("board_uuid", metavar="BOARD")
@click.argument("user_uuid", metavar="[USER]", required=False, default=None)
@click.option(
    "--team",
    "team_uuid",
    default=None,
    help="A whole team (uuid) instead of one person; membership follows the team live.",
)
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_member_add(
    board_uuid: str,
    user_uuid: str | None,
    team_uuid: str | None,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Give a person or a whole team sight of a board. Adding an existing member is a no-op.

    \b
    Adding yourself to a private board you manage is visible to its members — it is
    recorded as an event, never a silent capability.

    \b
    Examples:
      dailybot board member add <board-uuid> <user-uuid>
      dailybot board member add <board-uuid> --team <team-uuid> --json
    """
    _require_person_for_admin("board member add", json_mode=json_mode)
    if (user_uuid is None) == (team_uuid is None):
        raise click.UsageError("Pass exactly one of USER or --team.")
    client = require_auth()
    try:
        with console.status("Adding the member..."):
            data: dict[str, Any] = client.add_board_member(
                board_uuid, user_uuid, team_uuid=team_uuid, idempotency_key=idempotency_key
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Member added")


@board_member.command("remove")
@click.argument("board_uuid", metavar="BOARD")
@click.argument("user_uuid", metavar="USER")
@click.option("--dry-run", is_flag=True, help="Say what would happen and send nothing.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the confirmation.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_member_remove(
    board_uuid: str, user_uuid: str, dry_run: bool, assume_yes: bool, json_mode: bool
) -> None:
    """Take someone's sight of a board away.

    \b
    The last member of a private board cannot be removed
    (`last_grant_cannot_be_removed`): a private board with nobody in it is
    readable by nobody.

    \b
    Examples:
      dailybot board member remove <board-uuid> <user-uuid> --dry-run
      dailybot board member remove <board-uuid> <user-uuid> --yes
    """
    _require_person_for_admin("board member remove", json_mode=json_mode)
    if not confirm_without_preview(
        f"remove user {user_uuid} from board {board_uuid}; they lose sight of it if it is private.",
        assume_yes=assume_yes,
        dry_run=dry_run,
        json_mode=json_mode,
    ):
        return
    client = require_auth()
    try:
        with console.status("Removing the member..."):
            client.remove_board_member(board_uuid, user_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json({"removed": True, "board": board_uuid, "user": user_uuid})
        return
    print_success("Member removed.")


# ---------------------------------------------------------------------------
# Labels and saved views — person-only writes
# ---------------------------------------------------------------------------


@board.group("label")
def board_label() -> None:
    """Create labels from a board. Needs `dailybot login`.

    \b
    Labels are the organization's shared taxonomy (the same set forms and check-ins
    use); edit or retire them with `dailybot label`.

    \b
    Examples:
      dailybot board label create <board-uuid> -n bug --color "#ef4444"
    """


@board_label.command("create")
@click.argument("board_uuid", metavar="BOARD")
@click.option("-n", "--name", required=True, help="Label name.")
@click.option("--color", default=None, help="Label color, e.g. #ef4444.")
@click.option("-d", "--description", default=None, help="What the label means.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_label_create(
    board_uuid: str, name: str, color: str | None, description: str | None, json_mode: bool
) -> None:
    """Create an organization label from this board.

    \b
    Examples:
      dailybot board label create <board-uuid> -n bug --color "#ef4444"
      dailybot board label create <board-uuid> -n "needs design" --json
    """
    _require_person(
        "board label create",
        "creates an organization label, which needs a signed-in person.",
        json_mode=json_mode,
    )
    client = require_auth()
    try:
        with console.status("Creating the label..."):
            data: dict[str, Any] = client.create_board_label(
                board_uuid, name=name, color=color, description=description
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Created label {named(data, name)}")


@board.group("view")
def board_view() -> None:
    """Save your views of a board. Needs `dailybot login`.

    \b
    Examples:
      dailybot board view save <board-uuid> -f views.json --if-match '"3"'
    """


@board_view.command("save")
@click.argument("board_uuid", metavar="BOARD")
@click.option(
    "-f",
    "--file",
    "views_file",
    type=click.File("r"),
    required=True,
    help="JSON array of views (`-` reads stdin). It REPLACES your whole list.",
)
@click.option(
    "--if-match",
    default=None,
    help="The ETag `board views` showed. Protects against overwriting a concurrent save.",
)
@click.option(
    "--fetch-etag",
    is_flag=True,
    help="Read the current ETag first instead of passing --if-match (narrower protection).",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_view_save(
    board_uuid: str,
    views_file: Any,
    if_match: str | None,
    fetch_etag: bool,
    json_mode: bool,
) -> None:
    """Replace your saved views on a board with the array in a file.

    \b
    This replaces the WHOLE list, so the server requires the ETag you read: with
    --if-match you prove you saw the latest list; --fetch-etag reads it now, which
    only guards the moment between that read and this write.

    \b
    Examples:
      dailybot board views <board-uuid> --json > views.json
      dailybot board view save <board-uuid> -f views.json --if-match '"3"'
      dailybot board view save <board-uuid> -f views.json --fetch-etag --json
    """
    if (if_match is None) == (not fetch_etag):
        raise click.UsageError("Pass exactly one of --if-match <etag> or --fetch-etag.")
    try:
        views: Any = load_json_input(views_file)
    except ValueError as exc:
        raise click.BadParameter(f"not valid JSON: {exc}", param_hint="--file") from exc
    if not isinstance(views, list):
        raise click.BadParameter("must be a JSON array of views.", param_hint="--file")
    _require_person(
        "board view save",
        "saves views that belong to a person, and an organization API key is not one.",
        json_mode=json_mode,
    )
    client = require_auth()
    try:
        etag: str | None = if_match
        if fetch_etag:
            with console.status("Reading the current views..."):
                _current, etag = client.list_board_views_with_etag(board_uuid)
            if etag is None:
                raise click.ClickException(
                    "The server returned no ETag for this board's views, so a save cannot be "
                    "made safely. Nothing was changed."
                )
        with console.status("Saving the views..."):
            data: Any = client.save_board_views(board_uuid, views, if_match=str(etag))
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_rows("Views", rows_of(data), _VIEW_COLUMNS, empty="No saved views.")


@board.command("snapshot")
@click.argument("board_uuid", metavar="BOARD")
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
# Boards have no description field (BoardWrite declares none), so the flag the CLI
# once offered could only earn a 400. It stays, hidden, to refuse with the reason.
@click.option("-d", "--description", default=None, hidden=True)
@click.option(
    "--project",
    "project_uuid",
    required=True,
    help="The project the board belongs to (uuid).",
)
@click.option(
    "--key",
    "board_key",
    required=True,
    help="The board's key prefix, e.g. DSN, so its tasks read DSN-1, DSN-2…",
)
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_create(
    name: str,
    description: str | None,
    project_uuid: str,
    board_key: str,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Create a board in a project. Needs a signed-in organization admin.

    \b
    An organization API key cannot do this: the `tasks:admin` scope it requires can
    never be held by a key. Run `dailybot login` first.

    \b
    Examples:
      dailybot board create --name "Design" --project <project-uuid> --key DSN
    """
    if description is not None:
        raise click.UsageError(
            "Boards have no description. Put the context in a project "
            "(`dailybot project create -d ...`) and create the board under it."
        )
    _require_person_for_admin("board create", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Creating the board..."):
            data: dict[str, Any] = client.create_board(
                name=name, project=project_uuid, key=board_key, idempotency_key=idempotency_key
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Created board {named(data, name)}")


@board.command("update")
@click.argument("board_uuid", metavar="BOARD")
@click.option("-n", "--name", default=None, help="New board name.")
@click.option(
    "--key",
    "board_key",
    default=None,
    help="New key prefix. The old key is retired and stays reserved, so old links still resolve.",
)
@click.option(
    "--visibility",
    type=click.Choice(BOARD_VISIBILITIES),
    default=None,
    help="`members` makes it private; you are seated as its first member.",
)
@click.option("--estimate-scale", type=click.Choice(BOARD_ESTIMATE_SCALES), default=None)
@click.option(
    "--archive-after-days",
    type=click.IntRange(min=1),
    default=None,
    help="Auto-archive done tasks after this many days.",
)
@click.option("--project", default=None, help="Move the board under this project (uuid).")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def board_update(
    board_uuid: str,
    name: str | None,
    board_key: str | None,
    visibility: str | None,
    estimate_scale: str | None,
    archive_after_days: int | None,
    project: str | None,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Change a board's name, key, visibility or settings.

    \b
    Only the fields you pass are sent. Renaming the key retires the old one, which
    stays reserved forever, so `ENG-142` typed two years later still resolves.

    \b
    Examples:
      dailybot board update <board-uuid> --name "Design (Q4)"
      dailybot board update <board-uuid> --key DSN --visibility members --json
    """
    _require_person_for_admin("board update", json_mode=json_mode)
    fields: dict[str, Any] = {
        k: v
        for k, v in {
            "name": name,
            "key": board_key,
            "visibility": visibility,
            "estimate_scale": estimate_scale,
            "archive_after_days": archive_after_days,
            "project": project,
        }.items()
        if v is not None
    }
    if not fields:
        raise click.UsageError(
            "Nothing to update. Pass at least one of --name, --key, --visibility, "
            "--estimate-scale, --archive-after-days or --project."
        )
    client = require_auth()
    try:
        with console.status("Updating the board..."):
            data: dict[str, Any] = client.update_board(
                board_uuid, idempotency_key=idempotency_key, **fields
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Updated board {named(data, name or board_uuid)}")


@board.command("archive")
@click.argument("board_uuid", metavar="BOARD")
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
    _require_person_for_admin("board archive", json_mode=json_mode)
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
@click.argument("board_uuid", metavar="BOARD")
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
    _require_person_for_admin("board restore", json_mode=json_mode)
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
