"""Resolve a channel the way the notification, route and report commands take it.

The API stores a channel as ``{external_id, name, type}`` and is addressed by ``external_id`` (the
chat-platform id that ``dailybot chat send --channel`` also takes). A person types either that id or the
channel's name, so the commands resolve the typed reference through ``tasks channels search``. Channel
names are user-authored text: they are quoted as data wherever they appear in a message.
"""

from typing import Any

import click

from dailybot_cli.display import present_untrusted

PUBLIC_CHANNEL_TYPE: str = "channel"
MAX_CHANNELS_TO_SCAN: int = 500
MAX_CANDIDATES_SHOWN: int = 8


def _describe(channel: dict[str, Any]) -> str:
    return f"{present_untrusted(channel.get('name'), limit=40)} ({channel.get('external_id')})"


def resolve_channel(client: Any, reference: str, *, public_only: bool = False) -> dict[str, str]:
    """Return ``{external_id, name, type}`` for an id or a name; ``click.UsageError`` when it cannot.

    Order: exact ``external_id``, exact name (case-insensitive), then a unique substring of the name.
    A channel the caller cannot see is simply absent from the list, so it reads as "not found".
    """
    result: Any = client.search_channels(
        channel_type=PUBLIC_CHANNEL_TYPE if public_only else None,
        fetch_all=True,
        limit=MAX_CHANNELS_TO_SCAN,
    )
    channels: list[dict[str, Any]] = [row for row in result.results if isinstance(row, dict)]
    wanted: str = reference.strip()
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
        "List them with `dailybot tasks channels search`."
    )


def _as_reference(channel: dict[str, Any]) -> dict[str, str]:
    return {
        "external_id": str(channel["external_id"]),
        "name": str(channel.get("name", "")),
        "type": str(channel.get("type", PUBLIC_CHANNEL_TYPE)),
    }
