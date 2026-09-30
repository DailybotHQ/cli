"""Reference-argument callbacks shared by the Tasks settings commands."""

import re

import click

UUID_RE: re.Pattern[str] = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def require_uuid(_ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    """Refuse a reference that is not a uuid before any request leaves (routes and reports have no key)."""
    if value is not None and not UUID_RE.match(value):
        raise click.BadParameter("must be a uuid (see the list command).", param=param)
    return value


def require_uuids(
    _ctx: click.Context, param: click.Parameter, value: tuple[str, ...]
) -> tuple[str, ...]:
    """The same check for a repeatable option."""
    for item in value:
        if not UUID_RE.match(item):
            raise click.BadParameter(f"{item!r} is not a uuid.", param=param)
    return value
