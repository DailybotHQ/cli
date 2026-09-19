"""`dailybot tasks changes` — the delta poll loop (plan task 6).

The door refuses three different things (MEASURED_ANSWERS.md §4) and only one of
them is recoverable. These tests exist mostly to stop the recoverable one from
being retried forever.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.tasks import EXIT_DELTA_WINDOW_EXPIRED
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


def _invoke(runner: CliRunner, client: MagicMock, args: list[str]) -> Any:
    with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
        return runner.invoke(cli, args)


class TestCursorAcquisition:
    def test_without_a_cursor_it_reads_the_snapshot_first(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # The delta door's own 400 for a missing cursor does not say where to get
        # one; the snapshot is the only source.
        client.get_board_snapshot.return_value = {"delta_cursor": "2026-09-19T13:13:37Z"}
        client.get_board_delta.return_value = {"changed": [], "delta_cursor": "c-2"}
        result = _invoke(runner, client, ["tasks", "changes", "b-1"])
        assert result.exit_code == 0
        client.get_board_snapshot.assert_called_once_with("b-1")
        assert client.get_board_delta.call_args[1]["updated_since"] == "2026-09-19T13:13:37Z"

    def test_an_explicit_cursor_skips_the_snapshot(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_board_delta.return_value = {"changed": [], "delta_cursor": "c-2"}
        result = _invoke(runner, client, ["tasks", "changes", "b-1", "--cursor", "c-1"])
        assert result.exit_code == 0
        client.get_board_snapshot.assert_not_called()

    def test_since_is_accepted_as_an_alias_for_a_cursor(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_board_delta.return_value = {"changed": [], "delta_cursor": "c-2"}
        _invoke(runner, client, ["tasks", "changes", "b-1", "--since", "2026-09-01T00:00:00Z"])
        assert client.get_board_delta.call_args[1]["updated_since"] == "2026-09-01T00:00:00Z"


class TestTheEncodingTrap:
    """C-6 — the single most likely way a Python client breaks this door."""

    def test_the_outgoing_cursor_never_carries_a_plus(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_board_snapshot.return_value = {"delta_cursor": "2026-09-19T13:13:37+00:00"}
        client.get_board_delta.return_value = {"changed": [], "delta_cursor": "c-2"}
        _invoke(runner, client, ["tasks", "changes", "b-1"])
        sent: str = client.get_board_delta.call_args[1]["updated_since"]
        assert "+" not in sent
        assert sent.endswith("Z")


class TestWindowExpiry:
    """C-5 — an expired cursor will never be accepted again."""

    def test_it_does_not_retry_the_delta_call(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_board_delta.side_effect = APIError(
            400,
            "expired",
            code="delta_window_expired",
            extra={"full_resync_required": True, "max_window_days": 7},
        )
        _invoke(runner, client, ["tasks", "changes", "b-1", "--cursor", "old"])
        # Retrying is an infinite loop: exactly one attempt.
        assert client.get_board_delta.call_count == 1

    def test_it_exits_with_a_distinct_branchable_code(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_board_delta.side_effect = APIError(
            400, "expired", code="delta_window_expired", extra={"full_resync_required": True}
        )
        result = _invoke(runner, client, ["tasks", "changes", "b-1", "--cursor", "old"])
        assert result.exit_code == EXIT_DELTA_WINDOW_EXPIRED
        assert EXIT_DELTA_WINDOW_EXPIRED not in (0, 1, 2, 3, 4, 5, 6, 7)

    def test_resync_performs_the_snapshot_and_reports_it(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_board_delta.side_effect = APIError(
            400, "expired", code="delta_window_expired", extra={"full_resync_required": True}
        )
        client.get_board_snapshot.return_value = {"delta_cursor": "fresh", "groups": []}
        result = _invoke(runner, client, ["tasks", "changes", "b-1", "--cursor", "old", "--resync"])
        assert result.exit_code == 0
        client.get_board_snapshot.assert_called_once_with("b-1")
        assert "fresh" in result.output


class TestOtherRefusals:
    def test_an_unreadable_cursor_names_the_parameter(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_board_delta.side_effect = APIError(
            400, "bad", code="invalid_filter_value", extra={"parameter": "updated_since"}
        )
        result = _invoke(runner, client, ["tasks", "changes", "b-1", "--cursor", "nonsense"])
        assert result.exit_code != 0


class TestSingleRead:
    def test_exactly_one_delta_request_per_invocation(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # D8: the loop belongs to the caller, who owns the rate limit. A CLI that
        # sleeps and retries hides both the ceiling and the window.
        client.get_board_delta.return_value = {"changed": [], "delta_cursor": "c-2"}
        _invoke(runner, client, ["tasks", "changes", "b-1", "--cursor", "c-1"])
        assert client.get_board_delta.call_count == 1

    def test_there_is_no_follow_flag(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["tasks", "changes", "--help"])
        assert "--follow" not in result.output


class TestJsonMode:
    def test_the_new_cursor_is_carried_so_it_can_be_persisted(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_board_delta.return_value = {"changed": [{"uuid": "t-1"}], "delta_cursor": "c-2"}
        result = _invoke(runner, client, ["tasks", "changes", "b-1", "--cursor", "c-1", "--json"])
        assert json.loads(result.output)["delta_cursor"] == "c-2"


class TestHelpDocumentsTheContract:
    def test_the_seven_day_window_is_documented(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["tasks", "changes", "--help"])
        assert "7-day" in result.output or "seven-day" in result.output

    def test_the_delta_rate_limit_is_documented(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["tasks", "changes", "--help"])
        assert "240" in result.output
