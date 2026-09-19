"""Project commands (``/v1/tasks/projects/*``)."""

from typing import Any

import click
from rich.table import Table

from dailybot_cli.api_client import APIError, PaginatedResult
from dailybot_cli.commands._rollups import render_rollup
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

INCLUDE_VALUES: tuple[str, ...] = ("progress", "projects")

_PROJECT_FIELDS: list[tuple[str, str]] = [
    ("Name", "name"),
    ("UUID", "uuid"),
    ("Status", "status"),
    ("Archived", "is_archived"),
]


def _envelope(result: PaginatedResult) -> dict[str, Any]:
    return {
        "count": result.count,
        "next": result.next,
        "previous": result.previous,
        "results": result.results,
    }


def _include_list(include: tuple[str, ...]) -> list[str] | None:
    return sorted({value.lower() for value in include}) if include else None


@click.group()
def project() -> None:
    """Read Dailybot Tasks projects.

    \b
    Roll-ups are opt-in: a field you did not ask for is absent, which is a
    different answer from null and from zero.

    \b
    Examples:
      dailybot project list --include progress
      dailybot project updates
    """


@project.command("list")
@click.option("--include", type=click.Choice(INCLUDE_VALUES, case_sensitive=False),
              multiple=True, help="Ask for a roll-up (nothing is included by default).")
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_list(include: tuple[str, ...], json_mode: bool, **flags: Any) -> None:
    """List projects.

    \b
    Examples:
      dailybot project list
      dailybot project list --include progress --json
    """
    client = require_auth()
    try:
        spec = build_query_params(**flags)
        with console.status("Reading projects..."):
            result: PaginatedResult = client.list_projects(
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
    table: Table = Table(title="Projects")
    table.add_column("Name")
    table.add_column("Progress", no_wrap=True)
    table.add_column("UUID", no_wrap=True)
    for row in result.results:
        table.add_row(
            present_untrusted(row.get("name")),
            render_rollup(row, "progress"),
            str(row.get("uuid") or ""),
        )
    console.print(table)
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))


@project.command("get")
@click.argument("project_uuid")
@click.option("--include", type=click.Choice(INCLUDE_VALUES, case_sensitive=False), multiple=True,
              help="Ask for a roll-up.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_get(project_uuid: str, include: tuple[str, ...], json_mode: bool) -> None:
    """Show one project.

    \b
    Examples:
      dailybot project get <project-uuid> --include progress
    """
    client = require_auth()
    try:
        with console.status("Reading the project..."):
            data: dict[str, Any] = client.get_project(project_uuid, include=_include_list(include))
    except APIError as exc:
        if exc.code == "not_found":
            print_error(resolve_error_message(exc))
            raise SystemExit(5) from exc
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_detail_panel("Project", data, _PROJECT_FIELDS)
    console.print(f"[bold]Progress[/bold]  {render_rollup(data, 'progress')}")


@project.command("updates")
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_updates(json_mode: bool, **flags: Any) -> None:
    """Read the batched project-update digest.

    \b
    This door exists to replace one request per project. An agent catching up
    should use it rather than looping over `project get`.

    \b
    Examples:
      dailybot project updates --last-week
    """
    client = require_auth()
    try:
        spec = build_query_params(**flags)
        with console.status("Reading project updates..."):
            result: PaginatedResult = client.list_project_updates(
                params=spec.params or None, page=spec.page, page_size=spec.page_size,
                fetch_all=spec.fetch_all, limit=spec.limit,
            )
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(_envelope(result))
        return
    for update in result.results:
        console.print(
            f"[dim]{update.get('created_at', '')}[/dim] "
            f"{present_untrusted(update.get('body'), limit=160)}"
        )
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))
