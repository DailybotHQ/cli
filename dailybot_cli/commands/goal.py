"""Goal commands (``/v1/tasks/goals/*``)."""

from datetime import datetime
from typing import Any

import click

from dailybot_cli.api_client import APIError, PaginatedResult
from dailybot_cli.commands._beta import mark_beta
from dailybot_cli.commands._destructive import confirm_without_preview, preview_then_confirm
from dailybot_cli.commands._rollups import render_rollup
from dailybot_cli.commands._writes import named, report_write
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
    print_goals_table,
    print_pagination_footer,
    print_projects_table,
    print_success,
    print_tasks_detail_panel,
)

_GOAL_FIELDS: list[tuple[str, str]] = [
    ("Name", "name"),
    ("UUID", "uuid"),
    ("Archived", "is_archived"),
]


@click.group()
def goal() -> None:
    """Read and manage Dailybot Tasks goals.

    \b
    Roll-ups are opt-in. An absent field, a null field and a zero are three
    different answers and are rendered as three different things.

    \b
    Examples:
      dailybot goal list --include progress --include projects
    """


mark_beta(goal)


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


# Goals are dated commitments: the contract requires both ends of the period.
GOAL_DATE_FORMAT: str = "%Y-%m-%d"


@goal.command("create")
@click.option("-n", "--name", required=True, help="Goal name.")
@click.option(
    "--period-start",
    type=click.DateTime(formats=[GOAL_DATE_FORMAT]),
    required=True,
    help="First day of the goal's period (YYYY-MM-DD).",
)
@click.option(
    "--period-end",
    type=click.DateTime(formats=[GOAL_DATE_FORMAT]),
    required=True,
    help="Last day of the goal's period (YYYY-MM-DD).",
)
@click.option("-d", "--description", default=None, help="Goal description.")
@click.option("--owner", default=None, help="Accountable person (user uuid).")
@click.option("--team", default=None, help="Team the goal belongs to (uuid).")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def goal_create(
    name: str,
    period_start: datetime,
    period_end: datetime,
    description: str | None,
    owner: str | None,
    team: str | None,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Create a goal. Needs a signed-in person.

    \b
    A goal is a dated commitment, so both ends of its period are required. It starts
    as `not_started`; declare its status later with `dailybot goal update --status`.

    \b
    Examples:
      dailybot goal create -n "Q4 reliability" --period-start 2026-10-01 --period-end 2026-12-31
    """
    if period_end < period_start:
        raise click.UsageError("--period-end is before --period-start.")
    _require_person_for_admin("goal create", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Creating the goal..."):
            data: dict[str, Any] = client.create_goal(
                name=name,
                period_start=period_start.strftime(GOAL_DATE_FORMAT),
                period_end=period_end.strftime(GOAL_DATE_FORMAT),
                description=description,
                owner=owner,
                team=team,
                idempotency_key=idempotency_key,
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Created goal {named(data, name)}")


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


# Declared by a person; deliberately separate from the derived progress.
GOAL_STATUSES: tuple[str, ...] = (
    "not_started",
    "on_track",
    "at_risk",
    "off_track",
    "achieved",
    "missed",
)
_GOAL_DATE: click.DateTime = click.DateTime(formats=[GOAL_DATE_FORMAT])


@goal.command("update")
@click.argument("goal_uuid", metavar="GOAL")
@click.option("-n", "--name", default=None, help="New goal name.")
@click.option("-d", "--description", default=None, help="New description.")
@click.option("--period-start", type=_GOAL_DATE, default=None, help="YYYY-MM-DD.")
@click.option("--period-end", type=_GOAL_DATE, default=None, help="YYYY-MM-DD.")
@click.option("--owner", default=None, help="Accountable person (user uuid).")
@click.option("--team", default=None, help="Team (uuid).")
@click.option(
    "--status",
    type=click.Choice(GOAL_STATUSES),
    default=None,
    help="Declare where the goal stands. Not derived from progress.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def goal_update(
    goal_uuid: str,
    name: str | None,
    description: str | None,
    period_start: datetime | None,
    period_end: datetime | None,
    owner: str | None,
    team: str | None,
    status: str | None,
    json_mode: bool,
) -> None:
    """Change a goal, or declare its status.

    \b
    A goal's status is a person's judgement, separate from its derived progress:
    80% of the cards done with the hard half untouched is `at_risk`.

    \b
    Examples:
      dailybot goal update <goal-uuid> --status at_risk
      dailybot goal update <goal-uuid> --period-end 2027-01-31 --owner <user-uuid> --json
    """
    if period_start and period_end and period_end < period_start:
        raise click.UsageError("--period-end is before --period-start.")
    fields: dict[str, Any] = {
        k: v
        for k, v in {
            "name": name,
            "description": description,
            "period_start": period_start.strftime(GOAL_DATE_FORMAT) if period_start else None,
            "period_end": period_end.strftime(GOAL_DATE_FORMAT) if period_end else None,
            "owner": owner,
            "team": team,
            "status": status,
        }.items()
        if v is not None
    }
    if not fields:
        raise click.UsageError("Nothing to update. Pass at least one field, e.g. --status.")
    client = require_auth()
    try:
        with console.status("Updating the goal..."):
            data: dict[str, Any] = client.update_goal(goal_uuid, **fields)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Updated goal {named(data, name or goal_uuid)}")


@goal.command("restore")
@click.argument("goal_uuid", metavar="GOAL")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def goal_restore(goal_uuid: str, json_mode: bool) -> None:
    """Bring an archived goal back. A live goal is a no-op.

    \b
    If another live goal took its name meanwhile, the server refuses
    (`goal_name_conflict`): rename one of them first.

    \b
    Examples:
      dailybot goal restore <goal-uuid>
    """
    client = require_auth()
    try:
        with console.status("Restoring the goal..."):
            data: dict[str, Any] = client.restore_goal(goal_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Goal restored")


@goal.command("link")
@click.argument("goal_uuid", metavar="GOAL")
@click.argument("project_uuid", metavar="PROJECT")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def goal_link(goal_uuid: str, project_uuid: str, json_mode: bool) -> None:
    """Make a project count toward a goal.

    \b
    Progress rolls up only along task → board → project → goal, so this link is
    what makes a project's work show in the goal's progress.

    \b
    Examples:
      dailybot goal link <goal-uuid> <project-uuid>
    """
    client = require_auth()
    try:
        with console.status("Linking the project..."):
            data: dict[str, Any] = client.link_goal_project(goal_uuid, project_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Project linked to the goal")


@goal.command("unlink")
@click.argument("goal_uuid", metavar="GOAL")
@click.argument("project_uuid", metavar="PROJECT")
@click.option("--dry-run", is_flag=True, help="Say what would happen and send nothing.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the confirmation.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def goal_unlink(
    goal_uuid: str, project_uuid: str, dry_run: bool, assume_yes: bool, json_mode: bool
) -> None:
    """Stop a project counting toward a goal. The project itself is untouched.

    \b
    Examples:
      dailybot goal unlink <goal-uuid> <project-uuid> --dry-run
      dailybot goal unlink <goal-uuid> <project-uuid> --yes
    """
    if not confirm_without_preview(
        f"unlink project {project_uuid} from goal {goal_uuid}; its work stops counting toward "
        "the goal.",
        assume_yes=assume_yes,
        dry_run=dry_run,
        json_mode=json_mode,
    ):
        return
    client = require_auth()
    try:
        with console.status("Unlinking the project..."):
            client.unlink_goal_project(goal_uuid, project_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json({"unlinked": True, "goal": goal_uuid, "project": project_uuid})
        return
    print_success("Project unlinked from the goal.")
