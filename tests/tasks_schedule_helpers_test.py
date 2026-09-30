"""Schedule and channel helpers shared by the tasks notification, route, report and briefing commands."""

from typing import Any
from unittest.mock import MagicMock, patch

import click
import pytest

from dailybot_cli.api_client import PaginatedResult
from dailybot_cli.commands._channels import resolve_channel
from dailybot_cli.commands._schedule import (
    IANA_TZ,
    TIME_OF_DAY,
    WEEKLY_KINDS,
    format_weekdays,
    parse_weekdays,
    require_single_weekday_for_weekly,
)


class TestParseWeekdays:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (("mon,tue",), [1, 2]),
            (("Mon", "FRI"), [1, 5]),
            (("fri,mon,mon",), [1, 5]),
            ((" mon , tue ",), [1, 2]),
            (("sun",), [7]),
            (("mon,tue,wed,thu,fri,sat,sun",), [1, 2, 3, 4, 5, 6, 7]),
        ],
    )
    def test_names_repeats_and_commas_become_sorted_unique_iso_ints(
        self, raw: tuple[str, ...], expected: list[int]
    ) -> None:
        assert parse_weekdays(raw) == expected

    @pytest.mark.parametrize("bad", [("funday",), ("8",), ("0",), ("mon,,",), ("",), ("monday",)])
    def test_anything_else_is_refused_naming_the_valid_values(self, bad: tuple[str, ...]) -> None:
        with pytest.raises(ValueError) as raised:
            parse_weekdays(bad)
        assert "mon" in str(raised.value)

    def test_iso_numbers_are_not_accepted_on_the_command_line(self) -> None:
        # The wire uses 1..7, the command line uses names; accepting both would make "1" ambiguous.
        with pytest.raises(ValueError):
            parse_weekdays(("1",))

    def test_empty_input_is_an_empty_list_not_an_error(self) -> None:
        assert parse_weekdays(()) == []


class TestFormatWeekdays:
    def test_ints_become_names_in_week_order(self) -> None:
        assert format_weekdays([5, 1, 3]) == "mon,wed,fri"

    def test_out_of_range_values_are_shown_not_hidden(self) -> None:
        assert "9" in format_weekdays([1, 9])

    def test_empty(self) -> None:
        assert format_weekdays([]) == ""


class TestWeeklyKinds:
    def test_constants(self) -> None:
        assert set(WEEKLY_KINDS) == {"week_start", "week_end"}

    @pytest.mark.parametrize("kind", ["week_start", "week_end"])
    def test_a_weekly_kind_takes_exactly_one_weekday(self, kind: str) -> None:
        require_single_weekday_for_weekly(kind, [5])
        for days in ([], [1, 5]):
            with pytest.raises(ValueError):
                require_single_weekday_for_weekly(kind, days)

    def test_a_daily_kind_takes_any_non_empty_set(self) -> None:
        require_single_weekday_for_weekly("daily", [1, 2, 3])
        with pytest.raises(ValueError):
            require_single_weekday_for_weekly("daily", [])


class TestTimeOfDay:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("09:00", "09:00"), ("9:05", "09:05"), ("23:59", "23:59"), ("00:00", "00:00")],
    )
    def test_valid_times_are_normalised(self, raw: str, expected: str) -> None:
        assert TIME_OF_DAY.convert(raw, None, None) == expected

    @pytest.mark.parametrize("bad", ["24:00", "9am", "09:60", "9", "", "09:00:00", "-1:00"])
    def test_invalid_times_are_refused_locally(self, bad: str) -> None:
        with pytest.raises(click.BadParameter):
            TIME_OF_DAY.convert(bad, None, None)


class TestIanaTimezone:
    def test_a_real_zone_passes_unchanged(self) -> None:
        assert IANA_TZ.convert("America/Bogota", None, None) == "America/Bogota"
        assert IANA_TZ.convert("UTC", None, None) == "UTC"

    @pytest.mark.parametrize(
        "bad", ["Mars/Base", "", "Bogota", "../etc/passwd", "America/Bogota\n"]
    )
    def test_an_unknown_zone_is_refused_locally(self, bad: str) -> None:
        with pytest.raises(click.BadParameter):
            IANA_TZ.convert(bad, None, None)

    def test_without_a_zone_database_the_server_decides(self) -> None:
        with patch("dailybot_cli.commands._schedule._zone_database_present", return_value=False):
            assert IANA_TZ.convert("Mars/Base", None, None) == "Mars/Base"


def _page(rows: list[dict[str, Any]]) -> PaginatedResult:
    return PaginatedResult(results=rows, count=len(rows), next=None, previous=None)


CHANNELS: list[dict[str, str]] = [
    {"external_id": "C0000000A", "name": "eng", "type": "channel"},
    {"external_id": "C0000000B", "name": "eng-alerts", "type": "channel"},
    {"external_id": "C0000000C", "name": "Design", "type": "channel"},
    {"external_id": "G0000000D", "name": "leads", "type": "private_channel"},
]


@pytest.fixture
def client() -> MagicMock:
    # No spec: `search_channels` lands on the client in the next task; the helper only needs the call.
    mock: MagicMock = MagicMock()
    mock.search_channels.return_value = _page(CHANNELS)
    return mock


class TestResolveChannel:
    def test_an_external_id_is_matched_exactly(self, client: MagicMock) -> None:
        assert resolve_channel(client, "C0000000B")["name"] == "eng-alerts"

    def test_a_name_matches_exactly_case_insensitively(self, client: MagicMock) -> None:
        assert resolve_channel(client, "DESIGN")["external_id"] == "C0000000C"

    def test_an_exact_name_beats_a_longer_substring(self, client: MagicMock) -> None:
        assert resolve_channel(client, "eng")["external_id"] == "C0000000A"

    def test_a_unique_substring_resolves(self, client: MagicMock) -> None:
        assert resolve_channel(client, "alerts")["external_id"] == "C0000000B"

    def test_an_ambiguous_substring_lists_the_candidates(self, client: MagicMock) -> None:
        with pytest.raises(click.UsageError) as raised:
            resolve_channel(client, "e")
        message: str = raised.value.message
        assert "eng" in message and "Design" in message and "C0000000A" in message

    def test_a_missing_channel_says_so_and_how_to_list(self, client: MagicMock) -> None:
        with pytest.raises(click.UsageError) as raised:
            resolve_channel(client, "nope")
        assert "tasks channels search" in raised.value.message

    def test_public_only_asks_the_server_for_public_channels(self, client: MagicMock) -> None:
        resolve_channel(client, "eng", public_only=True)
        assert client.search_channels.call_args.kwargs["channel_type"] == "channel"

    def test_the_default_does_not_filter_by_type(self, client: MagicMock) -> None:
        resolve_channel(client, "eng")
        assert client.search_channels.call_args.kwargs.get("channel_type") is None

    def test_a_private_channel_the_caller_cannot_see_is_just_missing(
        self, client: MagicMock
    ) -> None:
        client.search_channels.return_value = _page(CHANNELS[:3])
        with pytest.raises(click.UsageError):
            resolve_channel(client, "leads")

    def test_the_result_is_the_reference_the_api_takes(self, client: MagicMock) -> None:
        found: dict[str, str] = resolve_channel(client, "eng")
        assert found == {"external_id": "C0000000A", "name": "eng", "type": "channel"}

    def test_channel_names_are_shown_as_quoted_data(self, client: MagicMock) -> None:
        client.search_channels.return_value = _page(
            [
                {"external_id": "C1", "name": "[bold red]x[/]", "type": "channel"},
                {"external_id": "C2", "name": "[bold red]y[/]", "type": "channel"},
            ]
        )
        with pytest.raises(click.UsageError) as raised:
            resolve_channel(client, "bold")
        assert '"' in raised.value.message
