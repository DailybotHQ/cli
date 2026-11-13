"""Resolve a channel the way the notification, route and report commands take it.

The API stores a channel as ``{external_id, name, type}`` and is addressed by ``external_id`` (the
chat-platform id that ``dailybot chat send --channel`` also takes). A person types either that id or the
channel's name, so the commands resolve the typed reference through ``tasks channels search``. Channel
names are user-authored text: they are quoted as data wherever they appear in a message.

Qualified references (PLAN_002, frozen grammar W2, L44, L74). Besides a raw id or a name, a channel can
be named on one chat platform of the organization: `slack:C0123` (platform-qualified, split on the first
colon, so `msteams:19:abc@thread.tacv2` keeps its Teams id) or `<platform-id>:C0123`, where the platform
id is a `ChatPlatformSummary.id` from `dailybot org`. A raw Teams id `19:...` stays raw. Qualified forms
are sent only to organizations whose `/v1/organization/` serves `chat_platforms`; raw ids keep working
until the multi-channel release + 90 days.
"""

import re
from dataclasses import dataclass
from typing import Any

import click

from dailybot_cli.api_client import APIError, TransportError
from dailybot_cli.display import plain_text, present_untrusted

PUBLIC_CHANNEL_TYPE: str = "channel"
# A platform id (Slack `C0123`, a Discord snowflake, a Teams `19:...@thread`) is one token; a name the
# server did not match is usually several words. Only a single token is worth a scan for an exact id.
SINGLE_TOKEN_PATTERN: re.Pattern[str] = re.compile(r"^\S+$")
MAX_CANDIDATES_SHOWN: int = 8

PLATFORM_QUALIFIED_PATTERN: re.Pattern[str] = re.compile(r"^(slack|msteams|discord|hangouts):(.+)$")
INSTALLATION_QUALIFIED_PATTERN: re.Pattern[str] = re.compile(
    r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):(.+)$"
)
# Not a chat send destination in phase 1: an org without an external platform answers
# `platform_not_connected`, and the CLI never routes a message to Dailybot Chat instead.
DAILYBOT_PREFIX_PATTERN: re.Pattern[str] = re.compile(r"^(dailybot):(.*)$")
CHAT_PLATFORMS_KEY: str = "chat_platforms"


@dataclass(frozen=True)
class ChannelReference:
    """A parsed channel reference: ``kind`` is raw, platform, installation or dailybot."""

    kind: str
    qualifier: str | None
    channel_id: str
    original: str

    @property
    def is_qualified(self) -> bool:
        return self.kind in ("platform", "installation")


def parse_channel_reference(reference: str) -> ChannelReference:
    """Classify a channel reference by the frozen grammar; anything else is raw."""
    for kind, pattern in (
        ("platform", PLATFORM_QUALIFIED_PATTERN),
        ("installation", INSTALLATION_QUALIFIED_PATTERN),
        ("dailybot", DAILYBOT_PREFIX_PATTERN),
    ):
        match: re.Match[str] | None = pattern.match(reference)
        if match:
            return ChannelReference(kind, match.group(1), match.group(2), reference)
    return ChannelReference("raw", None, reference, reference)


def _org_serves_chat_platforms(client: Any) -> bool | None:
    """Whether the organization takes qualified references; ``None`` when it cannot be read.

    The keys are served only when the organization's gate is on (L74), so their presence is
    the signal. Read only when a qualified reference was actually typed.
    """
    try:
        organization: Any = client.get_organization()
    except (APIError, TransportError):
        return None
    return isinstance(organization, dict) and CHAT_PLATFORMS_KEY in organization


def _qualified_refused(reference: ChannelReference) -> click.UsageError:
    return click.UsageError(
        f"This organization does not take platform-qualified channels yet. Pass the channel id "
        f"alone: {plain_text(reference.channel_id)}"
    )


def _dailybot_refused() -> click.UsageError:
    return click.UsageError(
        "`dailybot:` is not a chat send destination: messages are never delivered to "
        "Dailybot Chat. Target a channel on a connected chat platform (see `dailybot org`)."
    )


def check_chat_channel_references(client: Any, payload: dict[str, Any]) -> None:
    """Validate the `target_channels` of a chat send payload against the grammar.

    Raw references pass untouched and cost nothing. A `dailybot:` reference is refused. Qualified
    references pass verbatim when the organization serves `chat_platforms`, and are refused when it
    does not (the server would read them as raw ids). If the organization cannot be read, the payload
    goes as typed and the server decides.
    """
    targets: Any = payload.get("target_channels")
    if not isinstance(targets, list):
        return
    references: list[ChannelReference] = []
    for target in targets:
        raw: Any = target.get("id") if isinstance(target, dict) else target
        if isinstance(raw, str):
            references.append(parse_channel_reference(raw))
    for reference in references:
        if reference.kind == "dailybot":
            raise _dailybot_refused()
    qualified: list[ChannelReference] = [r for r in references if r.is_qualified]
    if qualified and _org_serves_chat_platforms(client) is False:
        raise _qualified_refused(qualified[0])


def _describe(channel: dict[str, Any]) -> str:
    return f"{present_untrusted(channel.get('name'), limit=40)} ({plain_text(channel.get('external_id'))})"


def resolve_channel(client: Any, reference: str, *, public_only: bool = False) -> dict[str, str]:
    """Return ``{external_id, name, type}`` for an id or a name; ``click.UsageError`` when it cannot.

    Order: exact ``external_id``, exact name (case-insensitive), then a unique substring of the name.
    A channel the caller cannot see is simply absent from the list, so it reads as "not found".
    """
    wanted: str = reference.strip()
    channel_type: str | None = PUBLIC_CHANNEL_TYPE if public_only else None
    parsed: ChannelReference = parse_channel_reference(wanted)
    if parsed.kind == "dailybot":
        raise _dailybot_refused()
    if parsed.is_qualified:
        return _resolve_qualified(client, parsed, channel_type)

    def fetch(search: str | None) -> list[dict[str, Any]]:
        result: Any = client.search_channels(
            search=search, channel_type=channel_type, fetch_all=True
        )
        return [row for row in result.results if isinstance(row, dict)]

    # The server matches names, so a name is searched there (no scan of the whole workspace). A
    # platform id is not a name: only when the reference looks like one is the list scanned for it.
    channels: list[dict[str, Any]] = fetch(wanted)
    if not channels and SINGLE_TOKEN_PATTERN.match(wanted):
        channels = fetch(None)
    folded: str = wanted.casefold()

    for channel in channels:
        if str(channel.get("external_id")) == wanted:
            return _as_reference(channel)
    exact: list[dict[str, Any]] = [
        c for c in channels if str(c.get("name", "")).casefold() == folded
    ]
    if len(exact) == 1:
        return _as_reference(exact[0])
    partial: list[dict[str, Any]] = exact or [
        c for c in channels if folded and folded in str(c.get("name", "")).casefold()
    ]
    if len(partial) == 1:
        return _as_reference(partial[0])
    if partial:
        shown: str = ", ".join(_describe(c) for c in partial[:MAX_CANDIDATES_SHOWN])
        raise click.UsageError(
            f"More than one channel matches {present_untrusted(wanted, limit=40)}: {shown}. "
            "Pass the external id."
        )
    scope: str = "public channel" if public_only else "channel"
    raise click.UsageError(
        f"No {scope} matches {present_untrusted(wanted, limit=40)}. "
        "List them with `dailybot plan tasks channels search`."
    )


def _as_reference(channel: dict[str, Any]) -> dict[str, str]:
    return {
        "external_id": str(channel["external_id"]),
        "name": str(channel.get("name", "")),
        "type": str(channel.get("type", PUBLIC_CHANNEL_TYPE)),
    }


def _resolve_qualified(
    client: Any, reference: ChannelReference, channel_type: str | None
) -> dict[str, str]:
    """A qualified reference keeps its qualifier on the wire; the list only fills in the name.

    The server owns the platform match (`channel_reference_unknown` / `_ambiguous`), so a channel
    the list does not show is still sent as typed.
    """
    if _org_serves_chat_platforms(client) is False:
        raise _qualified_refused(reference)
    result: Any = client.search_channels(search=None, channel_type=channel_type, fetch_all=True)
    for channel in result.results:
        if isinstance(channel, dict) and str(channel.get("external_id")) == reference.channel_id:
            return {
                "external_id": reference.original,
                "name": str(channel.get("name", "")),
                "type": str(channel.get("type", PUBLIC_CHANNEL_TYPE)),
            }
    return {
        "external_id": reference.original,
        "name": "",
        "type": channel_type or PUBLIC_CHANNEL_TYPE,
    }
