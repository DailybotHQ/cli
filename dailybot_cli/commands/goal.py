"""Goal commands (``/v1/tasks/goals/*``)."""

from typing import Any

import click
from rich.table import Table

from dailybot_cli.api_client import APIError, PaginatedResult
from dailybot_cli.commands._rollups import render_rollup
from dailybot_cli.commands.project import INCLUDE_VALUES, _envelope, _include_list
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
    print_detail_panel,
    print_error,
    print_pagination_footer,
)

_GOAL_FIELDS: list[tuple[str, str]] = [
    ("Name", "name"),
    ("UUID", "uuid"),
    ("Archived", "is_archived"),
]


@click.group()
def goal() -> None:
    """Read Dailybot Tasks goals.

    \b
    Roll-ups are opt-in. An absent field, a null field and a zero are three
    different answers and are rendered as three different things.

    \b
    Examples:
      dailybot goal list --include progress,projects
    """


@goal.command("list")
@click.option("--include", type=click.Choice(INCLUDE_VALUES, case_sensitive=False), multiple=True,
              help="Ask for a roll-up (nothing is included by default).")
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def goal_list(include: tuple[str, ...], json_mode: bool, **flags: Any) -> None:
    """List goals.

    \b
    Examples:
      dailybot goal list
      dailybot goal list --include progress --json
    """
    client = require_auth()
    try:
        spec = build_query_params(**flags)
        with console.status("Reading goals..."):
            result: PaginatedResult = client.list_goals(
                include=_include_list(include), page=spec.page, page_size=spec.page_size,
                fetch_all=spec.fetch_all, limit=spec.limit,
            )
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(_envelope(result))
        return
    table: Table = Table(title="Goals")
    table.add_column("Name")
    table.add_column("Progress", no_wrap=True)
    table.add_column("Projects", no_wrap=True)
    table.add_column("UUID", no_wrap=True)
    for row in result.results:
        table.add_row(
            present_untrusted(row.get("name")),
            render_rollup(row, "progress"),
            render_rollup(row, "project_count"),
            str(row.get("uuid") or ""),
        )
    console.print(table)
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))


@goal.command("get")
@click.argument("goal_uuid")
@click.option("--include", type=click.Choice(INCLUDE_VALUES, case_sensitive=False), multiple=True,
              help="Ask for a roll-up.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def goal_get(goal_uuid: str, include: tuple[str, ...], json_mode: bool) -> None:
    """Show one goal.

    \b
    Examples:
      dailybot goal get <goal-uuid> --include progress
    """
    client = require_auth()
    try:
        with console.status("Reading the goal..."):
            data: dict[str, Any] = client.get_goal(goal_uuid, include=_include_list(include))
    except APIError as exc:
        if exc.code == "not_found":
            print_error(resolve_error_message(exc))
            raise SystemExit(5) from exc
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_detail_panel("Goal", data, _GOAL_FIELDS)
    console.print(f"[bold]Progress[/bold]  {render_rollup(data, 'progress')}")
