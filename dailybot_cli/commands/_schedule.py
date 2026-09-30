"""Weekday, time-of-day and timezone handling for the notification, report and briefing commands.

On the wire weekdays are ISO integers 1..7 (Monday = 1), a time is ``HH:MM`` (24h) and a timezone is an
IANA name. On the command line weekdays are lowercase three-letter names, so ``--weekdays mon,tue`` and
``--weekdays mon --weekdays fri`` both work and the number ``1`` is never accepted (it would be
ambiguous with "the first of the list").
"""

import re
from collections.abc import Iterable, Sequence
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import click

WEEKDAY_NAMES: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_NUMBERS: dict[str, int] = {
    name: number for number, name in enumerate(WEEKDAY_NAMES, start=1)
}
WEEKLY_KINDS: tuple[str, ...] = ("week_start", "week_end")
DAILY_KIND: str = "daily"
REPORT_KINDS: tuple[str, ...] = (DAILY_KIND, *WEEKLY_KINDS)
TIME_PATTERN: re.Pattern[str] = re.compile(r"^(\d{1,2}):(\d{2})$")
MAX_HOUR: int = 23
MAX_MINUTE: int = 59
WEEKDAYS_HELP: str = (
    "Days of the week: mon,tue,wed,thu,fri,sat,sun (comma list or repeat the flag)."
)
TIME_HELP: str = "Time of day, 24-hour HH:MM, in --timezone."
TIMEZONE_HELP: str = "IANA timezone such as America/Bogota. Omit it to use yours."


def parse_weekdays(values: Sequence[str] | str) -> list[int]:
    """Turn ``('mon,tue', 'fri')`` into ``[1, 2, 5]`` (sorted, no repeats); ``ValueError`` otherwise."""
    raw_values: Sequence[str] = (values,) if isinstance(values, str) else values
    numbers: set[int] = set()
    for raw in raw_values:
        for part in raw.split(","):
            name: str = part.strip().lower()
            if name not in WEEKDAY_NUMBERS:
                raise ValueError(
                    f"Not a weekday: {part!r}. Use {', '.join(WEEKDAY_NAMES)} "
                    "(a comma list, or repeat the flag)."
                )
            numbers.add(WEEKDAY_NUMBERS[name])
    return sorted(numbers)


def format_weekdays(days: Iterable[int]) -> str:
    """``[5, 1, 3]`` -> ``'mon,wed,fri'``; a value outside 1..7 is shown as is, never dropped."""
    ordered: list[int] = sorted(set(days))
    return ",".join(
        WEEKDAY_NAMES[d - 1] if 1 <= d <= len(WEEKDAY_NAMES) else str(d) for d in ordered
    )


def weekdays_callback(
    _ctx: click.Context, param: click.Parameter, value: tuple[str, ...]
) -> list[int] | None:
    """Click callback: ``None`` when the flag was not passed, else the parsed ISO numbers."""
    if not value:
        return None
    try:
        return parse_weekdays(value)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param=param) from exc


def require_single_weekday_for_weekly(kind: str, days: Sequence[int]) -> None:
    """A weekly report runs on exactly one weekday; a daily one on at least one."""
    if kind in WEEKLY_KINDS and len(days) != 1:
        raise ValueError(f"A {kind} report runs on exactly one weekday; got {len(days)}.")
    if kind == DAILY_KIND and not days:
        raise ValueError("A daily report needs at least one weekday.")


class TimeOfDay(click.ParamType):
    """``HH:MM`` in 24 hours; ``9:05`` is accepted and sent as ``09:05``."""

    name = "HH:MM"

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> str:
        match: re.Match[str] | None = TIME_PATTERN.match(str(value))
        if match is None or int(match.group(1)) > MAX_HOUR or int(match.group(2)) > MAX_MINUTE:
            self.fail(
                f"{value!r} is not a time of day; use 24-hour HH:MM, for example 09:30.", param, ctx
            )
        return f"{int(match.group(1)):02d}:{match.group(2)}"


def _zone_database_present() -> bool:
    """False on a system with no IANA database: then only the server can judge a zone name."""
    return bool(available_timezones())


class IanaTimezone(click.ParamType):
    """An IANA zone name, checked locally when the machine has the zone database."""

    name = "TIMEZONE"

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> str:
        text: str = str(value)
        if not _zone_database_present():
            return text
        try:
            if not text or text != text.strip():
                raise ValueError(text)
            ZoneInfo(text)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            self.fail(
                f"{text!r} is not an IANA timezone; use a name such as America/Bogota.", param, ctx
            )
        return text


TIME_OF_DAY: TimeOfDay = TimeOfDay()
IANA_TZ: IanaTimezone = IanaTimezone()
