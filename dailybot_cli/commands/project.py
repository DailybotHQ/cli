"""Project commands (``/v1/tasks/projects/*``)."""

from typing import Any

import click
from rich.markup import escape

from dailybot_cli.api_client import APIError, PaginatedResult
from dailybot_cli.commands._beta import mark_beta
from dailybot_cli.commands._destructive import preview_then_confirm
from dailybot_cli.commands._rollups import render_rollup
from dailybot_cli.commands._writes import named, report_write
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_tasks_error,
    refuse_without_person,
    require_auth,
)
from dailybot_cli.commands.query_options import build_query_params, query_options, resolve_fetch_all
from dailybot_cli.config import get_token
from dailybot_cli.display import (
    console,
    present_untrusted,
    print_milestones_table,
    print_pagination_footer,
    print_projects_table,
    print_tasks_detail_panel,
)

# Split deliberately. `projects` is a goal-shaped selector: a project has no
# projects. Sharing one Choice let `project list --include projects` past Click and
# onto the wire, where it either 400s or is silently ignored — and a silently
# ignored selector is the failure mode this whole surface exists to avoid.
PROJECT_INCLUDE_VALUES: tuple[str, ...] = ("progress",)
GOAL_INCLUDE_VALUES: tuple[str, ...] = ("progress", "projects")

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


mark_beta(project)


@project.command("list")
@click.option(
    "--include",
    type=click.Choice(PROJECT_INCLUDE_VALUES, case_sensitive=False),
    multiple=True,
    help="Ask for a roll-up (nothing is included by default).",
)
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
    print_projects_table(result.results, rollup=render_rollup)
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))


@project.command("get")
@click.argument("project_uuid")
@click.option(
    "--include",
    type=click.Choice(PROJECT_INCLUDE_VALUES, case_sensitive=False),
    multiple=True,
    help="Ask for a roll-up.",
)
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
        # Isolation is 404-not-403: routed through the shared mapper so the exit
        # code and the --json payload match the documented table.
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_detail_panel("Project", data, _PROJECT_FIELDS)
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
    for update in result.results:
        console.print(
            f"[dim]{escape(str(update.get('created_at', '')))}[/dim] "
            f"{present_untrusted(update.get('body'), limit=160)}"
        )
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))


def _read_body(value: str) -> str:
    """Read a body argument, or stdin when it is `-`."""
    if value == "-":
        return click.get_text_stream("stdin").read().strip()
    return value


@project.command("update-post")
@click.argument("project_uuid")
@click.argument("body")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_update_post(project_uuid: str, body: str, json_mode: bool) -> None:
    """Post a project update — how the team sees what was done.

    \b
    This closes the loop between work and the people who care about it. An agent
    that moves tasks silently is invisible to the humans who own them.

    \b
    Pass `-` as the body to read it from stdin.

    \b
    Examples:
      dailybot project update-post <project-uuid> "Shipped the retry fix"
      echo "long update" | dailybot project update-post <project-uuid> -
    """
    client = require_auth()
    try:
        with console.status("Posting the update..."):
            # This door IGNORES Idempotency-Key, so none is sent and no flag is
            # offered — advertising one would promise a guarantee that does not exist.
            data: dict[str, Any] = client.post_project_update(project_uuid, body=_read_body(body))
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    # No web link: the web app's routes are not published, so one built here
    # would be a guess handed to a human.
    report_write(data, "Project update posted")


@project.command("milestones")
@click.argument("project_uuid", required=False)
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_milestones(project_uuid: str | None, json_mode: bool, **flags: Any) -> None:
    """List milestones, for one project or across the organization.

    \b
    Examples:
      dailybot project milestones <project-uuid>
      dailybot project milestones --json
    """
    client = require_auth()
    try:
        spec = build_query_params(**flags)
        with console.status("Reading milestones..."):
            result: PaginatedResult = client.list_milestones(
                project_uuid,
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
    print_milestones_table(result.results, rollup=render_rollup)
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))


@project.command("milestone-complete")
@click.argument("project_uuid")
@click.argument("milestone_uuid")
@click.option("--dry-run", is_flag=True, help="Show the consequence and exit without acting.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the prompt (still previews).")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_milestone_complete(
    project_uuid: str, milestone_uuid: str, dry_run: bool, assume_yes: bool, json_mode: bool
) -> None:
    """Mark a milestone complete.

    \b
    Completing a milestone does NOT close its open tasks. They stay open and keep
    their state — this is the thing most people assume the other way round.

    \b
    Examples:
      dailybot project milestone-complete <project-uuid> <milestone-uuid> --dry-run
      dailybot project milestone-complete <project-uuid> <milestone-uuid> --yes
    """
    client = require_auth()
    # The shared helper, not a private copy: this flow drifted from `task archive`
    # once already (it kept printing the Rich panel to stdout under `--json`), and a
    # second copy is a second place for that to happen.
    if not preview_then_confirm(
        lambda: client.complete_milestone(project_uuid, milestone_uuid, dry_run=True),
        assume_yes=assume_yes,
        preview_only=dry_run,
        json_mode=json_mode,
    ):
        return

    try:
        with console.status("Completing the milestone..."):
            data: dict[str, Any] = client.complete_milestone(
                project_uuid, milestone_uuid, dry_run=False
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Milestone completed. Its open tasks stay open and keep their state.")


@project.command("milestone-reopen")
@click.argument("project_uuid")
@click.argument("milestone_uuid")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_milestone_reopen(project_uuid: str, milestone_uuid: str, json_mode: bool) -> None:
    """Reopen a completed milestone.

    \b
    Examples:
      dailybot project milestone-reopen <project-uuid> <milestone-uuid>
    """
    client = require_auth()
    try:
        with console.status("Reopening the milestone..."):
            data: dict[str, Any] = client.reopen_milestone(project_uuid, milestone_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Milestone reopened")


def _require_person_for_admin(action: str, *, json_mode: bool) -> None:
    """Refuse a key on a `tasks:admin` door — see board.py for the full reasoning."""
    # See tasks.py `_require_person`: gate on the absence of a person token.
    if get_token() is None:
        refuse_without_person(
            f"`{action}` needs the `tasks:admin` scope, which an organization API key can "
            "never hold — it cannot even be stored on one. Run `dailybot login` and retry "
            "as a signed-in person.",
            json_mode=json_mode,
            admin=True,
        )


@project.command("create")
@click.option("-n", "--name", required=True, help="Project name.")
@click.option("-d", "--description", default=None, help="Project description.")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_create(
    name: str, description: str | None, idempotency_key: str | None, json_mode: bool
) -> None:
    """Create a project. Needs a signed-in person.

    \b
    Examples:
      dailybot project create --name "Apollo"
    """
    _require_person_for_admin("project create", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Creating the project..."):
            data: dict[str, Any] = client.create_project(
                name=name, description=description, idempotency_key=idempotency_key
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Created project {named(data, name)}")


@project.command("archive")
@click.argument("project_uuid")
@click.option("--dry-run", is_flag=True, help="Show the consequence and exit without acting.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the prompt (still previews).")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_archive(
    project_uuid: str, dry_run: bool, assume_yes: bool, idempotency_key: str | None, json_mode: bool
) -> None:
    """Archive a project.

    \b
    Examples:
      dailybot project archive <project-uuid> --dry-run
    """
    client = require_auth()
    if not preview_then_confirm(
        lambda: client.archive_project(project_uuid, dry_run=True),
        assume_yes=assume_yes,
        preview_only=dry_run,
        json_mode=json_mode,
    ):
        return
    try:
        with console.status("Archiving the project..."):
            data: dict[str, Any] = client.archive_project(
                project_uuid, dry_run=False, idempotency_key=idempotency_key
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Project archived")
