"""Workflow commands (list / get / trigger).

Browse workflows and fire ``api_trigger`` ones via
``POST /v1/workflows/{uuid}/trigger/``. Creating and editing workflow
definitions remains in the Dailybot web app (automations builder).
"""

import json
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
    print_info,
    print_pagination_footer,
    print_success,
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

# Server rejects non-object / oversized payloads with
# ``workflow_trigger_payload_invalid``; catch the common cases client-side.
MAX_TRIGGER_PAYLOAD_BYTES: int = 8 * 1024
API_TRIGGER_TYPE: str = "api_trigger"


@click.group()
def workflow() -> None:
    """Browse and trigger your organization's workflows.

    \b
    Acts as you — visibility matches the webapp. Workflows are a plan-gated
    feature; creating/editing them is done in the Dailybot automations builder.

    \b
    Only workflows with trigger type 'api_trigger' ("When triggered via API or
    button") can be fired with 'workflow trigger' or via a chat button's
    callback_workflow. The optional --payload reaches steps as {{trigger.body.*}}.
    """


@workflow.command("list")
@query_options
@click.option(
    "--filter",
    "trigger_filter",
    default=None,
    help="Client-side filter on trigger type (e.g. api_trigger).",
)
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
    trigger_filter: str | None,
    json_mode: bool,
) -> None:
    """List workflows in your organization.

    \b
    Examples:
      dailybot workflow list
      dailybot workflow list --search deploy --json
      dailybot workflow list --filter api_trigger --all
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
    if trigger_filter:
        needle: str = trigger_filter.strip().lower()
        workflows = [
            wf
            for wf in workflows
            if str(wf.get("trigger_type", "")).lower() == needle
        ]
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


@workflow.command("trigger")
@click.argument("workflow_uuid")
@click.option(
    "--payload",
    "payload_raw",
    default=None,
    help="JSON object (≤8 KiB) exposed to steps as {{trigger.body.*}}.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def workflow_trigger(workflow_uuid: str, payload_raw: str | None, json_mode: bool) -> None:
    """Queue an api_trigger workflow run (async — returns 202).

    \b
    Only workflows with trigger type 'api_trigger' ("When triggered via API or
    button" in the automations builder) are triggerable. The run is queued —
    there is no run output to show. The same workflows can also be fired from
    a chat button via callback_workflow (see 'dailybot chat send --help').

    \b
    Examples:
      dailybot workflow trigger <workflow-uuid>
      dailybot workflow trigger <workflow-uuid> \\
        --payload '{"env":"production","requested_by":"release-bot"}'
      dailybot workflow trigger <workflow-uuid> --json
    """
    enforce_plan_access("workflow_trigger", json_mode=json_mode)
    payload: dict[str, Any] | None = None
    if payload_raw is not None:
        try:
            parsed: Any = json.loads(payload_raw)
        except json.JSONDecodeError:
            print_error("Invalid JSON in --payload.")
            raise SystemExit(1)
        if not isinstance(parsed, dict):
            print_error("--payload must be a JSON object.")
            raise SystemExit(1)
        encoded: bytes = json.dumps(parsed, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_TRIGGER_PAYLOAD_BYTES:
            print_error(
                f"--payload must serialize to at most {MAX_TRIGGER_PAYLOAD_BYTES} bytes "
                f"(got {len(encoded)})."
            )
            raise SystemExit(1)
        payload = parsed

    client = require_auth()
    try:
        with console.status("Queuing workflow..."):
            result: dict[str, Any] = client.trigger_workflow(workflow_uuid, payload=payload)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return
    print_success("Workflow queued")
    print_info(f"Workflow UUID: {result.get('workflow_uuid', workflow_uuid)}")
    print_info("The run is asynchronous — there is no run output to show.")
