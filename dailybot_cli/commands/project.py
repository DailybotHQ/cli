"""Project commands (``/v1/tasks/projects/*``)."""

import json as _json
from datetime import datetime
from typing import Any

import click
from rich.markup import escape

from dailybot_cli.api_client import APIError, PaginatedResult
from dailybot_cli.commands._beta import mark_beta
from dailybot_cli.commands._destructive import confirm_without_preview, preview_then_confirm
from dailybot_cli.commands._rollups import render_rollup
from dailybot_cli.commands._writes import named, report_write
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_tasks_error,
    refuse_without_person,
    require_auth,
    rows_of,
)
from dailybot_cli.commands.query_options import build_query_params, query_options, resolve_fetch_all
from dailybot_cli.config import get_token
from dailybot_cli.display import (
    console,
    present_untrusted,
    print_info,
    print_milestones_table,
    print_pagination_footer,
    print_projects_table,
    print_raw_value,
    print_success,
    print_tasks_detail_panel,
    print_tasks_rows,
)

# Split deliberately. `projects` is a goal-shaped selector: a project has no
# projects. Sharing one Choice let `project list --include projects` past Click and
# onto the wire, where it either 400s or is silently ignored — and a silently
# ignored selector is the failure mode this whole surface exists to avoid.
PROJECT_INCLUDE_VALUES: tuple[str, ...] = ("progress",)
PROJECT_HEALTH: tuple[str, ...] = ("not_set", "on_track", "at_risk", "off_track")
PROJECT_VISIBILITIES: tuple[str, ...] = ("org", "members")
PROJECT_DATE_FORMAT: str = "%Y-%m-%d"
_PROJECT_DATE: click.DateTime = click.DateTime(formats=[PROJECT_DATE_FORMAT])
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
    """Read and manage Dailybot Tasks projects.

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
@click.argument("project_uuid", metavar="PROJECT")
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
@click.argument("project_uuid", metavar="PROJECT", required=False)
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_updates(project_uuid: str | None, json_mode: bool, **flags: Any) -> None:
    """Read project updates: the batched digest, or one project's updates.

    \b
    Without PROJECT this is the digest across projects — use it instead of looping
    over `project get`. With PROJECT it is that project's own feed.

    \b
    Examples:
      dailybot project updates --last-week
      dailybot project updates <project-uuid> --json
    """
    client = require_auth()
    try:
        spec = build_query_params(**flags)
        with console.status("Reading project updates..."):
            result: PaginatedResult = client.list_project_updates(
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
@click.argument("project_uuid", metavar="PROJECT")
@click.argument("body")
@click.option(
    "--health",
    type=click.Choice(PROJECT_HEALTH),
    default=None,
    help="What you claim about the project today. Does not change the project's own health.",
)
@click.option(
    "--idempotency-key",
    default=None,
    help="Reuse a key to make a retry safe. Generated automatically when omitted.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_update_post(
    project_uuid: str,
    body: str,
    health: str | None,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Post a project update — how the team sees what was done.

    \b
    This closes the loop between work and the people who care about it. An agent
    that moves tasks silently is invisible to the humans who own them.

    \b
    Pass `-` as the body to read it from stdin.

    \b
    Examples:
      dailybot project update-post <project-uuid> "Shipped the retry fix"
      echo "long update" | dailybot project update-post <project-uuid> - --health on_track
    """
    client = require_auth()
    try:
        with console.status("Posting the update..."):
            # The door honours Idempotency-Key (API R4): a retry with the printed key
            # replays the original post instead of posting it twice.
            data: dict[str, Any] = client.post_project_update(
                project_uuid,
                body=_read_body(body),
                health=health,
                idempotency_key=idempotency_key,
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    # No web link: the web app's routes are not published, so one built here
    # would be a guess handed to a human.
    report_write(data, "Project update posted")


@project.command("milestones")
@click.argument("project_uuid", metavar="PROJECT", required=False)
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
@click.argument("project_uuid", metavar="PROJECT")
@click.argument("milestone_uuid", metavar="MILESTONE")
@click.option("--dry-run", is_flag=True, help="Show the consequence and exit without acting.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the prompt (still previews).")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_milestone_complete(
    project_uuid: str,
    milestone_uuid: str,
    dry_run: bool,
    assume_yes: bool,
    idempotency_key: str | None,
    json_mode: bool,
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
                project_uuid, milestone_uuid, dry_run=False, idempotency_key=idempotency_key
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Milestone completed. Its open tasks stay open and keep their state.")


@project.command("milestone-reopen")
@click.argument("project_uuid", metavar="PROJECT")
@click.argument("milestone_uuid", metavar="MILESTONE")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_milestone_reopen(
    project_uuid: str, milestone_uuid: str, idempotency_key: str | None, json_mode: bool
) -> None:
    """Reopen a completed milestone.

    \b
    Examples:
      dailybot project milestone-reopen <project-uuid> <milestone-uuid>
    """
    client = require_auth()
    try:
        with console.status("Reopening the milestone..."):
            data: dict[str, Any] = client.reopen_milestone(
                project_uuid, milestone_uuid, idempotency_key=idempotency_key
            )
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


def _project_fields(
    visibility: str | None,
    lead: str | None,
    health: str | None,
    start_date: datetime | None,
    target_date: datetime | None,
) -> dict[str, Any]:
    """The optional ProjectWrite fields, dates in the contract's YYYY-MM-DD form."""
    fields: dict[str, Any] = {
        "visibility": visibility,
        "lead": lead,
        "health": health,
        "start_date": start_date.strftime(PROJECT_DATE_FORMAT) if start_date else None,
        "target_date": target_date.strftime(PROJECT_DATE_FORMAT) if target_date else None,
    }
    if start_date and target_date and target_date < start_date:
        raise click.UsageError("--target-date is before --start-date.")
    return {k: v for k, v in fields.items() if v is not None}


def _project_field_options(func: Any) -> Any:
    """The ProjectWrite options shared by `project create` and `project update`."""
    for option in reversed(
        [
            click.option(
                "--visibility",
                type=click.Choice(PROJECT_VISIBILITIES),
                default=None,
                help="`members` makes it private: you plus whoever you invite. It only narrows.",
            ),
            click.option("--lead", default=None, help="Lead (user uuid)."),
            click.option(
                "--health",
                type=click.Choice(PROJECT_HEALTH),
                default=None,
                help="Declared health — separate from the derived progress.",
            ),
            click.option("--start-date", type=_PROJECT_DATE, default=None, help="YYYY-MM-DD."),
            click.option("--target-date", type=_PROJECT_DATE, default=None, help="YYYY-MM-DD."),
        ]
    ):
        func = option(func)
    return func


@project.command("create")
@click.option("-n", "--name", required=True, help="Project name.")
@click.option("-d", "--description", default=None, help="Project description.")
@_project_field_options
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_create(
    name: str,
    description: str | None,
    visibility: str | None,
    lead: str | None,
    health: str | None,
    start_date: datetime | None,
    target_date: datetime | None,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Create a project. Needs a signed-in person.

    \b
    Examples:
      dailybot project create --name "Apollo"
      dailybot project create -n "Apollo" --lead <user-uuid> --target-date 2026-12-15 --json
    """
    extra: dict[str, Any] = _project_fields(visibility, lead, health, start_date, target_date)
    _require_person_for_admin("project create", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Creating the project..."):
            data: dict[str, Any] = client.create_project(
                name=name, description=description, idempotency_key=idempotency_key, **extra
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Created project {named(data, name)}")


@project.command("archive")
@click.argument("project_uuid", metavar="PROJECT")
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


@project.command("update")
@click.argument("project_uuid", metavar="PROJECT")
@click.option("-n", "--name", default=None, help="New project name.")
@click.option("-d", "--description", default=None, help="New project description.")
@_project_field_options
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_update(
    project_uuid: str,
    name: str | None,
    description: str | None,
    visibility: str | None,
    lead: str | None,
    health: str | None,
    start_date: datetime | None,
    target_date: datetime | None,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Change a project's name, lead, health, dates or visibility.

    \b
    Only the fields you pass are sent. Needs the `tasks:admin` scope. To post a
    status note for the team, use `dailybot project update-post` instead.

    \b
    Examples:
      dailybot project update <project-uuid> --health at_risk
      dailybot project update <project-uuid> --target-date 2027-01-15 --lead <user-uuid> --json
    """
    fields: dict[str, Any] = _project_fields(visibility, lead, health, start_date, target_date)
    if name is not None:
        fields["name"] = name
    if description is not None:
        fields["description"] = description
    if not fields:
        raise click.UsageError("Nothing to update. Pass at least one field, e.g. --health.")
    client = require_auth()
    try:
        with console.status("Updating the project..."):
            data: dict[str, Any] = client.update_project(
                project_uuid, idempotency_key=idempotency_key, **fields
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Updated project {named(data, name or project_uuid)}")


@project.command("restore")
@click.argument("project_uuid", metavar="PROJECT")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_restore(project_uuid: str, idempotency_key: str | None, json_mode: bool) -> None:
    """Bring an archived project back. A live project is a no-op.

    \b
    Boards and tasks that were archived with it stay archived: restore them with
    `dailybot board restore`. Restoring uses one project slot on your plan.

    \b
    Examples:
      dailybot project restore <project-uuid>
    """
    client = require_auth()
    try:
        with console.status("Restoring the project..."):
            data: dict[str, Any] = client.restore_project(
                project_uuid, idempotency_key=idempotency_key
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Project restored")


# ---------------------------------------------------------------------------
# Members and saved views — person-only
# ---------------------------------------------------------------------------

_MEMBER_REASON: str = (
    "changes or reveals who can see a private project, and no organization API key may do "
    "that — there is no person behind it to be accountable."
)
_MEMBER_COLUMNS: list[tuple[str, str, bool]] = [
    ("Kind", "subject_type", True),
    ("Name", "name", False),
    ("Team", "team_name", False),
    ("User UUID", "user_uuid", True),
    ("Team UUID", "team_uuid", True),
]
_VIEW_COLUMNS: list[tuple[str, str, bool]] = [
    ("Name", "name", False),
    ("Mode", "view_mode", True),
    ("UUID", "uuid", True),
]


def _require_person(action: str, reason: str, *, json_mode: bool) -> None:
    """Refuse an API key on a person-only project door, before any request."""
    if get_token() is None:
        refuse_without_person(
            f"`{action}` {reason} Run `dailybot login` and retry as a signed-in person.",
            json_mode=json_mode,
        )


@project.command("members")
@click.argument("project_uuid", metavar="PROJECT")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_members(project_uuid: str, json_mode: bool) -> None:
    """List who can see a project — people and whole teams. Needs `dailybot login`.

    \b
    Examples:
      dailybot project members <project-uuid>
    """
    _require_person("project members", _MEMBER_REASON, json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Reading the members..."):
            data: Any = client.list_project_members(project_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_rows("Members", rows_of(data), _MEMBER_COLUMNS, empty="No explicit members.")


@project.group("member")
def project_member() -> None:
    """Invite or remove people and teams on a project. Needs `dailybot login`.

    \b
    There is no project role to edit: organization roles plus visibility are the
    access model.

    \b
    Examples:
      dailybot project member add <project-uuid> --user <user-uuid>
      dailybot project member add <project-uuid> --team <team-uuid>
    """


@project_member.command("add")
@click.argument("project_uuid", metavar="PROJECT")
@click.option("--user", "user_uuid", default=None, help="A person (user uuid).")
@click.option(
    "--team",
    "team_uuid",
    default=None,
    help="A whole team (uuid); membership follows the team live.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_member_add(
    project_uuid: str, user_uuid: str | None, team_uuid: str | None, json_mode: bool
) -> None:
    """Invite a person or a whole team into a project.

    \b
    Examples:
      dailybot project member add <project-uuid> --user <user-uuid>
      dailybot project member add <project-uuid> --team <team-uuid> --json
    """
    if (user_uuid is None) == (team_uuid is None):
        raise click.UsageError("Pass exactly one of --user or --team.")
    _require_person("project member add", _MEMBER_REASON, json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Adding the member..."):
            data: dict[str, Any] = client.add_project_member(
                project_uuid, user_uuid=user_uuid, team_uuid=team_uuid
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Member added")


@project_member.command("remove")
@click.argument("project_uuid", metavar="PROJECT")
@click.argument("user_uuid", metavar="USER")
@click.option("--dry-run", is_flag=True, help="Say what would happen and send nothing.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the confirmation.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_member_remove(
    project_uuid: str, user_uuid: str, dry_run: bool, assume_yes: bool, json_mode: bool
) -> None:
    """Remove someone from a project.

    \b
    Examples:
      dailybot project member remove <project-uuid> <user-uuid> --dry-run
      dailybot project member remove <project-uuid> <user-uuid> --yes
    """
    _require_person("project member remove", _MEMBER_REASON, json_mode=json_mode)
    if not confirm_without_preview(
        f"remove user {user_uuid} from project {project_uuid}; they lose sight of it if it "
        "is private.",
        assume_yes=assume_yes,
        dry_run=dry_run,
        json_mode=json_mode,
    ):
        return
    client = require_auth()
    try:
        with console.status("Removing the member..."):
            client.remove_project_member(project_uuid, user_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json({"removed": True, "project": project_uuid, "user": user_uuid})
        return
    print_success("Member removed.")


@project.command("views")
@click.argument("project_uuid", metavar="PROJECT")
@click.option(
    "--etag",
    "etag_only",
    is_flag=True,
    help="Print only the ETag `project view save --if-match` needs.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_views(project_uuid: str, etag_only: bool, json_mode: bool) -> None:
    """List your saved views on a project, with the ETag a save needs.

    \b
    Examples:
      dailybot project views <project-uuid>
      ETAG=$(dailybot project views <project-uuid> --etag)
    """
    client = require_auth()
    try:
        with console.status("Reading the views..."):
            data, etag = client.list_project_views_with_etag(project_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if etag_only:
        print_raw_value(etag or "")
        return
    if json_mode:
        emit_json(data)
        return
    print_tasks_rows("Views", rows_of(data), _VIEW_COLUMNS, empty="No saved views.")
    if etag:
        print_info(f"ETag: {etag} (pass it to `project view save --if-match`)")


@project.group("view")
def project_view() -> None:
    """Save your views of a project. Needs `dailybot login`.

    \b
    Examples:
      dailybot project view save <project-uuid> -f views.json --if-match '"3"'
    """


@project_view.command("save")
@click.argument("project_uuid", metavar="PROJECT")
@click.option(
    "-f",
    "--file",
    "views_file",
    type=click.File("r"),
    required=True,
    help="JSON array of views (`-` reads stdin). It REPLACES your whole list.",
)
@click.option("--if-match", default=None, help="The ETag `project views` showed.")
@click.option("--fetch-etag", is_flag=True, help="Read the current ETag first (narrower).")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_view_save(
    project_uuid: str,
    views_file: Any,
    if_match: str | None,
    fetch_etag: bool,
    json_mode: bool,
) -> None:
    """Replace your saved views on a project with the array in a file.

    \b
    Examples:
      dailybot project view save <project-uuid> -f views.json --if-match '"3"'
      dailybot project view save <project-uuid> -f views.json --fetch-etag --json
    """
    if (if_match is None) == (not fetch_etag):
        raise click.UsageError("Pass exactly one of --if-match <etag> or --fetch-etag.")
    try:
        views: Any = _json.load(views_file)
    except ValueError as exc:
        raise click.BadParameter(f"not valid JSON: {exc}", param_hint="--file") from exc
    if not isinstance(views, list):
        raise click.BadParameter("must be a JSON array of views.", param_hint="--file")
    _require_person(
        "project view save",
        "saves views that belong to a person, and an organization API key is not one.",
        json_mode=json_mode,
    )
    client = require_auth()
    try:
        etag: str | None = if_match
        if fetch_etag:
            with console.status("Reading the current views..."):
                _current, etag = client.list_project_views_with_etag(project_uuid)
            if etag is None:
                raise click.ClickException(
                    "The server returned no ETag for this project's views, so a save cannot be "
                    "made safely. Nothing was changed."
                )
        with console.status("Saving the views..."):
            data: Any = client.save_project_views(project_uuid, views, if_match=str(etag))
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_rows("Views", rows_of(data), _VIEW_COLUMNS, empty="No saved views.")


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------


@project.command("milestone-create")
@click.argument("project_uuid", metavar="PROJECT")
@click.option("-n", "--name", required=True, help="Milestone name.")
@click.option("--date", "date", type=_PROJECT_DATE, required=True, help="Due date (YYYY-MM-DD).")
@click.option("-d", "--description", default=None, help="What the milestone commits to.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_milestone_create(
    project_uuid: str, name: str, date: datetime, description: str | None, json_mode: bool
) -> None:
    """Commit a project to a dated milestone.

    \b
    This door takes no idempotency key: a retry after a timeout can create a second
    milestone. Check `dailybot project milestones <project>` before retrying.

    \b
    Examples:
      dailybot project milestone-create <project-uuid> -n "Beta" --date 2026-11-01
    """
    client = require_auth()
    try:
        with console.status("Creating the milestone..."):
            data: dict[str, Any] = client.create_milestone(
                project_uuid,
                name=name,
                date=date.strftime(PROJECT_DATE_FORMAT),
                description=description,
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Created milestone {named(data, name)}")


@project.command("milestone-update")
@click.argument("project_uuid", metavar="PROJECT")
@click.argument("milestone_uuid", metavar="MILESTONE")
@click.option("-n", "--name", default=None, help="New name.")
@click.option("--date", "date", type=_PROJECT_DATE, default=None, help="New date (YYYY-MM-DD).")
@click.option("-d", "--description", default=None, help="New description.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_milestone_update(
    project_uuid: str,
    milestone_uuid: str,
    name: str | None,
    date: datetime | None,
    description: str | None,
    json_mode: bool,
) -> None:
    """Rename a milestone or move its date.

    \b
    Examples:
      dailybot project milestone-update <project-uuid> <milestone-uuid> --date 2026-11-15
    """
    fields: dict[str, Any] = {
        "name": name,
        "date": date.strftime(PROJECT_DATE_FORMAT) if date else None,
        "description": description,
    }
    if all(v is None for v in fields.values()):
        raise click.UsageError("Nothing to update. Pass --name, --date or --description.")
    client = require_auth()
    try:
        with console.status("Updating the milestone..."):
            data: dict[str, Any] = client.update_milestone(project_uuid, milestone_uuid, **fields)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Milestone updated")


@project.command("milestone-delete")
@click.argument("project_uuid", metavar="PROJECT")
@click.argument("milestone_uuid", metavar="MILESTONE")
@click.option("--dry-run", is_flag=True, help="Say what would happen and send nothing.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the confirmation.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def project_milestone_delete(
    project_uuid: str, milestone_uuid: str, dry_run: bool, assume_yes: bool, json_mode: bool
) -> None:
    """Retire a milestone. Its tasks keep pointing at it; nothing is hard-deleted.

    \b
    Examples:
      dailybot project milestone-delete <project-uuid> <milestone-uuid> --dry-run
      dailybot project milestone-delete <project-uuid> <milestone-uuid> --yes
    """
    if not confirm_without_preview(
        f"retire milestone {milestone_uuid} on project {project_uuid}; its tasks keep pointing "
        "at it.",
        assume_yes=assume_yes,
        dry_run=dry_run,
        json_mode=json_mode,
    ):
        return
    client = require_auth()
    try:
        with console.status("Retiring the milestone..."):
            client.delete_milestone(project_uuid, milestone_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json({"retired": True, "project": project_uuid, "milestone": milestone_uuid})
        return
    print_success("Milestone retired.")
