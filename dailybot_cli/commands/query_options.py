"""Reusable Click flags + pure translator for pagination / search / date-range.

Any list-style command opts in with a single ``@query_options`` line and passes
the parsed values through ``build_query_params`` to get the query-param dict plus
iteration knobs the shared paginated-GET helper (``api_client._paginated_get``)
consumes. This module is Click-side only: no HTTP, no rendering.
"""

import datetime as _datetime
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import click

from dailybot_cli.api_client import MAX_PAGE_SIZE

MAX_SEARCH_LEN: int = 256  # server rejects longer; truncate client-side first


@dataclass
class QuerySpec:
    """Translated query options: params dict + iteration knobs for _paginated_get."""

    params: dict[str, Any] = field(default_factory=dict)
    page: int | None = None
    page_size: int | None = None
    fetch_all: bool = False
    limit: int | None = None


def resolve_fetch_all(spec: QuerySpec) -> bool:
    """Decide whether a list command should follow ``next`` across every page.

    ``--all`` always wins. Otherwise, any explicit paging flag (``--page``,
    ``--page-size``, ``--limit``) means the caller asked for a bounded slice, so
    only that slice is fetched. With no paging flag at all we fetch everything,
    preserving the historical default of these commands.

    ``--page-size`` must be counted here: it sizes the *response*, not just the
    internal chunk. Omitting it made ``--page-size 3`` silently walk all pages
    three rows at a time and return the full list.
    """
    if spec.fetch_all:
        return True
    return spec.page is None and spec.page_size is None and spec.limit is None


def last_week_range(reference: date) -> tuple[str, str]:
    """Return (Monday, Sunday) ISO strings for the week before ``reference``."""
    this_monday: date = reference - timedelta(days=reference.weekday())
    prev_monday: date = this_monday - timedelta(days=7)
    prev_sunday: date = prev_monday + timedelta(days=6)
    return prev_monday.isoformat(), prev_sunday.isoformat()


def build_query_params(
    *,
    page: int | None = None,
    page_size: int | None = None,
    fetch_all: bool = False,
    limit: int | None = None,
    search: str | None = None,
    since: str | None = None,
    until: str | None = None,
    on_date: str | None = None,
    last_week: bool = False,
    today: bool = False,
    reference: date | None = None,
) -> QuerySpec:
    """Translate parsed query flags into a QuerySpec (pure, deterministic).

    Date-flag precedence (mutually exclusive): explicit ``since``/``until`` >
    ``--date`` > ``--today`` > ``--last-week``. ``reference`` (default
    ``date.today()``) makes the relative helpers testable. ``--all`` and
    ``--limit`` cannot be combined.
    """
    if fetch_all and limit is not None:
        raise ValueError("--all and --limit cannot be combined; choose one.")

    ref: date = reference if reference is not None else _datetime.date.today()
    params: dict[str, Any] = {}

    if search is not None:
        params["search"] = search[:MAX_SEARCH_LEN]

    start: str | None = None
    end: str | None = None
    if since is not None or until is not None:
        start, end = since, until
    elif on_date is not None:
        start = end = on_date
    elif today:
        start = end = ref.isoformat()
    elif last_week:
        start, end = last_week_range(ref)
    if start is not None:
        params["start_date"] = start
    if end is not None:
        params["end_date"] = end

    clamped_page_size: int | None = page_size
    if clamped_page_size is not None:
        clamped_page_size = max(1, min(clamped_page_size, MAX_PAGE_SIZE))

    return QuerySpec(
        params=params,
        page=page,
        page_size=clamped_page_size,
        fetch_all=fetch_all,
        limit=limit,
    )


def query_options(func: Callable[..., Any]) -> Callable[..., Any]:
    """Stack the shared pagination / search / date-range flags onto a command."""
    options: list[Callable[..., Any]] = [
        click.option("--page", "-P", type=int, default=None, help="Page number to fetch."),
        click.option(
            "--page-size",
            "-z",
            "page_size",
            type=int,
            default=None,
            help="Items per page (max 200).",
        ),
        click.option(
            "--all",
            "-a",
            "fetch_all",
            is_flag=True,
            default=False,
            help="Fetch every page (iterate until the end).",
        ),
        click.option(
            "--limit",
            "-l",
            type=int,
            default=None,
            help="Stop after collecting N items.",
        ),
        click.option(
            "--search",
            "--grep",
            "-s",
            "search",
            default=None,
            help="Filter by text (max 256 chars; truncated).",
        ),
        click.option("--since", "-S", "since", default=None, help="Start date (YYYY-MM-DD)."),
        click.option("--until", "-U", "until", default=None, help="End date (YYYY-MM-DD)."),
        click.option(
            "--date",
            "-D",
            "on_date",
            default=None,
            help="Single day (YYYY-MM-DD): sets start and end.",
        ),
        click.option(
            "--last-week",
            "last_week",
            is_flag=True,
            default=False,
            help="Previous Monday-Sunday week.",
        ),
        click.option("--today", "today", is_flag=True, default=False, help="Today only."),
    ]
    for option in reversed(options):
        func = option(func)
    return func
