"""Tests for the shared query-flags translator (Task 5)."""

from datetime import date

import pytest

from dailybot_cli.commands.query_options import (
    MAX_SEARCH_LEN,
    build_query_params,
    last_week_range,
)

REF = date(2026, 7, 8)  # a Wednesday — fixed reference for deterministic date math


def test_page_and_page_size_mapping() -> None:
    spec = build_query_params(page=2, page_size=25, reference=REF)
    assert spec.page == 2
    assert spec.page_size == 25


def test_page_size_clamped_to_max() -> None:
    spec = build_query_params(page_size=500, reference=REF)
    assert spec.page_size == 100


def test_search_maps_and_truncates() -> None:
    spec = build_query_params(search="retro", reference=REF)
    assert spec.params["search"] == "retro"
    long = "a" * 300
    spec2 = build_query_params(search=long, reference=REF)
    assert len(spec2.params["search"]) == MAX_SEARCH_LEN


def test_since_until_mapping() -> None:
    spec = build_query_params(since="2026-07-01", until="2026-07-31", reference=REF)
    assert spec.params["start_date"] == "2026-07-01"
    assert spec.params["end_date"] == "2026-07-31"


def test_date_sets_both_bounds() -> None:
    spec = build_query_params(on_date="2026-07-04", reference=REF)
    assert spec.params["start_date"] == "2026-07-04"
    assert spec.params["end_date"] == "2026-07-04"


def test_today_uses_reference() -> None:
    spec = build_query_params(today=True, reference=REF)
    assert spec.params["start_date"] == "2026-07-08"
    assert spec.params["end_date"] == "2026-07-08"


def test_last_week_is_previous_monday_to_sunday() -> None:
    # Week containing 2026-07-08 (Wed) starts Mon 2026-07-06; previous week is
    # Mon 2026-06-29 .. Sun 2026-07-05.
    start, end = last_week_range(REF)
    assert start == "2026-06-29"
    assert end == "2026-07-05"
    spec = build_query_params(last_week=True, reference=REF)
    assert spec.params["start_date"] == "2026-06-29"
    assert spec.params["end_date"] == "2026-07-05"


def test_date_precedence_since_beats_date_and_today() -> None:
    spec = build_query_params(since="2026-01-01", on_date="2026-07-04", today=True, reference=REF)
    assert spec.params["start_date"] == "2026-01-01"


def test_all_sets_fetch_all() -> None:
    spec = build_query_params(fetch_all=True, reference=REF)
    assert spec.fetch_all is True
    assert spec.limit is None


def test_limit_sets_limit() -> None:
    spec = build_query_params(limit=5, reference=REF)
    assert spec.limit == 5
    assert spec.fetch_all is False


def test_all_and_limit_conflict() -> None:
    with pytest.raises(ValueError):
        build_query_params(fetch_all=True, limit=5, reference=REF)


def test_no_flags_yields_empty_spec() -> None:
    spec = build_query_params(reference=REF)
    assert spec.params == {}
    assert spec.page is None and spec.page_size is None
    assert spec.fetch_all is False and spec.limit is None
