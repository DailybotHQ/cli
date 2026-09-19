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


# ---------------------------------------------------------------------------
# Container writes (plan task 16)
# ---------------------------------------------------------------------------


def _invoke_auth(runner: CliRunner, client: MagicMock, args: list[str], auth: str) -> Any:
    with (
        patch("dailybot_cli.commands.board.require_auth", return_value=client),
        patch("dailybot_cli.commands.board.get_agent_auth", return_value=auth),
    ):
        return runner.invoke(cli, args)


class TestContainerCreateNeedsAPerson:
    """C-8 — measured: an ADMIN_ORG owner is refused too."""

    def test_an_api_key_is_refused_before_the_request(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke_auth(runner, client, ["board", "create", "--name", "Design"], "api_key")
        assert result.exit_code == 3
        client.create_board.assert_not_called()

    def test_the_message_blames_the_credential_kind(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke_auth(runner, client, ["board", "create", "--name", "x"], "api_key")
        # Rich wraps at the terminal width, so a phrase can straddle a newline.
        # Collapse whitespace before asserting on wording.
        out: str = " ".join(result.output.lower().split())
        assert "api key" in out
        assert "dailybot login" in out

    def test_it_does_not_tell_an_org_admin_to_become_an_admin(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # Task 1 measured an ADMIN_ORG owner refused identically. "You must be an
        # admin" would send them hunting for a setting that cannot exist.
        result = _invoke_auth(runner, client, ["board", "create", "--name", "x"], "api_key")
        out: str = " ".join(result.output.lower().split())
        assert "must be an admin" not in out
        assert "be an org admin" not in out


class TestGuestIsDistinctFromScope:
    def test_guest_not_allowed_talks_about_role(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.create_board.side_effect = APIError(403, "guest", code="guest_not_allowed")
        result = _invoke_auth(runner, client, ["board", "create", "--name", "x"], "bearer")
        assert "role" in " ".join(result.output.lower().split())


_BOARD_PREVIEW: dict[str, Any] = {
    "operation": "board.archive",
    "reversible": True,
    "restore_path": "/v1/tasks/boards/b-1/restore/",
    "consequence": "Archives the board and cascade-archives 12 live tasks.",
    "affects": {"boards": 1, "tasks_cascaded": 12},
    "_idempotency_replayed": False,
}


class TestBoardArchivePreviews:

    def test_dry_run_mutates_nothing(self, runner: CliRunner, client: MagicMock) -> None:
        client.archive_board.return_value = _BOARD_PREVIEW
        result = _invoke(runner, client, ["board", "archive", "b-1", "--dry-run"])
        assert result.exit_code == 0
        assert client.archive_board.call_count == 1

    def test_the_cascade_count_is_shown(self, runner: CliRunner, client: MagicMock) -> None:
        client.archive_board.return_value = _BOARD_PREVIEW
        result = _invoke(runner, client, ["board", "archive", "b-1", "--dry-run"])
        assert "12" in result.output

    def test_it_warns_that_restoring_does_not_restore_cascaded_tasks(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.archive_board.side_effect = [_BOARD_PREVIEW, {"_idempotency_replayed": False}]
        result = _invoke(runner, client, ["board", "archive", "b-1", "--yes"])
        out: str = " ".join(result.output.lower().split())
        assert "not restore" in out or "stay archived" in out

    def test_a_failed_preview_aborts(self, runner: CliRunner, client: MagicMock) -> None:
        client.archive_board.side_effect = APIError(500, "boom", code="server_error")
        result = _invoke(runner, client, ["board", "archive", "b-1", "--yes"])
        assert result.exit_code != 0
        assert client.archive_board.call_count == 1


class TestBoardLimitIsSurfaced:
    def test_the_entitlement_refusal_is_explained(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.create_board.side_effect = APIError(
            402, "limit", code="task_boards_limit_reached"
        )
        result = _invoke_auth(runner, client, ["board", "create", "--name", "x"], "bearer")
        assert result.exit_code != 0
        assert "limit" in " ".join(result.output.lower().split())
