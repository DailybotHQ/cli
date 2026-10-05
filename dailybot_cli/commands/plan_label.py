"""Organization Plan labels (``/v1/plan/labels/*``).

These are the Plan-surface taxonomy doors annotated as
``dailybot plan label list|create|update|delete``. Board-scoped create still
lives under ``board label create``; edit/delete there call the same Plan paths.
"""

from typing import Any

import click

from dailybot_cli.api_client import APIError, PaginatedResult
from dailybot_cli.commands._beta import mark_beta
from dailybot_cli.commands._destructive import confirm_without_preview
from dailybot_cli.commands._writes import named, report_write
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_tasks_error,
    require_auth,
    rows_of,
)
from dailybot_cli.commands.query_options import (
    PAGING_ONLY_MORE_HINT,
    build_query_params,
    paging_options,
    resolve_fetch_all,
)
from dailybot_cli.display import (
    console,
    print_pagination_footer,
    print_success,
    print_tasks_rows,
)


def _envelope(result: PaginatedResult) -> dict[str, Any]:
    return {
        "count": result.count,
        "next": result.next,
        "previous": result.previous,
        "results": result.results,
    }


_LABEL_COLUMNS: list[tuple[str, str, bool]] = [
    ("Name", "name", False),
    ("Color", "color", True),
    ("UUID", "uuid", True),
    ("Archived", "is_archived", True),
]


@click.group("label")
def label() -> None:
    """Organization labels on the Plan surface (``/v1/plan/labels/``).

    \b
    Needs a person: `dailybot login` or a personal API key. Create from a board
    with `board label create` when you are already on a board context; list and
    manage the org set here.

    \b
    Examples:
      dailybot plan label list
      dailybot plan label create -n bug --color "#ef4444"
      dailybot plan label update <label-uuid> --archive
      dailybot plan label delete <label-uuid> --yes
    """


mark_beta(label)


@label.command("list")
@click.option("-s", "--search", default=None, help="Case-insensitive substring match on the name.")
@click.option(
    "--include-archived",
    is_flag=True,
    help="Include archived labels (hidden from the default list).",
)
@paging_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def label_list(
    search: str | None,
    include_archived: bool,
    json_mode: bool,
    **flags: Any,
) -> None:
    """List organization labels under Plan.

    \b
    Examples:
      dailybot plan label list
      dailybot plan label list --search bug --include-archived --json
    """
    client = require_auth()
    try:
        spec = build_query_params(**flags)
        with console.status("Reading labels..."):
            result: PaginatedResult = client.list_plan_labels(
                search=search,
                include_archived=include_archived,
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
    print_tasks_rows(
        "Labels",
        rows_of(result.results),
        _LABEL_COLUMNS,
        empty="No labels.",
    )
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next), more_hint=PAGING_ONLY_MORE_HINT)


@label.command("create")
@click.option("-n", "--name", required=True, help="Label name.")
@click.option("--color", default=None, help="Label color, e.g. #ef4444.")
@click.option("-d", "--description", default=None, help="What the label means.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def label_create(name: str, color: str | None, description: str | None, json_mode: bool) -> None:
    """Create an organization label on the Plan surface.

    \b
    Examples:
      dailybot plan label create -n bug --color "#ef4444"
      dailybot plan label create -n "needs design" --json
    """
    client = require_auth()
    try:
        with console.status("Creating the label..."):
            data: dict[str, Any] = client.create_plan_label(
                name=name, color=color, description=description
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Created label {named(data, name)}")


@label.command("update")
@click.argument("label_uuid", metavar="LABEL")
@click.option("-n", "--name", default=None, help="New name (max 64).")
@click.option("--color", default=None, help="New color, a #rrggbb hex (empty clears it).")
@click.option("-d", "--description", default=None, help="New description (max 255).")
@click.option("--archive/--unarchive", "archive", default=None, help="Archive or bring back.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def label_update(
    label_uuid: str,
    name: str | None,
    color: str | None,
    description: str | None,
    archive: bool | None,
    json_mode: bool,
) -> None:
    """Edit or archive an organization label (PATCH /v1/plan/labels/<uuid>/).

    \b
    Examples:
      dailybot plan label update <label-uuid> -n "needs-design" --color "#8b5cf6"
      dailybot plan label update <label-uuid> --archive --json
    """
    fields: dict[str, Any] = {
        k: v
        for k, v in (
            ("name", name),
            ("color", color),
            ("description", description),
            ("is_archived", archive),
        )
        if v is not None
    }
    if not fields:
        raise click.UsageError("Pass at least one change. Nothing was sent.")
    client = require_auth()
    try:
        with console.status("Updating the label..."):
            data: dict[str, Any] = client.update_tasks_label(label_uuid, **fields)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Updated label {named(data, label_uuid)}")


@label.command("delete")
@click.argument("label_uuid", metavar="LABEL")
@click.option("--dry-run", is_flag=True, help="Say what would happen and send nothing.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Skip the confirmation.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def label_delete(label_uuid: str, dry_run: bool, assume_yes: bool, json_mode: bool) -> None:
    """Hard-delete an organization label. Refused with `label_in_use` while tasks use it.

    \b
    Prefer `label update --archive` when cards still carry the label.

    \b
    Examples:
      dailybot plan label delete <label-uuid> --dry-run
      dailybot plan label delete <label-uuid> --yes
    """
    if not confirm_without_preview(
        f"permanently delete label {label_uuid}.",
        assume_yes=assume_yes,
        dry_run=dry_run,
        json_mode=json_mode,
    ):
        return
    client = require_auth()
    try:
        with console.status("Deleting the label..."):
            client.delete_tasks_label(label_uuid)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json({"deleted": True, "label": label_uuid})
        return
    print_success("Label deleted.")
