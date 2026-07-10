"""Workflow read commands (list / get). Read-only — workflow writes are API-side."""

from typing import Any

import click

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    enforce_plan_access,
    exit_for_api_error,
    require_auth,
)
from dailybot_cli.commands.query_options import build_query_params, query_options, resolve_fetch_all
from dailybot_cli.display import (
    console,
    print_detail_panel,
    print_error,
    print_pagination_footer,
    print_workflows_table,
)

_WORKFLOW_FIELDS: list[tuple[str, str]] = [
    ("Name", "name"),
    ("UUID", "uuid"),
    ("Description", "description"),
    ("Trigger", "trigger_type"),
    ("Active", "active"),
    ("Total runs", "total_runs"),
    ("Last run", "last_run_at"),
]


@click.group()
def workflow() -> None:
    """Browse your organization's workflows (read-only).

    \b
    Acts as you — visibility matches the webapp. Workflows are a plan-gated
    feature; creating/editing them is done in the Dailybot web app.
    """


@workflow.command("list")
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def workflow_list(
    page: int | None,
    page_size: int | None,
    fetch_all: bool,
    limit: int | None,
    search: str | None,
    since: str | None,
    until: str | None,
    on_date: str | None,
    last_week: bool,
    today: bool,
    json_mode: bool,
) -> None:
    """List workflows in your organization.

    \b
    Examples:
      dailybot workflow list
      dailybot workflow list --search deploy --json
    """
    enforce_plan_access("workflow_list", json_mode=json_mode)
    try:
        spec = build_query_params(
            page=page,
            page_size=page_size,
            fetch_all=fetch_all,
            limit=limit,
            search=search,
            since=since,
            until=until,
            on_date=on_date,
            last_week=last_week,
            today=today,
        )
    except ValueError as exc:
        print_error(str(exc))
        raise SystemExit(1)
    client = require_auth()
    resolved_fetch_all: bool = resolve_fetch_all(spec)
    meta: dict[str, Any] = {}
    try:
        with console.status("Fetching workflows..."):
            workflows: list[dict[str, Any]] = client.list_workflows(
                search=spec.params.get("search"),
                start_date=spec.params.get("start_date"),
                end_date=spec.params.get("end_date"),
                page=spec.page,
                page_size=spec.page_size,
                fetch_all=resolved_fetch_all,
                limit=spec.limit,
                meta=meta,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(workflows)
        return
    print_workflows_table(workflows)
    print_pagination_footer(len(workflows), meta.get("count"), has_more=bool(meta.get("next")))


@workflow.command("get")
@click.argument("workflow_uuid")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def workflow_get(workflow_uuid: str, json_mode: bool) -> None:
    """Show a single workflow's configuration by UUID.

    \b
    Examples:
      dailybot workflow get <workflow_uuid>
      dailybot workflow get <workflow_uuid> --json
    """
    enforce_plan_access("workflow_get", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Fetching workflow..."):
            data: dict[str, Any] = client.get_workflow(workflow_uuid)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_detail_panel("Workflow", data, _WORKFLOW_FIELDS)
