"""Tasks notification settings: personal preferences, organization routes, scheduled reports, briefing.

These groups hang under ``dailybot tasks`` (``tasks notifications``, ``tasks routes``, ``tasks reports``,
``tasks briefing``, ``tasks channels``). They configure who is told what, where and when; they are not task
work, so no agent name is stamped on their writes. Every name, title and channel name the API returns is
user-authored data and is rendered quoted (``display.present_untrusted``).
"""

from typing import Any

import click

from dailybot_cli.api_client import APIError, PaginatedResult
from dailybot_cli.commands._beta import mark_beta
from dailybot_cli.commands._channels import PUBLIC_CHANNEL_TYPE, resolve_channel
from dailybot_cli.commands._destructive import confirm_without_preview
from dailybot_cli.commands._outbound import send_test_flow
from dailybot_cli.commands._paging import envelope, page_kwargs
from dailybot_cli.commands._refs import require_uuid, require_uuids
from dailybot_cli.commands._writes import named, report_write
from dailybot_cli.commands.public_api_helpers import emit_json, exit_for_tasks_error, require_auth
from dailybot_cli.commands.query_options import PAGING_ONLY_MORE_HINT, paging_options
from dailybot_cli.display import (
    console,
    print_channels_table,
    print_my_notifications,
    print_notification_catalog,
    print_notification_routes,
    print_pagination_footer,
    print_route_deliveries,
    print_success,
)

CHANNEL_TYPE_CHOICES: tuple[str, ...] = (
    "channel",
    "private_channel",
    "group_chat",
    "direct_message",
    "public",
)
ROUTE_SCOPE_TYPES: tuple[str, ...] = ("boards", "projects")
PERSONAL_SCOPE: str = "personal"
ORG_SCOPE: str = "org"
MY_NOTIFICATIONS_DOOR: str = "me/notifications"
JSON_HELP: str = "Emit machine-readable JSON to stdout."


def _split_kinds(raw: tuple[str, ...]) -> list[str]:
    """Flatten repeated and comma-separated ``--kind`` values, dropping blanks and repeats."""
    kinds: list[str] = []
    for chunk in raw:
        kinds.extend(part.strip() for part in chunk.split(",") if part.strip())
    return list(dict.fromkeys(kinds))


def validate_kinds(catalog: dict[str, Any], kinds: list[str], *, scope: str) -> None:
    """Refuse locally a kind that is unknown or of the other scope, naming what is valid."""
    known: dict[str, str] = {
        str(k["key"]): str(k.get("scope"))
        for k in catalog.get("kinds") or []
        if isinstance(k, dict) and "key" in k
    }
    valid: list[str] = sorted(key for key, kind_scope in known.items() if kind_scope == scope)
    other_command: str = "tasks routes" if scope == PERSONAL_SCOPE else "tasks notifications set"
    for kind in kinds:
        if kind not in known:
            raise click.UsageError(
                f"Unknown notification kind {kind!r}. Valid {scope} kinds: {', '.join(valid)}."
            )
        if known[kind] != scope:
            raise click.UsageError(
                f"{kind!r} is an {known[kind]} kind, not a {scope} one: use `dailybot {other_command}`."
            )


@click.group("notifications")
def notifications() -> None:
    """Choose which Tasks events tell you, and where.

    \b
    Personal preferences: a kind x chat x email matrix, plus where chat notifications land (your DM,
    or a public channel). Work on private boards and projects always comes by DM. Organization-wide
    posts to a channel are `dailybot tasks routes`; scheduled digests are `dailybot tasks reports`.
    """


mark_beta(notifications)


@notifications.command("catalog")
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def notifications_catalog(json_mode: bool) -> None:
    """List every notification kind (personal and organization) with its defaults.

    \b
    Examples:
      dailybot tasks notifications catalog
      dailybot tasks notifications catalog --json
    """
    client = require_auth()
    try:
        with console.status("Reading the notification catalog..."):
            catalog: dict[str, Any] = client.get_notifications_catalog()
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(catalog)
        return
    print_notification_catalog(catalog)


@notifications.command("get")
@click.option(
    "--me", "me", is_flag=True, default=True, help="Your own preferences (the only scope today)."
)
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def notifications_get(me: bool, json_mode: bool) -> None:
    """Show your notification preferences and where they are delivered.

    \b
    Needs a person: `dailybot login` or a personal API key.

    \b
    Examples:
      dailybot tasks notifications get
      dailybot tasks notifications get --json
    """
    client = require_auth()
    try:
        with console.status("Reading your notification preferences..."):
            data: dict[str, Any] = client.get_my_notifications()
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode, door=MY_NOTIFICATIONS_DOOR)
    if json_mode:
        emit_json(data)
        return
    print_my_notifications(data)


@notifications.command("set")
@click.option(
    "--me", "me", is_flag=True, default=True, help="Your own preferences (the only scope today)."
)
@click.option(
    "--kind",
    "kinds",
    multiple=True,
    help="Personal kind to change (repeatable, or comma-separated). See `tasks notifications catalog`.",
)
@click.option(
    "--chat/--no-chat", default=None, help="Turn chat delivery on or off for the named kinds."
)
@click.option(
    "--email/--no-email", default=None, help="Turn email delivery on or off for the named kinds."
)
@click.option("--dm", "to_dm", is_flag=True, help="Deliver chat notifications to your DM.")
@click.option(
    "--channel",
    default=None,
    help="Deliver chat notifications in this PUBLIC channel (name or external id).",
)
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def notifications_set(
    me: bool,
    kinds: tuple[str, ...],
    chat: bool | None,
    email: bool | None,
    to_dm: bool,
    channel: str | None,
    json_mode: bool,
) -> None:
    """Change your notification preferences (a partial update: only what you pass is sent).

    \b
    Name the kinds with --kind and say what to do with them (--chat/--no-chat, --email/--no-email);
    and/or pick the destination with --dm or --channel. Work on private boards and projects always
    comes by DM, whatever the destination.

    \b
    Examples:
      dailybot tasks notifications set --kind tasks_assigned,tasks_commented --chat --no-email
      dailybot tasks notifications set --kind tasks_reactions --chat
      dailybot tasks notifications set --channel eng
      dailybot tasks notifications set --dm
    """
    kind_list: list[str] = _split_kinds(kinds)
    if to_dm and channel:
        raise click.UsageError("Pass --dm or --channel, not both.")
    if kind_list and chat is None and email is None:
        raise click.UsageError(
            "Say what to do with the kinds: --chat/--no-chat and/or --email/--no-email."
        )
    if not kind_list and (chat is not None or email is not None):
        raise click.UsageError(
            "Name the kinds with --kind (see `dailybot tasks notifications catalog`)."
        )
    if not kind_list and not to_dm and not channel:
        raise click.UsageError(
            "Nothing to change. Pass --kind with --chat/--email, and/or --dm or --channel."
        )

    client = require_auth()
    items: list[dict[str, Any]] | None = None
    destination: dict[str, Any] | None = None
    try:
        if kind_list:
            with console.status("Checking the notification kinds..."):
                validate_kinds(client.get_notifications_catalog(), kind_list, scope=PERSONAL_SCOPE)
            flags: dict[str, bool] = {
                name: value
                for name, value in (("chat", chat), ("email", email))
                if value is not None
            }
            items = [{"kind": kind, **flags} for kind in kind_list]
        if to_dm:
            destination = {"type": "dm"}
        elif channel:
            with console.status("Finding the channel..."):
                resolved: dict[str, str] = resolve_channel(client, channel, public_only=True)
            destination = {
                "type": PUBLIC_CHANNEL_TYPE,
                "channel": {"external_id": resolved["external_id"]},
            }
        with console.status("Saving your preferences..."):
            data: dict[str, Any] = client.put_my_notifications(items=items, destination=destination)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode, door=MY_NOTIFICATIONS_DOOR)
    if json_mode:
        emit_json(data)
        return
    changed: list[str] = [*kind_list, *(["destination"] if destination else [])]
    print_success(f"Updated {', '.join(changed)}.")
    print_my_notifications(data)


@click.group("channels")
def channels() -> None:
    """Find the chat channels that routes, reports and notifications can post to.

    \b
    Not the same as `dailybot channels list` (report channels for forms and check-ins): these are
    the chat platform's own channels, and the external id is what `tasks routes`, `tasks reports`
    and `chat send --channel` take.
    """


mark_beta(channels)


@channels.command("search")
@click.option("-q", "--query", default=None, help="Only channels whose name contains this text.")
@click.option(
    "--type",
    "channel_type",
    type=click.Choice(CHANNEL_TYPE_CHOICES, case_sensitive=False),
    default=None,
    help="Only this kind of channel; `public` means public channels only.",
)
@paging_options
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def channels_search(
    query: str | None, channel_type: str | None, json_mode: bool, **flags: Any
) -> None:
    """Search the channels you can pick, by name or type.

    \b
    These are the chat platform's channels, not the report channels of `dailybot channels list`:
    the external id shown here is what `tasks routes`, `tasks reports` and `chat send --channel`
    take. Organization admins also see the private channels the bot is in; everyone else sees
    public channels only (a private channel is absent, not an error). Paging is one page per
    call: follow `next` with --page.

    \b
    Examples:
      dailybot tasks channels search -q eng
      dailybot tasks channels search --type public --json
    """
    wire_type: str | None = None
    if channel_type:
        wire_type = (
            PUBLIC_CHANNEL_TYPE if channel_type.lower() == "public" else channel_type.lower()
        )
    client = require_auth()
    try:
        page: dict[str, Any] = page_kwargs(**flags)
        page.pop("params", None)
        with console.status("Searching channels..."):
            result = client.search_channels(search=query, channel_type=wire_type, **page)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(envelope(result))
        return
    print_channels_table(result.results)
    print_pagination_footer(
        len(result.results),
        result.count,
        has_more=bool(result.next),
        more_hint=PAGING_ONLY_MORE_HINT,
    )


# --------------------------------------------------------------------------------------- routes


def _scope_from(
    boards: tuple[str, ...], projects: tuple[str, ...], *, clear: bool = False
) -> dict[str, Any] | None:
    """The ``scope`` object for ``--board`` / ``--project`` (one kind at a time), or all on ``--clear-scope``."""
    if clear:
        if boards or projects:
            raise click.UsageError("--clear-scope cannot be combined with --board or --project.")
        return {"type": "all", "uuids": []}
    if boards and projects:
        raise click.UsageError("Scope by boards or by projects, not both.")
    if boards:
        return {"type": "boards", "uuids": list(dict.fromkeys(boards))}
    if projects:
        return {"type": "projects", "uuids": list(dict.fromkeys(projects))}
    return None


def _org_kinds(client: Any, kinds: tuple[str, ...]) -> list[str]:
    """Split, de-duplicate and validate ``--kind`` values against the catalog's organization kinds."""
    kind_list: list[str] = _split_kinds(kinds)
    with console.status("Checking the notification kinds..."):
        validate_kinds(client.get_notifications_catalog(), kind_list, scope=ORG_SCOPE)
    return kind_list


@click.group("routes")
def routes() -> None:
    """Post organization Tasks events to a chat channel (admins change them; members read).

    \b
    A route = a channel + the organization event kinds it receives (card created or completed,
    project health or lead changed, milestone reached, ...), optionally limited to some boards or
    projects. Private boards and projects never post to a channel. Up to 10 routes per organization.
    Find channels with `dailybot tasks channels search`; see kinds with
    `dailybot tasks notifications catalog`.
    """


mark_beta(routes)


@routes.command("list")
@paging_options
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def routes_list(json_mode: bool, **flags: Any) -> None:
    """List the notification routes.

    \b
    Examples:
      dailybot tasks routes list
      dailybot tasks routes list --json
    """
    client = require_auth()
    try:
        page: dict[str, Any] = page_kwargs(**flags)
        page.pop("params", None)
        with console.status("Reading the routes..."):
            result = client.list_notification_routes(**page)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(envelope(result))
        return
    print_notification_routes(result)
    print_pagination_footer(
        len(result.results),
        result.count,
        has_more=bool(result.next),
        more_hint=PAGING_ONLY_MORE_HINT,
    )


@routes.command("get")
@click.argument("route", metavar="ROUTE", callback=require_uuid)
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def routes_get(route: str, json_mode: bool) -> None:
    """Show one route.

    \b
    Examples:
      dailybot tasks routes get <route-uuid>
    """
    client = require_auth()
    try:
        with console.status("Reading the route..."):
            data: dict[str, Any] = client.get_notification_route(route)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_notification_routes(PaginatedResult(results=[data], count=1))


@routes.command("create")
@click.option("--name", required=True, help="A name for the route.")
@click.option(
    "--channel", "channel_ref", required=True, help="Channel to post to (name or external id)."
)
@click.option(
    "--kind",
    "kinds",
    multiple=True,
    required=True,
    help="Organization kind to post (repeatable, or comma-separated).",
)
@click.option(
    "--board",
    "boards",
    multiple=True,
    callback=require_uuids,
    help="Only this board (uuid, repeatable).",
)
@click.option(
    "--project",
    "projects",
    multiple=True,
    callback=require_uuids,
    help="Only this project (uuid, repeatable).",
)
@click.option("--enabled/--disabled", default=None, help="Start enabled (the default) or disabled.")
@click.option("--idempotency-key", default=None, help="Reuse a key to make a retry safe.")
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def routes_create(
    name: str,
    channel_ref: str,
    kinds: tuple[str, ...],
    boards: tuple[str, ...],
    projects: tuple[str, ...],
    enabled: bool | None,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Create a route (admin only). Sends an idempotency key and prints it.

    \b
    Examples:
      dailybot tasks routes create --name Completions --channel eng --kind task.completed,project.health_changed
      dailybot tasks routes create --name "Design board" --channel design --kind task.created --board <board-uuid>
    """
    scope: dict[str, Any] | None = _scope_from(boards, projects)
    client = require_auth()
    try:
        kind_list: list[str] = _org_kinds(client, kinds)
        with console.status("Finding the channel..."):
            channel: dict[str, str] = resolve_channel(client, channel_ref)
        with console.status("Creating the route..."):
            data: dict[str, Any] = client.create_notification_route(
                name=name,
                channel={"external_id": channel["external_id"]},
                kinds=kind_list,
                scope=scope,
                enabled=enabled,
                idempotency_key=idempotency_key,
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Created route {named(data, name)}")
    print_notification_routes(PaginatedResult(results=[data], count=1))


@routes.command("update")
@click.argument("route", metavar="ROUTE", callback=require_uuid)
@click.option("--name", default=None, help="New name.")
@click.option("--channel", "channel_ref", default=None, help="New channel (name or external id).")
@click.option(
    "--kind",
    "kinds",
    multiple=True,
    help="Replace the kinds with these (repeatable, or comma-separated).",
)
@click.option(
    "--board",
    "boards",
    multiple=True,
    callback=require_uuids,
    help="Only this board (uuid, repeatable).",
)
@click.option(
    "--project",
    "projects",
    multiple=True,
    callback=require_uuids,
    help="Only this project (uuid, repeatable).",
)
@click.option("--clear-scope", is_flag=True, help="Cover the whole organization again.")
@click.option("--enabled/--disabled", default=None, help="Turn the route on or off.")
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def routes_update(
    route: str,
    name: str | None,
    channel_ref: str | None,
    kinds: tuple[str, ...],
    boards: tuple[str, ...],
    projects: tuple[str, ...],
    clear_scope: bool,
    enabled: bool | None,
    json_mode: bool,
) -> None:
    """Change a route (admin only); only the flags you pass are sent.

    \b
    Examples:
      dailybot tasks routes update <route-uuid> --disabled
      dailybot tasks routes update <route-uuid> --kind task.completed --channel eng
      dailybot tasks routes update <route-uuid> --clear-scope
    """
    scope: dict[str, Any] | None = _scope_from(boards, projects, clear=clear_scope)
    if name is None and channel_ref is None and not kinds and scope is None and enabled is None:
        raise click.UsageError(
            "Nothing to update. Pass at least one of --name, --channel, --kind, --board/--project, --clear-scope, --enabled/--disabled."
        )
    client = require_auth()
    try:
        fields: dict[str, Any] = {
            key: value
            for key, value in (("name", name), ("enabled", enabled), ("scope", scope))
            if value is not None
        }
        if kinds:
            fields["kinds"] = _org_kinds(client, kinds)
        if channel_ref:
            with console.status("Finding the channel..."):
                fields["channel"] = {
                    "external_id": resolve_channel(client, channel_ref)["external_id"]
                }
        with console.status("Updating the route..."):
            data: dict[str, Any] = client.update_notification_route(route, **fields)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Route updated")
    print_notification_routes(PaginatedResult(results=[data], count=1))


@routes.command("delete")
@click.argument("route", metavar="ROUTE", callback=require_uuid)
@click.option("--dry-run", is_flag=True, help="Say what would happen and send nothing.")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation.")
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def routes_delete(route: str, dry_run: bool, assume_yes: bool, json_mode: bool) -> None:
    """Delete a route (admin only). The channel stops receiving its events; past deliveries stay in the log.

    \b
    Examples:
      dailybot tasks routes delete <route-uuid> --dry-run
      dailybot tasks routes delete <route-uuid> --yes
    """
    consequence: str = (
        f"Deletes the notification route {route}; its channel stops receiving those events."
    )
    if not confirm_without_preview(
        consequence, assume_yes=assume_yes, dry_run=dry_run, json_mode=json_mode
    ):
        return
    client = require_auth()
    try:
        with console.status("Deleting the route..."):
            client.delete_notification_route(route)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json({"deleted": True, "route": route})
        return
    print_success("Route deleted.")


@routes.command("send-test")
@click.argument("route", metavar="ROUTE", callback=require_uuid)
@click.option("--dry-run", is_flag=True, help="Show what would be posted and send nothing.")
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Skip the confirmation (the preview is still fetched and shown).",
)
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def routes_send_test(route: str, dry_run: bool, assume_yes: bool, json_mode: bool) -> None:
    """Post a sample message to the route's channel (admin only), after a preview.

    \b
    It always asks the API for a dry run first and shows the channel and the message; it posts for
    real only after you confirm (or pass --yes). --dry-run stops after the preview.

    \b
    Examples:
      dailybot tasks routes send-test <route-uuid> --dry-run
      dailybot tasks routes send-test <route-uuid> --yes
    """
    client = require_auth()
    send_test_flow(
        lambda preview: client.send_route_test(route, dry_run=preview),
        what="test message",
        dry_run=dry_run,
        assume_yes=assume_yes,
        json_mode=json_mode,
    )


@routes.command("deliveries")
@click.argument("route", metavar="ROUTE", callback=require_uuid)
@paging_options
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def routes_deliveries(route: str, json_mode: bool, **flags: Any) -> None:
    """Show a route's recent deliveries (status and error per post).

    \b
    Examples:
      dailybot tasks routes deliveries <route-uuid>
    """
    client = require_auth()
    try:
        page: dict[str, Any] = page_kwargs(**flags)
        page.pop("params", None)
        with console.status("Reading the deliveries..."):
            result = client.list_route_deliveries(route, **page)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(envelope(result))
        return
    print_route_deliveries(result)
    print_pagination_footer(
        len(result.results),
        result.count,
        has_more=bool(result.next),
        more_hint=PAGING_ONLY_MORE_HINT,
    )
