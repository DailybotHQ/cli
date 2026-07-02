"""Small deterministic intents for terminal-native chat flows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

CHECKINS_INTENT_PHRASES: frozenset[str] = frozenset(
    {
        "checkin",
        "check-in",
        "checkins",
        "check-ins",
        "show checkins",
        "show check-ins",
        "show my checkins",
        "show my check-ins",
        "list checkins",
        "list check-ins",
        "my checkins",
        "my check-ins",
    }
)

_CHECKINS_QUESTION_RE: re.Pattern[str] = re.compile(
    r"\b(what|which|show|list|do i have|missing|pending)\b.*\b(checkins?|check-ins?|standups?|stand-ups?)\b",
    re.IGNORECASE,
)

_KUDOS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^(?:please\s+)?(?:give|send)\s+kudos\s+to\s+(?P<receiver>.+?)(?:\s+(?:for|because|about)\s+(?P<message>.+))?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:please\s+)?(?:kudos|shout\s*out|shoutout|props|congratulate|thank|thanks)\s+(?:to\s+)?(?P<receiver>.+?)(?:\s+(?:for|because|about)\s+(?P<message>.+))?$",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class TerminalCheckinIntent:
    """Parsed check-in request that should stay inside the terminal UI."""

    action: str


@dataclass(frozen=True)
class KudosIntent:
    """Parsed kudos request from terminal chat text."""

    receiver_query: str
    message: str
    receiver_kind: str = "auto"


@dataclass(frozen=True)
class TerminalActionIntent:
    """Parsed terminal-native action that should bypass general chat."""

    action: str
    args: tuple[str, ...] = ()


def is_checkins_intent(raw_value: str) -> bool:
    """Return True when the user is asking for the native check-ins flow."""
    value: str = _normalize(raw_value)
    return value in CHECKINS_INTENT_PHRASES or bool(_CHECKINS_QUESTION_RE.search(value))


def parse_terminal_checkin_intent(raw_value: str) -> TerminalCheckinIntent | None:
    """Parse check-in commands that chatbot platforms expose without a slash."""
    value: str = _normalize(raw_value).lstrip("/")
    if not value.startswith(("checkin", "check-in", "checkins", "check-ins")):
        return None

    parts: list[str] = value.split()
    if len(parts) == 1:
        return TerminalCheckinIntent(action="complete")

    action: str = parts[1]
    if action in {"list", "show", "complete", "start", "submit"}:
        return TerminalCheckinIntent(action="complete")
    if action in {"edit", "reset", "delete"}:
        return TerminalCheckinIntent(action=action)
    return None


def parse_kudos_intent(raw_value: str) -> KudosIntent | None:
    """Parse simple kudos requests that should use the native CLI flow."""
    value: str = raw_value.strip()
    if not value:
        return None
    for pattern in _KUDOS_PATTERNS:
        match = pattern.match(value)
        if match is None:
            continue
        receiver_query: str = _clean_receiver(match.group("receiver") or "")
        if not receiver_query:
            return None
        message: str = (match.group("message") or "").strip(" .")
        receiver_kind: str = "team" if _looks_like_team_receiver(receiver_query) else "auto"
        receiver_query = _clean_team_receiver(receiver_query)
        return KudosIntent(
            receiver_query=receiver_query,
            message=message,
            receiver_kind=receiver_kind,
        )
    return None


def parse_terminal_action_intent(raw_value: str) -> TerminalActionIntent | None:
    """Parse simple natural language requests for terminal-native flows."""
    value: str = _normalize(raw_value).lstrip("/")
    if value in {"forms", "form list", "list forms", "show forms", "my forms"}:
        return TerminalActionIntent(action="forms")
    if value.startswith(("submit form", "fill form", "fill out form")):
        return TerminalActionIntent(action="form_submit")
    if value.startswith(("form responses", "show form responses", "list form responses")):
        return TerminalActionIntent(action="form_responses")
    if value.startswith(("update form", "edit form response")):
        return TerminalActionIntent(action="form_update")
    if value.startswith(("transition form", "move form response")):
        return TerminalActionIntent(action="form_transition")
    if value.startswith(("delete form", "delete form response")):
        return TerminalActionIntent(action="form_delete")
    if value in {"users", "list users", "show users", "team members", "list members"}:
        return TerminalActionIntent(action="users")
    if value in {"teams", "list teams", "show teams"}:
        return TerminalActionIntent(action="teams")
    if value.startswith("team "):
        return TerminalActionIntent(action="team", args=(value.removeprefix("team ").strip(),))
    if value in {"dashboard", "open dashboard", "dailybot dashboard"}:
        return TerminalActionIntent(action="dashboard")
    if value in {"mood", "track mood", "record mood", "how am i feeling"}:
        return TerminalActionIntent(action="mood")
    if value.startswith(("timeoff", "time off", "pto")):
        return TerminalActionIntent(action="timeoff")
    return None


def matching_users(users: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Return active users whose name/email/handle matches the query."""
    normalized_query: str = _normalize(query).lstrip("@")
    if not normalized_query:
        return []

    query_parts: list[str] = [
        part for part in re.split(r"\s+", normalized_query) if part
    ]
    matches: list[dict[str, Any]] = []
    for user in users:
        if not user.get("is_active", True):
            continue
        haystack: str = _normalize(
            " ".join(
                str(user.get(key) or "")
                for key in (
                    "full_name",
                    "name",
                    "display_name",
                    "email",
                    "username",
                    "handle",
                )
            )
        ).lstrip("@")
        if normalized_query in haystack or all(part in haystack for part in query_parts):
            matches.append(user)
    return matches


def matching_teams(teams: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Return teams whose name/UUID matches the query."""
    normalized_query: str = _normalize(query).lstrip("@")
    if not normalized_query:
        return []
    matches: list[dict[str, Any]] = []
    for team in teams:
        haystack: str = _normalize(
            " ".join(str(team.get(key) or "") for key in ("name", "uuid", "id"))
        )
        if normalized_query in haystack:
            matches.append(team)
    return matches


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _clean_receiver(value: str) -> str:
    receiver: str = value.strip(" .")
    receiver = re.sub(r"^(?:@dailybot\s+)?", "", receiver, flags=re.IGNORECASE).strip()
    return receiver


def _looks_like_team_receiver(value: str) -> bool:
    return bool(re.search(r"\b(team|squad|group|department)\b", value, re.IGNORECASE))


def _clean_team_receiver(value: str) -> str:
    return re.sub(r"\b(team|squad|group|department)\b", "", value, flags=re.IGNORECASE).strip()
