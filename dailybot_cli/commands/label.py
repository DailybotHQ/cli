"""Organization Labels commands (/v1/labels/)."""

from typing import Any

import click

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    enforce_plan_access,
    exit_for_api_error,
    require_auth,
)
from dailybot_cli.display import (
    console,
    print_detail_panel,
    print_label_assignment,
    print_labels_table,
    print_success,
)

_LABEL_ENTITY_TYPES: tuple[str, ...] = ("forms", "checkins", "workflows", "automations")
_BATCH_MODES: tuple[str, ...] = ("add", "remove", "replace")


def _parse_label_entity_type(
    _ctx: click.Context, _param: click.Parameter, value: str
) -> str:
    normalized: str = value.strip().lower()
    if normalized not in _LABEL_ENTITY_TYPES:
        raise click.BadParameter(
            "must be one of: forms, checkins, workflows (automations is an alias)"
        )
    if normalized == "automations":
        return "workflows"
    return normalized


def _parse_label_uuid_list(values: tuple[str, ...]) -> list[str]:
    uuids: list[str] = []
    for raw in values:
        for part in raw.split(","):
            token: str = part.strip()
            if token:
                uuids.append(token)
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(uuids))


_LABEL_FIELDS: list[tuple[str, str]] = [
    ("Name", "name"),
    ("UUID", "uuid"),
    ("Color", "color"),
    ("Description", "description"),
    ("Archived", "is_archived"),
    ("Usage (total)", "usage_total"),
]


def _usage_total(label: dict[str, Any]) -> dict[str, Any]:
    usage: dict[str, Any] = label.get("usage") or {}
    enriched: dict[str, Any] = dict(label)
    enriched["usage_total"] = usage.get("total", 0)
    return enriched


@click.group()
def label() -> None:
    """Manage organization Labels (paid Feature.LABELS).

    \b
    Shared taxonomy for Forms, Automations, and Check-ins. Acts as you —
    permissions match the web app (members create; elevated roles manage all).
    """


@label.command("entitlement")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def label_entitlement(json_mode: bool) -> None:
    """Show Labels entitlement flags for your org."""
    enforce_plan_access("label_entitlement", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Checking Labels entitlement..."):
            data: dict[str, Any] = client.get_labels_entitlement()
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(data)
        return

    print_detail_panel(
        "Labels entitlement",
        data,
        [
            ("Entitled", "entitled"),
            ("Can create", "can_create"),
            ("Can manage all", "can_manage_all"),
            ("Can hard delete", "can_hard_delete"),
            ("Guest", "is_guest"),
        ],
    )


@label.command("list")
@click.option("--search", default=None, help="Case-insensitive name search.")
@click.option("--archived", is_flag=True, help="Include archived Labels.")
@click.option("--limit", default=20, type=click.IntRange(1, 100), show_default=True)
@click.option("--offset", default=0, type=click.IntRange(0, 100000), show_default=True)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def label_list(
    search: str | None,
    archived: bool,
    limit: int,
    offset: int,
    json_mode: bool,
) -> None:
    """List organization Labels."""
    enforce_plan_access("label_list", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Fetching labels..."):
            data: dict[str, Any] = client.list_labels(
                search=search,
                is_archived=archived,
                limit=limit,
                offset=offset,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(data)
        return

    results: list[dict[str, Any]] = data.get("results", [])
    print_labels_table(results)
    count: int | None = data.get("count")
    if count is not None:
        console.print(f"[dim]{count} total[/dim]")


@label.command("get")
@click.argument("label_uuid")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def label_get(label_uuid: str, json_mode: bool) -> None:
    """Get one Label by UUID."""
    enforce_plan_access("label_get", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Loading label..."):
            data: dict[str, Any] = client.get_label(label_uuid)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(data)
        return

    print_detail_panel("Label", _usage_total(data), _LABEL_FIELDS)


@label.command("create")
@click.option("--name", required=True, help="Label name (unique per org).")
@click.option("--color", default=None, help="Hex color (e.g. #4A90E2).")
@click.option("--description", default=None, help="Optional description.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def label_create(
    name: str,
    color: str | None,
    description: str | None,
    json_mode: bool,
) -> None:
    """Create an organization Label."""
    enforce_plan_access("label_create", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Creating label..."):
            data: dict[str, Any] = client.create_label(
                name=name,
                color=color,
                description=description,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(data)
        return

    print_success(f"Created label '{data.get('name', name)}' ({data.get('uuid', '')}).")


@label.command("update")
@click.argument("label_uuid")
@click.option("--name", default=None, help="New name.")
@click.option("--color", default=None, help="New hex color.")
@click.option("--description", default=None, help="New description (empty string clears).")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def label_update(
    label_uuid: str,
    name: str | None,
    color: str | None,
    description: str | None,
    json_mode: bool,
) -> None:
    """Update an organization Label."""
    enforce_plan_access("label_update", json_mode=json_mode)
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if color is not None:
        body["color"] = color
    if description is not None:
        body["description"] = description
    if not body:
        raise click.UsageError("Pass at least one of --name, --color, or --description.")

    client = require_auth()
    try:
        with console.status("Updating label..."):
            data: dict[str, Any] = client.update_label(label_uuid, body)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(data)
        return

    print_success(f"Updated label '{data.get('name', label_uuid)}'.")


@label.command("archive")
@click.argument("label_uuid")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def label_archive(label_uuid: str, json_mode: bool) -> None:
    """Archive a Label (idempotent)."""
    enforce_plan_access("label_archive", json_mode=json_mode)
    client = require_auth()
    try:
        with console.status("Archiving label..."):
            data: dict[str, Any] = client.archive_label(label_uuid)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(data)
        return

    print_success(f"Archived label '{data.get('name', label_uuid)}'.")


@label.command("delete")
@click.argument("label_uuid")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def label_delete(label_uuid: str, yes: bool, json_mode: bool) -> None:
    """Hard-delete a Label (elevated only; fails when in use)."""
    enforce_plan_access("label_delete", json_mode=json_mode)
    client: DailyBotClient = require_auth()

    if (
        not yes
        and not json_mode
        and not click.confirm(
            f"Permanently delete label {label_uuid}? This cannot be undone.",
            default=False,
        )
    ):
        raise SystemExit(0)

    try:
        with console.status("Deleting label..."):
            client.delete_label(label_uuid)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json({"deleted": True, "uuid": label_uuid})
        return

    print_success(f"Deleted label {label_uuid}.")


@label.command("assign")
@click.argument("entity_uuid")
@click.option(
    "--type",
    "entity_type",
    required=True,
    callback=_parse_label_entity_type,
    help="Entity type: forms, checkins, or workflows (automations alias).",
)
@click.option(
    "--label",
    "label_refs",
    multiple=True,
    help="Label UUID to attach (repeatable, or comma-separated). Replace-set.",
)
@click.option(
    "--clear",
    is_flag=True,
    help="Remove every Label from this entity (replace with an empty set).",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def label_assign(
    entity_uuid: str,
    entity_type: str,
    label_refs: tuple[str, ...],
    clear: bool,
    json_mode: bool,
) -> None:
    """Replace the Labels on one form, check-in, or workflow (web picker parity).

    \b
    Same as the chip picker in the Dailybot web app: the list you pass becomes
    the full set. Use --clear to detach every Label. Add or remove on many
    items at once with `label batch`.
    """
    label_uuids: list[str] = _parse_label_uuid_list(label_refs)
    if clear and label_uuids:
        raise click.UsageError("Pass either --label or --clear, not both.")
    if not clear and not label_uuids:
        raise click.UsageError("Pass at least one --label, or --clear to detach all.")

    client = require_auth()
    try:
        with console.status("Updating labels..."):
            data: dict[str, Any] = client.assign_entity_labels(
                entity_type,
                entity_uuid,
                label_uuids,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(data)
        return

    attached: list[dict[str, Any]] = data.get("labels") or []
    print_success(f"Updated labels on {entity_type} {data.get('uuid', entity_uuid)}.")
    print_label_assignment(str(data.get("uuid", entity_uuid)), attached)


@label.command("batch")
@click.option(
    "--type",
    "entity_type",
    required=True,
    callback=_parse_label_entity_type,
    help="Entity type: forms, checkins, or workflows (automations alias).",
)
@click.option(
    "--uuids",
    required=True,
    help="Comma-separated form, check-in, or workflow UUIDs.",
)
@click.option(
    "--label",
    "label_refs",
    multiple=True,
    help="Label UUID (repeatable, or comma-separated).",
)
@click.option(
    "--mode",
    type=click.Choice(_BATCH_MODES, case_sensitive=False),
    default="add",
    show_default=True,
    help="add / remove / replace Labels on every listed entity.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def label_batch(
    entity_type: str,
    uuids: str,
    label_refs: tuple[str, ...],
    mode: str,
    json_mode: bool,
) -> None:
    """Add, remove, or replace Labels on many forms, check-ins, or workflows."""
    entity_uuids: list[str] = [part.strip() for part in uuids.split(",") if part.strip()]
    if not entity_uuids:
        raise click.UsageError("--uuids must contain at least one UUID.")
    label_uuids: list[str] = _parse_label_uuid_list(label_refs)
    if not label_uuids:
        raise click.UsageError("Pass at least one --label.")

    client = require_auth()
    try:
        with console.status("Updating labels..."):
            data: dict[str, Any] = client.batch_entity_labels(
                entity_type=entity_type,
                entity_uuids=entity_uuids,
                label_uuids=label_uuids,
                mode=mode.lower(),
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(data)
        return

    updated: int = int(data.get("updated_count") or len(entity_uuids))
    print_success(
        f"{mode.lower()} {len(label_uuids)} label(s) on {updated} {entity_type} item(s)."
    )
