"""Tests for resolve_fetch_all — the guard that decides whether a list command
walks every page or returns the single slice the user asked for."""

from dailybot_cli.commands.query_options import QuerySpec, resolve_fetch_all


def test_no_paging_flags_fetches_everything() -> None:
    assert resolve_fetch_all(QuerySpec()) is True


def test_explicit_all_flag_fetches_everything() -> None:
    assert resolve_fetch_all(QuerySpec(fetch_all=True)) is True


def test_all_flag_wins_over_page_size() -> None:
    assert resolve_fetch_all(QuerySpec(fetch_all=True, page_size=3)) is True


def test_page_bounds_the_fetch() -> None:
    assert resolve_fetch_all(QuerySpec(page=2)) is False


def test_limit_bounds_the_fetch() -> None:
    assert resolve_fetch_all(QuerySpec(limit=5)) is False


def test_page_size_alone_bounds_the_fetch() -> None:
    """Regression: --page-size 3 used to walk all pages 3 rows at a time."""
    assert resolve_fetch_all(QuerySpec(page_size=3)) is False


def test_page_and_page_size_bounds_the_fetch() -> None:
    assert resolve_fetch_all(QuerySpec(page=1, page_size=3)) is False
