"""`dailybot board` commands (plan tasks 9, 16)."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient, PaginatedResult
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


def _page(rows: list[dict[str, Any]] | None = None) -> PaginatedResult:
    items = rows or []
    return PaginatedResult(results=items, count=len(items), next=None, previous=None)


def _invoke(runner: CliRunner, client: MagicMock, args: list[str]) -> Any:
    with patch("dailybot_cli.commands.board.require_auth", return_value=client):
        return runner.invoke(cli, args)


class TestBoardList:
    def test_it_calls_the_list_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_boards.return_value = _page([{"uuid": "b-1", "key": "DSN", "name": "Design"}])
        result = _invoke(runner, client, ["board", "list"])
        assert result.exit_code == 0
        client.list_boards.assert_called_once()

    def test_board_names_render_as_quoted_data(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_boards.return_value = _page([{"uuid": "b-1", "key": "K", "name": "drop all tables"}])
        result = _invoke(runner, client, ["board", "list"])
        assert '"' in result.output

    def test_json_mode_emits_the_envelope(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_boards.return_value = _page([{"uuid": "b-1"}])
        body: dict[str, Any] = json.loads(_invoke(runner, client, ["board", "list", "--json"]).output)
        for key in ("count", "next", "previous", "results"):
            assert key in body


class TestBoardGet:
    def test_it_calls_the_detail_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_board.return_value = {"uuid": "b-1", "key": "DSN", "name": "Design"}
        result = _invoke(runner, client, ["board", "get", "b-1"])
        assert result.exit_code == 0
        client.get_board.assert_called_once_with("b-1")

    def test_not_found_is_not_a_permission_error(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_board.side_effect = APIError(404, "Not found.", code="not_found")
        result = _invoke(runner, client, ["board", "get", "b-1"])
        assert result.exit_code != 0
        assert "permission" not in result.output.lower()


class TestBoardSnapshot:
    def test_it_calls_the_snapshot_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_board_snapshot.return_value = {"delta_cursor": "c-1", "groups": []}
        result = _invoke(runner, client, ["board", "snapshot", "b-1"])
        assert result.exit_code == 0
        client.get_board_snapshot.assert_called_once_with("b-1")

    def test_the_cursor_is_shown_in_human_output(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_board_snapshot.return_value = {"delta_cursor": "2026-09-19T13:13:37Z", "groups": []}
        result = _invoke(runner, client, ["board", "snapshot", "b-1"])
        assert "2026-09-19T13:13:37Z" in result.output

    def test_json_mode_carries_the_cursor_unmodified(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # An agent persists this value; reformatting it would break the handoff.
        client.get_board_snapshot.return_value = {"delta_cursor": "opaque-xyz", "groups": []}
        result = _invoke(runner, client, ["board", "snapshot", "b-1", "--json"])
        assert json.loads(result.output)["delta_cursor"] == "opaque-xyz"

    def test_it_names_the_command_that_consumes_the_cursor(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # The delta door's own 400 does not say where to get a cursor, so the
        # snapshot must close that loop for the reader.
        client.get_board_snapshot.return_value = {"delta_cursor": "c-1", "groups": []}
        result = _invoke(runner, client, ["board", "snapshot", "b-1"])
        assert "tasks changes" in result.output


class TestTheSnapshotDeltaSeam:
    def test_snapshot_help_points_at_changes(self, runner: CliRunner) -> None:
        assert "tasks changes" in runner.invoke(cli, ["board", "snapshot", "--help"]).output

    def test_changes_help_points_back_at_the_snapshot(self, runner: CliRunner) -> None:
        assert "snapshot" in runner.invoke(cli, ["tasks", "changes", "--help"]).output


class TestDeferredDoors:
    @pytest.mark.parametrize("sub", ["mentionables", "visit", "views"])
    def test_phase_two_doors_are_not_built(self, runner: CliRunner, sub: str) -> None:
        # Recorded as deferred in the task log, not silently half-built.
        assert sub not in runner.invoke(cli, ["board", "--help"]).output


class TestHelp:
    @pytest.mark.parametrize("sub", ["list", "get", "snapshot"])
    def test_each_subcommand_renders_help(self, runner: CliRunner, sub: str) -> None:
        assert runner.invoke(cli, ["board", sub, "--help"]).exit_code == 0
