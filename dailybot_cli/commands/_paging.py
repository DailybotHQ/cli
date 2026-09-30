"""Paging helpers shared by the Tasks command modules (``tasks`` and ``tasks_settings``)."""

from typing import Any

from dailybot_cli.api_client import PaginatedResult
from dailybot_cli.commands.query_options import build_query_params, resolve_fetch_all


def envelope(result: PaginatedResult) -> dict[str, Any]:
    """The `{count,next,previous,results}` shape an agent parses (plus any envelope extras)."""
    return {
        "count": result.count,
        "next": result.next,
        "previous": result.previous,
        "results": result.results,
        **result.extra,
    }


def page_kwargs(*, walk_pages: bool = False, **flags: Any) -> dict[str, Any]:
    """Translate the shared query flags into client kwargs.

    ``walk_pages`` follows the decorator the command stacked, and the two must
    agree or the help lies. A ``query_options`` command declares ``--all`` and
    therefore keeps the repo-wide default that no paging flag means every page; a
    ``paging_options`` / ``date_options`` command declares no ``--all``, states in
    its help that paging is one page per call, and stays bounded.
    """
    spec = build_query_params(**flags)
    return {
        "params": spec.params or None,
        "page": spec.page,
        "page_size": spec.page_size,
        "fetch_all": resolve_fetch_all(spec) if walk_pages else spec.fetch_all,
        "limit": spec.limit,
    }
