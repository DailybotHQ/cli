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
from dailybot_cli.commands._schedule import (
    DAILY_KIND,
    IANA_TZ,
    REPORT_KINDS,
    TIME_HELP,
    TIME_OF_DAY,
    TIMEZONE_HELP,
    WEEKDAYS_HELP,
    require_single_weekday_for_weekly,
    weekdays_callback,
)
from dailybot_cli.commands._writes import named, report_write
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_tasks_error,
    require_auth,
    resolve_user_by_name_or_uuid,
)
from dailybot_cli.commands.query_options import PAGING_ONLY_MORE_HINT, paging_options
from dailybot_cli.display import (
    console,
    plain_text,
    print_briefing,
    print_channels_table,
    print_my_notifications,
    print_notification_catalog,
    print_notification_routes,
    print_pagination_footer,
    print_report_document,
    print_report_runs,
    print_reports,
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
DEFAULT_REPORT_WEEKDAYS: dict[str, list[int]] = {
    DAILY_KIND: [1, 2, 3, 4, 5],
    "week_start": [1],
    "week_end": [5],
}
DEFAULT_REPORT_TIME: str = "09:00"
PERSONAL_SCOPE: str = "personal"
ORG_SCOPE: str = "org"
MY_NOTIFICATIONS_DOOR: str = "me/notifications"
MY_BRIEFING_DOOR: str = "me/briefing"
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
    if not kind_list:
        raise click.UsageError("No notification kind given (the --kind value is empty).")
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


# -------------------------------------------------------------------------------------- reports


def _recipients(client: Any, refs: tuple[str, ...]) -> list[str]:
    """Resolve ``--email-to`` values (a name, an email or a uuid) to user uuids, repeats removed."""
    if not refs:
        return []
    with console.status("Finding the recipients..."):
        directory: list[dict[str, Any]] = client.list_users()
    resolved: list[str] = []
    for ref in refs:
        try:
            resolved.append(resolve_user_by_name_or_uuid(directory, ref)[0])
        except ValueError as exc:
            raise click.UsageError(plain_text(str(exc))) from exc
    return list(dict.fromkeys(resolved))


def _weekly_rule(kind: str, days: list[int]) -> None:
    try:
        require_single_weekday_for_weekly(kind, days)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc


@click.group("reports")
def reports() -> None:
    """Schedule Tasks digests to a channel and/or by email (admins change them; members read).

    \b
    Kinds: daily (what is due, in progress, blocked, overdue today), week_start (commitments,
    milestones and risks for the week) and week_end (what was completed, what slipped, who posted
    updates). Each runs on chosen weekdays at a time in a timezone (yours by default); a weekly
    kind runs on exactly one weekday. A report needs a channel or email recipients. Private boards
    and projects never appear in a channel post. Up to 10 per organization.
    """


mark_beta(reports)


@reports.command("list")
@paging_options
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def reports_list(json_mode: bool, **flags: Any) -> None:
    """List the scheduled reports.

    \b
    Examples:
      dailybot tasks reports list
      dailybot tasks reports list --json
    """
    client = require_auth()
    try:
        page: dict[str, Any] = page_kwargs(**flags)
        page.pop("params", None)
        with console.status("Reading the reports..."):
            result = client.list_reports(**page)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(envelope(result))
        return
    print_reports(result)
    print_pagination_footer(
        len(result.results),
        result.count,
        has_more=bool(result.next),
        more_hint=PAGING_ONLY_MORE_HINT,
    )


@reports.command("get")
@click.argument("report", metavar="REPORT", callback=require_uuid)
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def reports_get(report: str, json_mode: bool) -> None:
    """Show one report.

    \b
    Examples:
      dailybot tasks reports get <report-uuid>
    """
    client = require_auth()
    try:
        with console.status("Reading the report..."):
            data: dict[str, Any] = client.get_report(report)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_reports(PaginatedResult(results=[data], count=1))


@reports.command("create")
@click.option("--name", required=True, help="A name for the report.")
@click.option(
    "--kind",
    type=click.Choice(REPORT_KINDS, case_sensitive=False),
    required=True,
    help="daily, week_start or week_end.",
)
@click.option(
    "--weekdays",
    multiple=True,
    callback=weekdays_callback,
    help=f"{WEEKDAYS_HELP} Default: mon-fri (daily), mon (week_start), fri (week_end).",
)
@click.option(
    "--time",
    "time_of_day",
    type=TIME_OF_DAY,
    default=DEFAULT_REPORT_TIME,
    show_default=True,
    help=TIME_HELP,
)
@click.option("--timezone", type=IANA_TZ, default=None, help=TIMEZONE_HELP)
@click.option(
    "--channel", "channel_ref", default=None, help="Channel to post to (name or external id)."
)
@click.option(
    "--email-to",
    "email_refs",
    multiple=True,
    help="Member to email (name, email or uuid; repeatable).",
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
def reports_create(
    name: str,
    kind: str,
    weekdays: list[int] | None,
    time_of_day: str,
    timezone: str | None,
    channel_ref: str | None,
    email_refs: tuple[str, ...],
    boards: tuple[str, ...],
    projects: tuple[str, ...],
    enabled: bool | None,
    idempotency_key: str | None,
    json_mode: bool,
) -> None:
    """Create a scheduled report (admin only). Sends an idempotency key and prints it.

    \b
    Examples:
      dailybot tasks reports create --name Standup --kind daily --channel eng
      dailybot tasks reports create --name "Week end" --kind week_end --weekdays fri --time 16:00 --channel eng --email-to "Ana Ruiz"
    """
    kind = kind.lower()
    days: list[int] = weekdays if weekdays is not None else DEFAULT_REPORT_WEEKDAYS[kind]
    _weekly_rule(kind, days)
    if not channel_ref and not email_refs:
        raise click.UsageError(
            "A report needs a destination: a channel (--channel) or recipients (--email-to)."
        )
    scope: dict[str, Any] | None = _scope_from(boards, projects)
    client = require_auth()
    try:
        channel: dict[str, Any] | None = None
        if channel_ref:
            with console.status("Finding the channel..."):
                channel = {"external_id": resolve_channel(client, channel_ref)["external_id"]}
        recipients: list[str] = _recipients(client, email_refs)
        with console.status("Creating the report..."):
            data: dict[str, Any] = client.create_report(
                name=name,
                kind=kind,
                weekdays=days,
                time=time_of_day,
                timezone=timezone,
                channel=channel,
                email_recipients=recipients or None,
                scope=scope,
                enabled=enabled,
                idempotency_key=idempotency_key,
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, f"Created report {named(data, name)}")
    print_reports(PaginatedResult(results=[data], count=1))


@reports.command("update")
@click.argument("report", metavar="REPORT", callback=require_uuid)
@click.option("--name", default=None, help="New name.")
@click.option("--weekdays", multiple=True, callback=weekdays_callback, help=WEEKDAYS_HELP)
@click.option("--time", "time_of_day", type=TIME_OF_DAY, default=None, help=TIME_HELP)
@click.option("--timezone", type=IANA_TZ, default=None, help=TIMEZONE_HELP)
@click.option("--channel", "channel_ref", default=None, help="New channel (name or external id).")
@click.option(
    "--no-channel", is_flag=True, help="Stop posting to a channel (recipients must remain)."
)
@click.option(
    "--email-to",
    "email_refs",
    multiple=True,
    help="Replace the recipients with these (repeatable).",
)
@click.option("--no-email-to", is_flag=True, help="Stop emailing anyone (a channel must remain).")
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
@click.option("--enabled/--disabled", default=None, help="Turn the report on or off.")
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def reports_update(
    report: str,
    name: str | None,
    weekdays: list[int] | None,
    time_of_day: str | None,
    timezone: str | None,
    channel_ref: str | None,
    no_channel: bool,
    email_refs: tuple[str, ...],
    no_email_to: bool,
    boards: tuple[str, ...],
    projects: tuple[str, ...],
    clear_scope: bool,
    enabled: bool | None,
    json_mode: bool,
) -> None:
    """Change a report (admin only); only the flags you pass are sent.

    \b
    Examples:
      dailybot tasks reports update <report-uuid> --time 10:15
      dailybot tasks reports update <report-uuid> --weekdays mon,wed,fri --disabled
      dailybot tasks reports update <report-uuid> --no-channel --email-to "Ana Ruiz"
    """
    if channel_ref and no_channel:
        raise click.UsageError("Pass --channel or --no-channel, not both.")
    if email_refs and no_email_to:
        raise click.UsageError("Pass --email-to or --no-email-to, not both.")
    if no_channel and no_email_to:
        raise click.UsageError(
            "--no-channel with --no-email-to would leave the report with no destination: "
            "delete it with `tasks reports delete`, or keep one of them."
        )
    scope: dict[str, Any] | None = _scope_from(boards, projects, clear=clear_scope)
    nothing: bool = (
        name is None
        and weekdays is None
        and time_of_day is None
        and timezone is None
        and not channel_ref
        and not no_channel
        and not email_refs
        and not no_email_to
        and scope is None
        and enabled is None
    )
    if nothing:
        raise click.UsageError("Nothing to update. Pass at least one flag (see --help).")
    client = require_auth()
    try:
        current: dict[str, Any] | None = None
        needs_state: bool = (
            weekdays is not None
            or (no_channel and not email_refs)
            or (no_email_to and not channel_ref)
        )
        if needs_state:
            with console.status("Reading the report..."):
                current = client.get_report(report)
        if weekdays is not None and current is not None:
            _weekly_rule(str(current.get("kind", DAILY_KIND)), weekdays)
        if (
            no_channel
            and not email_refs
            and current is not None
            and not current.get("email_recipients")
        ):
            raise click.UsageError(
                "Clearing the channel would leave the report with no destination: add recipients with --email-to first."
            )
        if no_email_to and not channel_ref and current is not None and not current.get("channel"):
            raise click.UsageError(
                "Clearing the recipients would leave the report with no destination: add a channel with --channel first."
            )
        fields: dict[str, Any] = {
            key: value
            for key, value in (
                ("name", name),
                ("weekdays", weekdays),
                ("time", time_of_day),
                ("timezone", timezone),
                ("enabled", enabled),
                ("scope", scope),
            )
            if value is not None
        }
        if channel_ref:
            with console.status("Finding the channel..."):
                fields["channel"] = {
                    "external_id": resolve_channel(client, channel_ref)["external_id"]
                }
        if email_refs:
            fields["email_recipients"] = _recipients(client, email_refs)
        with console.status("Updating the report..."):
            data: dict[str, Any] = client.update_report(
                report,
                **({"clear_channel": True} if no_channel else {}),
                **({"clear_email_recipients": True} if no_email_to else {}),
                **fields,
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data, "Report updated")
    print_reports(PaginatedResult(results=[data], count=1))


@reports.command("delete")
@click.argument("report", metavar="REPORT", callback=require_uuid)
@click.option("--dry-run", is_flag=True, help="Say what would happen and send nothing.")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation.")
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def reports_delete(report: str, dry_run: bool, assume_yes: bool, json_mode: bool) -> None:
    """Delete a report (admin only). It stops running; its past runs stay in the history.

    \b
    Examples:
      dailybot tasks reports delete <report-uuid> --dry-run
      dailybot tasks reports delete <report-uuid> --yes
    """
    consequence: str = f"Deletes the scheduled report {report}; it stops posting and emailing."
    if not confirm_without_preview(
        consequence, assume_yes=assume_yes, dry_run=dry_run, json_mode=json_mode
    ):
        return
    client = require_auth()
    try:
        with console.status("Deleting the report..."):
            client.delete_report(report)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json({"deleted": True, "report": report})
        return
    print_success("Report deleted.")


@reports.command("preview")
@click.argument("report", metavar="REPORT", callback=require_uuid)
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def reports_preview(report: str, json_mode: bool) -> None:
    """Show the exact document the channel and email would receive now. Sends nothing.

    \b
    Examples:
      dailybot tasks reports preview <report-uuid>
      dailybot tasks reports preview <report-uuid> --json
    """
    client = require_auth()
    try:
        with console.status("Rendering the report..."):
            document: dict[str, Any] = client.get_report_preview(report)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(document)
        return
    print_report_document(document)


@reports.command("send-test")
@click.argument("report", metavar="REPORT", callback=require_uuid)
@click.option("--dry-run", is_flag=True, help="Show what would be sent and send nothing.")
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Skip the confirmation (the preview is still fetched and shown).",
)
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def reports_send_test(report: str, dry_run: bool, assume_yes: bool, json_mode: bool) -> None:
    """Send the report now as a test (admin only), after a preview.

    \b
    It always asks the API for a dry run first and shows the destination and the document; it
    sends for real (channel post and emails) only after you confirm or pass --yes. --dry-run
    stops after the preview.

    \b
    Examples:
      dailybot tasks reports send-test <report-uuid> --dry-run
      dailybot tasks reports send-test <report-uuid> --yes
    """
    client = require_auth()
    send_test_flow(
        lambda preview: client.send_report_test(report, dry_run=preview),
        what="report",
        dry_run=dry_run,
        assume_yes=assume_yes,
        json_mode=json_mode,
    )


@reports.command("runs")
@click.argument("report", metavar="REPORT", callback=require_uuid)
@paging_options
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def reports_runs(report: str, json_mode: bool, **flags: Any) -> None:
    """Show a report's recent runs (period, status, message id, errors).

    \b
    Examples:
      dailybot tasks reports runs <report-uuid>
    """
    client = require_auth()
    try:
        page: dict[str, Any] = page_kwargs(**flags)
        page.pop("params", None)
        with console.status("Reading the runs..."):
            result = client.list_report_runs(report, **page)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(envelope(result))
        return
    print_report_runs(result)
    print_pagination_footer(
        len(result.results),
        result.count,
        has_more=bool(result.next),
        more_hint=PAGING_ONLY_MORE_HINT,
    )


# ------------------------------------------------------------------------------------- briefing


@click.group("briefing")
def briefing() -> None:
    """Your personal daily Tasks briefing.

    \b
    A digest of your day: overdue, due today, in progress, blocked, next up, unread mentions and the
    projects you lead. Your briefing arrives by DM and/or email (never in a channel: it holds your
    private work). Pick the weekdays, the time and the timezone (yours by default). Person doors:
    `dailybot login` or a personal API key.
    """


mark_beta(briefing)


@briefing.command("get")
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def briefing_get(json_mode: bool) -> None:
    """Show your briefing settings (defaults with an `effective` flag when none is stored).

    \b
    Examples:
      dailybot tasks briefing get
      dailybot tasks briefing get --json
    """
    client = require_auth()
    try:
        with console.status("Reading your briefing..."):
            data: dict[str, Any] = client.get_my_briefing()
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode, door=MY_BRIEFING_DOOR)
    if json_mode:
        emit_json(data)
        return
    print_briefing(data)


@briefing.command("set")
@click.option("--enabled/--disabled", default=None, help="Turn the briefing on or off.")
@click.option("--weekdays", multiple=True, callback=weekdays_callback, help=WEEKDAYS_HELP)
@click.option("--time", "time_of_day", type=TIME_OF_DAY, default=None, help=TIME_HELP)
@click.option("--timezone", type=IANA_TZ, default=None, help=TIMEZONE_HELP)
@click.option("--chat/--no-chat", default=None, help="Deliver by DM (or not).")
@click.option("--email/--no-email", default=None, help="Deliver by email (or not).")
@click.option(
    "--skip-when-empty/--send-when-empty",
    default=None,
    help="Skip the day when there is nothing to report.",
)
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def briefing_set(
    enabled: bool | None,
    weekdays: list[int] | None,
    time_of_day: str | None,
    timezone: str | None,
    chat: bool | None,
    email: bool | None,
    skip_when_empty: bool | None,
    json_mode: bool,
) -> None:
    """Change your briefing (a partial update: only what you pass is sent).

    \b
    The timezone is sent only when you pass --timezone; otherwise the server keeps yours.

    \b
    Examples:
      dailybot tasks briefing set --enabled --weekdays mon,tue,wed,thu,fri --time 08:30
      dailybot tasks briefing set --email --no-chat
      dailybot tasks briefing set --timezone America/Bogota
    """
    fields: dict[str, Any] = {
        key: value
        for key, value in (
            ("enabled", enabled),
            ("weekdays", weekdays),
            ("time", time_of_day),
            ("timezone", timezone),
            ("chat", chat),
            ("email", email),
            ("skip_when_empty", skip_when_empty),
        )
        if value is not None
    }
    if not fields:
        raise click.UsageError("Nothing to change. Pass at least one flag (see --help).")
    client = require_auth()
    try:
        with console.status("Saving your briefing..."):
            data: dict[str, Any] = client.put_my_briefing(**fields)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode, door=MY_BRIEFING_DOOR)
    if json_mode:
        emit_json(data)
        return
    print_success(f"Updated {', '.join(fields)}.")
    print_briefing(data)


@briefing.command("preview")
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def briefing_preview(json_mode: bool) -> None:
    """Show your briefing as it would read right now. Sends nothing.

    \b
    Examples:
      dailybot tasks briefing preview
      dailybot tasks briefing preview --json
    """
    client = require_auth()
    try:
        with console.status("Rendering your briefing..."):
            document: dict[str, Any] = client.get_my_briefing_preview()
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode, door=MY_BRIEFING_DOOR)
    if json_mode:
        emit_json(document)
        return
    print_report_document(document)


@briefing.command("send-test")
@click.option("--dry-run", is_flag=True, help="Show what would be sent and send nothing.")
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Skip the confirmation (the preview is still fetched and shown).",
)
@click.option("--json", "json_mode", is_flag=True, help=JSON_HELP)
def briefing_send_test(dry_run: bool, assume_yes: bool, json_mode: bool) -> None:
    """Send yourself the briefing now, after a preview.

    \b
    It always asks the API for a dry run first and shows the document; it sends for real (DM and/or
    email, to you) only after you confirm or pass --yes. --dry-run stops after the preview.

    \b
    Examples:
      dailybot tasks briefing send-test --dry-run
      dailybot tasks briefing send-test --yes
    """
    client = require_auth()
    send_test_flow(
        lambda preview: client.send_my_briefing_test(dry_run=preview),
        what="briefing",
        dry_run=dry_run,
        assume_yes=assume_yes,
        json_mode=json_mode,
        door=MY_BRIEFING_DOOR,
        default_target="you",
    )
