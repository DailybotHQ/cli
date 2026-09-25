"""Pinning boards and saved views (`/v1/tasks/me/favorites/`), shared by `board` and `tasks view`.

Favorites belong to a person, so every door here is person-only. Only boards and
saved views can be pinned — projects and goals cannot.
"""

from typing import Any

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_tasks_error,
    refuse_without_person,
    rows_of,
)
from dailybot_cli.config import get_token
from dailybot_cli.display import console, print_info, print_success

FAVORITE_TARGETS: tuple[str, ...] = ("board", "view")


def require_person_for_favorites(action: str, *, json_mode: bool) -> None:
    """Refuse an API key before any request: a pin list belongs to a person."""
    if get_token() is None:
        refuse_without_person(
            f"`{action}` pins something for a person, and an organization API key is nobody. "
            "Run `dailybot login` and retry.",
            json_mode=json_mode,
        )


def star(client: DailyBotClient, target_type: str, target_uuid: str, *, json_mode: bool) -> None:
    """Pin a board or view. Pinning something already pinned returns the existing pin."""
    try:
        with console.status("Pinning..."):
            data: dict[str, Any] = client.add_favorite(
                target_type=target_type, target_uuid=target_uuid
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_success(f"Pinned (position {data.get('rank', '?')}).")


def unstar(client: DailyBotClient, target_type: str, target_uuid: str, *, json_mode: bool) -> None:
    """Unpin a board or view. The pin id is looked up; unpinning an unpinned target is a no-op."""
    try:
        with console.status("Finding the pin..."):
            pins: list[dict[str, Any]] = rows_of(client.list_favorites())
        match: list[dict[str, Any]] = [
            pin
            for pin in pins
            if pin.get("target_type") == target_type and pin.get("target_uuid") == target_uuid
        ]
        if not match:
            if json_mode:
                emit_json({"unpinned": False, "reason": "not_pinned", "target": target_uuid})
            else:
                print_info("It was not pinned; nothing to do.")
            return
        with console.status("Unpinning..."):
            client.delete_favorite(str(match[0]["uuid"]))
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json({"unpinned": True, "target": target_uuid, "favorite": match[0]["uuid"]})
        return
    print_success("Unpinned.")
