"""Tasks notification settings: personal preferences, organization routes, scheduled reports, briefing.

These groups hang under ``dailybot tasks`` (``tasks notifications``, ``tasks routes``, ``tasks reports``,
``tasks briefing``, ``tasks channels``). They configure who is told what, where and when; they are not task
work, so no agent name is stamped on their writes. Every name, title and channel name the API returns is
user-authored data and is rendered quoted (``display.present_untrusted``).
"""

from typing import Any

import click

from dailybot_cli.api_client import APIError
from dailybot_cli.commands._beta import mark_beta
from dailybot_cli.commands._channels import PUBLIC_CHANNEL_TYPE, resolve_channel
from dailybot_cli.commands._paging import envelope, page_kwargs
from dailybot_cli.commands.public_api_helpers import emit_json, exit_for_tasks_error, require_auth
from dailybot_cli.commands.query_options import PAGING_ONLY_MORE_HINT, paging_options
from dailybot_cli.display import (
    console,
    print_channels_table,
    print_my_notifications,
    print_notification_catalog,
    print_pagination_footer,
    print_success,
)

CHANNEL_TYPE_CHOICES: tuple[str, ...] = (
    "channel",
    "private_channel",
    "group_chat",
    "direct_message",
    "public",
)
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
