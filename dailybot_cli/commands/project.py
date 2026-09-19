"""Project commands (``/v1/tasks/projects/*``)."""

from typing import Any

import click
from rich.table import Table

from dailybot_cli.api_client import APIError, PaginatedResult
from dailybot_cli.commands._destructive import preview_then_confirm
from dailybot_cli.commands._rollups import render_rollup
from dailybot_cli.commands.public_api_helpers import (
    EXIT_NOT_AUTHENTICATED,
    EXIT_USER_ABORTED,
    emit_json,
    exit_for_api_error,
    require_auth,
    resolve_error_message,
)
from dailybot_cli.commands.query_options import build_query_params, query_options
from dailybot_cli.config import get_agent_auth
from dailybot_cli.display import (
    console,
    present_untrusted,
    print_detail_panel,
    print_dry_run_consequence,
    print_error,
    print_pagination_footer,
    print_success,
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
@click.option(
    "--include",
    type=click.Choice(INCLUDE_VALUES, case_sensitive=False),
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
@click.option(
    "--include",
    type=click.Choice(INCLUDE_VALUES, case_sensitive=False),
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
    for update in result.results:
        console.print(
            f"[dim]{update.get('created_at', '')}[/dim] "
            f"{present_untrusted(update.get('body'), limit=160)}"
        )
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))


def _read_body(value: str) -> str:
    """Read a body argument, or stdin when it is `-`."""
    if value == "-":
        return click.get_text_stream("stdin").read().strip()
    return value


def _report_write(result: dict[str, Any], message: str) -> None:
    """Report a write, distinguishing a fresh one from a server-side replay."""
    if result.get("_idempotency_replayed"):
        print_success(f"{message} — already applied (the server replayed a previous call).")
        return
    print_success(message)


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
        print_error(resolve_error_message(exc))
        raise SystemExit(4 if exc.status_code in (401, 403) else 1) from exc
    if json_mode:
        emit_json(data)
        return
    # No web link: the web app's routes are not published, so one built here
    # would be a guess handed to a human.
    _report_write(data, "Project update posted")


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
    table: Table = Table(title="Milestones")
    table.add_column("Name")
    table.add_column("Status", no_wrap=True)
    table.add_column("Open", no_wrap=True)
    table.add_column("UUID", no_wrap=True)
    for row in result.results:
        table.add_row(
            present_untrusted(row.get("name")),
            present_untrusted(row.get("status"), limit=16),
            render_rollup(row, "open_task_count"),
            str(row.get("uuid") or ""),
        )
    console.print(table)
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
    try:
        with console.status("Previewing the consequence..."):
            preview: dict[str, Any] = client.complete_milestone(
                project_uuid, milestone_uuid, dry_run=True
            )
    except APIError as exc:
        print_error(
            f"Could not preview the consequence, so nothing was changed. "
            f"{resolve_error_message(exc)}"
        )
        raise SystemExit(1) from exc

    print_dry_run_consequence(preview)
    if dry_run:
        return
    if not assume_yes and not click.confirm("Proceed?", default=False):
        print_error("Aborted. Nothing was changed.")
        raise SystemExit(EXIT_USER_ABORTED)

    try:
        with console.status("Completing the milestone..."):
            data: dict[str, Any] = client.complete_milestone(
                project_uuid, milestone_uuid, dry_run=False
            )
    except APIError as exc:
        print_error(resolve_error_message(exc))
        raise SystemExit(4 if exc.status_code in (401, 403) else 1) from exc
    if json_mode:
        emit_json(data)
        return
    _report_write(data, "Milestone completed. Its open tasks stay open and keep their state.")


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
        print_error(resolve_error_message(exc))
        raise SystemExit(4 if exc.status_code in (401, 403) else 1) from exc
    if json_mode:
        emit_json(data)
        return
    _report_write(data, "Milestone reopened")


def _require_person_for_admin(action: str) -> None:
    """Refuse a key on a `tasks:admin` door — see board.py for the full reasoning."""
    if get_agent_auth() == "api_key":
        print_error(
            f"`{action}` needs the `tasks:admin` scope, which an organization API key can "
            "never hold — it cannot even be stored on one. Run `dailybot login` and retry "
            "as a signed-in person."
        )
        raise SystemExit(EXIT_NOT_AUTHENTICATED)


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
    _require_person_for_admin("project create")
    client = require_auth()
    try:
        with console.status("Creating the project..."):
            data: dict[str, Any] = client.create_project(
                name=name, description=description, idempotency_key=idempotency_key
            )
    except APIError as exc:
        print_error(resolve_error_message(exc))
        raise SystemExit(4 if exc.status_code in (401, 402, 403) else 1) from exc
    if json_mode:
        emit_json(data)
        return
    _report_write(data, f"Created project {present_untrusted(data.get('name') or name)}")


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
    ):
        return
    try:
        with console.status("Archiving the project..."):
            data: dict[str, Any] = client.archive_project(
                project_uuid, dry_run=False, idempotency_key=idempotency_key
            )
    except APIError as exc:
        print_error(resolve_error_message(exc))
        raise SystemExit(4 if exc.status_code in (401, 403) else 1) from exc
    if json_mode:
        emit_json(data)
        return
    _report_write(data, "Project archived")
