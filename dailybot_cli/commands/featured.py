"""Private Featured star commands (/v1/me/featured/)."""

from typing import Any

import click

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_api_error,
    require_auth,
)
from dailybot_cli.display import console, print_featured_summary, print_success

FEATURED_ENTITY_TYPES: tuple[str, ...] = ("forms", "automations", "checkins")


def _parse_entity_type(ctx: click.Context, param: click.Parameter, value: str) -> str:
    normalized: str = value.strip().lower()
    if normalized not in FEATURED_ENTITY_TYPES:
        raise click.BadParameter(f"entity_type must be one of: {', '.join(FEATURED_ENTITY_TYPES)}")
    return normalized


@click.group()
def featured() -> None:
    """Manage your private Featured stars on Forms, Automations, and Check-ins.

    \b
    Featured is per-user (not org-shared). Not gated by paid Labels.
    """


@featured.command("list")
@click.option(
    "--entity-type",
    "entity_type",
    required=True,
    callback=_parse_entity_type,
    help="Entity type: forms, automations, or checkins.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def featured_list(entity_type: str, json_mode: bool) -> None:
    """List Featured entity UUIDs for one entity type."""
    client = require_auth()
    try:
        with console.status("Fetching featured items..."):
            data: dict[str, Any] = client.list_featured(entity_type=entity_type)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(data)
        return

    print_featured_summary(data)


@featured.command("set")
@click.option(
    "--entity-type",
    "entity_type",
    required=True,
    callback=_parse_entity_type,
    help="Entity type: forms, automations, or checkins.",
)
@click.argument("entity_uuid")
@click.option(
    "--featured/--unfeatured",
    default=True,
    help="Star (default) or unstar the entity.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def featured_set(
    entity_type: str,
    entity_uuid: str,
    featured: bool,
    json_mode: bool,
) -> None:
    """Toggle Featured for one entity."""
    client = require_auth()
    try:
        with console.status("Updating featured state..."):
            data: dict[str, Any] = client.set_featured(
                entity_type,
                entity_uuid,
                featured=featured,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(data)
        return

    state: str = "featured" if data.get("is_featured", featured) else "unfeatured"
    print_success(f"Marked {entity_uuid} as {state} ({entity_type}).")


@featured.command("batch")
@click.option(
    "--entity-type",
    "entity_type",
    required=True,
    callback=_parse_entity_type,
    help="Entity type: forms, automations, or checkins.",
)
@click.option(
    "--uuids",
    required=True,
    help="Comma-separated entity UUIDs.",
)
@click.option(
    "--featured/--unfeatured",
    default=True,
    help="Feature (default) or unfeature all listed entities.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def featured_batch(
    entity_type: str,
    uuids: str,
    featured: bool,
    json_mode: bool,
) -> None:
    """Batch feature or unfeature multiple entities."""
    entity_uuids: list[str] = [part.strip() for part in uuids.split(",") if part.strip()]
    if not entity_uuids:
        raise click.UsageError("--uuids must contain at least one UUID.")

    client = require_auth()
    try:
        with console.status("Updating featured items..."):
            data: dict[str, Any] = client.batch_featured(
                entity_type=entity_type,
                entity_uuids=entity_uuids,
                featured=featured,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(data)
        return

    updated: int = len(data.get("updated_entity_uuids", entity_uuids))
    state: str = "featured" if featured else "unfeatured"
    print_success(f"Marked {updated} {entity_type} item(s) as {state}.")
