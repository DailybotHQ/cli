"""Parsing and validation helpers for forms & check-ins authoring commands.

These helpers do **shape/format validation only**. Authorization (who may create
or edit what) is enforced server-side by role — the CLI never approximates it.
"""

import json
import re
from pathlib import Path
from typing import Any

import click

from dailybot_cli.api_client import DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    resolve_team_by_name_or_uuid,
    resolve_user_by_name_or_uuid,
)
from dailybot_cli.display import print_error

# Question types accepted by the server. Anything else is rejected with 400.
VALID_QUESTION_TYPES: tuple[str, ...] = ("text", "multiple_choice", "boolean", "numeric")
# Server-side ceiling; mirrored here so the CLI fails fast on obviously-too-many.
MAX_QUESTIONS: int = 50
# Schedule validation: ISO weekday ints (0=Sunday .. 6=Saturday) and HH:MM time.
MIN_WEEKDAY: int = 0
MAX_WEEKDAY: int = 6
_TIME_PATTERN: re.Pattern[str] = re.compile(r"^\d{2}:\d{2}$")


class AuthoringError(click.ClickException):
    """A user-facing validation error for authoring input.

    Rendered through ``display.print_error`` (stderr) and exits non-zero, so
    command callbacks don't need to wrap helper calls in try/except.
    """

    def show(self, file: Any = None) -> None:
        print_error(self.message)


def parse_options(raw: str | None) -> list[str] | None:
    """Split a comma-separated ``--options`` string into a trimmed list."""
    if raw is None:
        return None
    options: list[str] = [part.strip() for part in raw.split(",") if part.strip()]
    return options or None


def build_question(
    question_type: str,
    question: str,
    *,
    options: list[str] | None = None,
    required: bool = True,
) -> dict[str, Any]:
    """Build a validated question payload (explicit ``question_type``/``question``).

    Enforces the type whitelist, that ``multiple_choice`` carries options, that
    other types do not, and that the question text is non-empty.
    """
    qtype: str = question_type.strip().lower()
    if qtype not in VALID_QUESTION_TYPES:
        raise AuthoringError(
            f"Invalid question type '{question_type}'. "
            f"Choose from: {', '.join(VALID_QUESTION_TYPES)}."
        )
    text: str = question.strip()
    if not text:
        raise AuthoringError("Question text is required.")

    payload: dict[str, Any] = {
        "question_type": qtype,
        "question": text,
        "required": required,
    }
    if qtype == "multiple_choice":
        if not options:
            raise AuthoringError(
                "Multiple-choice questions require at least one option (use --options)."
            )
        payload["options"] = options
    elif options:
        raise AuthoringError(f"'{qtype}' questions do not take options.")
    return payload


def build_question_edit_fields(
    question: str | None,
    question_type: str | None,
    options: str | None,
    required: bool | None,
) -> dict[str, Any]:
    """Build a partial question-update payload from provided edit flags.

    Only shape checks run here; the server does full validation. ``build_question``
    isn't reused because edits are partial (no required question/type pairing).
    """
    fields: dict[str, Any] = {}
    if question is not None:
        fields["question"] = question
    if question_type is not None:
        fields["question_type"] = question_type
    if options is not None:
        fields["options"] = parse_options(options) or []
    if required is not None:
        fields["required"] = required
    return fields


def parse_questions_file(path: str) -> list[dict[str, Any]]:
    """Load and validate a JSON array of question objects from ``path``.

    Accepts both field conventions (``question_type``/``question`` or
    ``type``/``label``) and enforces ``MAX_QUESTIONS``.
    """
    try:
        raw: str = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise AuthoringError(f"Cannot read questions file '{path}': {exc}") from exc
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthoringError(f"Questions file '{path}' is not valid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise AuthoringError("Questions file must be a JSON array of question objects.")
    if len(data) > MAX_QUESTIONS:
        raise AuthoringError(f"Too many questions ({len(data)}); the limit is {MAX_QUESTIONS}.")

    questions: list[dict[str, Any]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise AuthoringError(f"Question #{index + 1} must be an object.")
        qtype: str = str(item.get("question_type") or item.get("type") or "")
        qtext: str = str(item.get("question") or item.get("label") or "")
        raw_options: Any = item.get("options")
        options: list[str] | None = (
            [str(option) for option in raw_options] if isinstance(raw_options, list) else None
        )
        required: bool = bool(item.get("required", True))
        questions.append(build_question(qtype, qtext, options=options, required=required))
    return questions


def _validate_schedule_dict(schedule: dict[str, Any]) -> dict[str, Any]:
    """Validate the shape of a schedule dict (``days``, ``time``); leave tz to server."""
    validated: dict[str, Any] = dict(schedule)
    if "days" in validated:
        days: Any = validated["days"]
        if not isinstance(days, list) or not all(
            isinstance(day, int) and MIN_WEEKDAY <= day <= MAX_WEEKDAY for day in days
        ):
            raise AuthoringError(
                "Schedule days must be a list of integers 0-6 (0=Sunday .. 6=Saturday)."
            )
    if "time" in validated and not _TIME_PATTERN.match(str(validated["time"])):
        raise AuthoringError("Schedule time must be in HH:MM format (e.g. 09:00).")
    return validated


def parse_schedule(
    *,
    days: str | None = None,
    time: str | None = None,
    timezone: str | None = None,
    schedule_file: str | None = None,
) -> dict[str, Any] | None:
    """Build a schedule dict from a JSON file or individual flags.

    Returns ``None`` when nothing is provided (so the field is omitted). The
    timezone is not validated locally — the server returns ``invalid_timezone``.
    """
    if schedule_file:
        try:
            raw: str = Path(schedule_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise AuthoringError(f"Cannot read schedule file '{schedule_file}': {exc}") from exc
        try:
            data: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthoringError(
                f"Schedule file '{schedule_file}' is not valid JSON: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise AuthoringError("Schedule file must be a JSON object.")
        return _validate_schedule_dict(data)

    schedule: dict[str, Any] = {}
    if days is not None:
        parsed_days: list[int] = []
        for part in days.split(","):
            token: str = part.strip()
            if not token:
                continue
            try:
                parsed_days.append(int(token))
            except ValueError as exc:
                raise AuthoringError(
                    "Schedule days must be comma-separated integers 0-6 (0=Sunday .. 6=Saturday)."
                ) from exc
        schedule["days"] = parsed_days
    if time is not None:
        schedule["time"] = time
    if timezone is not None:
        schedule["timezone"] = timezone

    if not schedule:
        return None
    return _validate_schedule_dict(schedule)


def parse_participants(
    users: tuple[str, ...],
    teams: tuple[str, ...],
    client: DailyBotClient,
) -> dict[str, Any]:
    """Resolve name-or-UUID participants into ``{user_uuids, team_uuids}``.

    Empty groups are omitted. Resolution reuses the shared resolver helpers, so
    ambiguous or unknown names raise the same friendly errors as other commands.
    """
    participants: dict[str, Any] = {}
    if users:
        directory: list[dict[str, Any]] = client.list_users()
        participants["user_uuids"] = [
            resolve_user_by_name_or_uuid(directory, identifier)[0] for identifier in users
        ]
    if teams:
        team_directory: list[dict[str, Any]] = client.list_teams()
        participants["team_uuids"] = [
            resolve_team_by_name_or_uuid(team_directory, identifier)[0] for identifier in teams
        ]
    return participants
