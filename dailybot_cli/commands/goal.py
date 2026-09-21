"""Goal commands (``/v1/tasks/goals/*``)."""

from typing import Any

import click

from dailybot_cli.api_client import APIError, PaginatedResult
from dailybot_cli.commands._destructive import preview_then_confirm
from dailybot_cli.commands._rollups import render_rollup
from dailybot_cli.commands._writes import report_write
from dailybot_cli.commands.project import (
    GOAL_INCLUDE_VALUES,
    _envelope,
    _include_list,
    _require_person_for_admin,
)
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_tasks_error,
    require_auth,
)
from dailybot_cli.commands.query_options import build_query_params, query_options, resolve_fetch_all
from dailybot_cli.display import (
    console,
    present_untrusted,
    print_goals_table,
    print_pagination_footer,
    print_projects_table,
    print_tasks_detail_panel,
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
      dailybot goal list --include progress --include projects
    """


@goal.command("list")
@click.option(
    "--include",
    type=click.Choice(GOAL_INCLUDE_VALUES, case_sensitive=False),
    multiple=True,
    help="Ask for a roll-up (nothing is included by default).",
)
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
                include=_include_list(include),
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
    print_goals_table(result.results, rollup=render_rollup)
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))


@goal.command("get")
@click.argument("goal_uuid")
@click.option(
    "--include",
    type=click.Choice(GOAL_INCLUDE_VALUES, case_sensitive=False),
    multiple=True,
    help="Ask for a roll-up.",
)
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
        # Isolation is 404-not-403: routed through the shared mapper so the exit
        # code and the --json payload match the documented table.
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_detail_panel("Goal", data, _GOAL_FIELDS)
    console.print(f"[bold]Progress[/bold]  {render_rollup(data, 'progress')}")
    # `--include projects` was accepted, sent, and then rendered nowhere on the human
    # path — so a caller had no signal the selector had worked. Absent stays absent:
    # `render_rollup` distinguishes "not requested" from null from a value.
    if "projects" in data or "project_count" in data:
        console.print(f"[bold]Projects[/bold]  {render_rollup(data, 'project_count')}")
        projects: Any = data.get("projects")
        if isinstance(projects, list) and projects:
            print_projects_table(projects, rollup=render_rollup)


@goal.command("create")
@click.option("-n", "--name", required=True, help="Goal name.")
@click.option("-d", "--description", default=None, help="Goal description.")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def goal_create(
    name: str, description: str | None, idempotency_key: str | None, json_mode: bool
) -> None:
    """Create a goal. Needs a signed-in person.

    \b
    Examples:
      dailybot goal create --name "Q4 reliability"
    """
    _require_person_for_admin("goal create", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Creating the goal..."):
            data: dict[str, Any] = client.create_goal(
                name=name, description=description, idempotency_key=idempotency_key
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Created goal {present_untrusted(data.get('name') or name)}")


@goal.command("archive")
@click.argument("goal_uuid")
@click.option("--dry-run", is_flag=True, help="Show the consequence and exit without acting.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the prompt (still previews).")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def goal_archive(
    goal_uuid: str, dry_run: bool, assume_yes: bool, idempotency_key: str | None, json_mode: bool
) -> None:
    """Archive a goal. Its projects are NOT archived with it.

    \b
    Examples:
      dailybot goal archive <goal-uuid> --dry-run
    """
    client = require_auth()
    if not preview_then_confirm(
        lambda: client.archive_goal(goal_uuid, dry_run=True),
        assume_yes=assume_yes,
        preview_only=dry_run,
        json_mode=json_mode,
    ):
        return
    try:
        with console.status("Archiving the goal..."):
            data: dict[str, Any] = client.archive_goal(
                goal_uuid, dry_run=False, idempotency_key=idempotency_key
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Goal archived. Its projects were not archived.")
