"""Board commands (``/v1/tasks/boards/*``).

The snapshot is the intentionally dense door: one request gives an agent cold
context, and it is where every ``full_resync_required`` sends you back to. It
also carries ``delta_cursor`` — the only place a caller can obtain one, because
the delta door's own refusal for a missing cursor does not say where to get it.
That handoff is named in both commands' help on purpose.
"""

from typing import Any

import click
from rich.table import Table

from dailybot_cli.api_client import APIError, PaginatedResult
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_api_error,
    require_auth,
    resolve_error_message,
)
from dailybot_cli.commands.query_options import build_query_params, query_options
from dailybot_cli.display import (
    console,
    present_untrusted,
    print_board_snapshot,
    print_detail_panel,
    print_error,
    print_pagination_footer,
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
    table: Table = Table(title="Boards")
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("UUID", no_wrap=True)
    for row in result.results:
        table.add_row(
            str(row.get("key") or ""),
            present_untrusted(row.get("name")),
            str(row.get("uuid") or ""),
        )
    console.print(table)
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
        if exc.code == "not_found":
            print_error(resolve_error_message(exc))
            raise SystemExit(5) from exc
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_detail_panel("Board", data, _BOARD_FIELDS)


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
        if exc.code == "not_found":
            print_error(resolve_error_message(exc))
            raise SystemExit(5) from exc
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_board_snapshot(data)
