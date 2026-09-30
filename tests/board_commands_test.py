"""`dailybot board` commands (plan tasks 9, 16)."""

import json
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient, PaginatedResult
from dailybot_cli.display import console as display_console
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
    # A signed-in person: board structure changes are `tasks:admin` doors, which
    # refuse an organization API key before any request.
    with (
        patch("dailybot_cli.commands.board.require_auth", return_value=client),
        patch("dailybot_cli.commands.board.get_person_token", return_value="tok", create=True),
    ):
        return runner.invoke(cli, args)


class TestBoardList:
    def test_it_calls_the_list_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_boards.return_value = _page([{"uuid": "b-1", "key": "DSN", "name": "Design"}])
        result = _invoke(runner, client, ["plan", "board", "list"])
        assert result.exit_code == 0
        client.list_boards.assert_called_once()

    def test_board_names_render_as_quoted_data(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_boards.return_value = _page(
            [{"uuid": "b-1", "key": "K", "name": "drop all tables"}]
        )
        result = _invoke(runner, client, ["plan", "board", "list"])
        assert '"' in result.output

    def test_json_mode_emits_the_envelope(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_boards.return_value = _page([{"uuid": "b-1"}])
        body: dict[str, Any] = json.loads(
            _invoke(runner, client, ["plan", "board", "list", "--json"]).output
        )
        for key in ("count", "next", "previous", "results"):
            assert key in body


class TestBoardGet:
    def test_it_calls_the_detail_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_board.return_value = {"uuid": "b-1", "key": "DSN", "name": "Design"}
        result = _invoke(runner, client, ["plan", "board", "get", "b-1"])
        assert result.exit_code == 0
        client.get_board.assert_called_once_with("b-1")

    def test_not_found_is_not_a_permission_error(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_board.side_effect = APIError(404, "Not found.", code="not_found")
        result = _invoke(runner, client, ["plan", "board", "get", "b-1"])
        assert result.exit_code != 0
        assert "permission" not in result.output.lower()


class TestBoardSnapshot:
    def test_it_calls_the_snapshot_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_board_snapshot.return_value = {"delta_cursor": "c-1", "groups": []}
        result = _invoke(runner, client, ["plan", "board", "snapshot", "b-1"])
        assert result.exit_code == 0
        client.get_board_snapshot.assert_called_once_with("b-1")

    def test_the_cursor_is_shown_in_human_output(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_board_snapshot.return_value = {
            "delta_cursor": "2026-09-19T13:13:37Z",
            "groups": [],
        }
        result = _invoke(runner, client, ["plan", "board", "snapshot", "b-1"])
        assert "2026-09-19T13:13:37Z" in result.output

    def test_json_mode_carries_the_cursor_unmodified(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # An agent persists this value; reformatting it would break the handoff.
        client.get_board_snapshot.return_value = {"delta_cursor": "opaque-xyz", "groups": []}
        result = _invoke(runner, client, ["plan", "board", "snapshot", "b-1", "--json"])
        assert json.loads(result.output)["delta_cursor"] == "opaque-xyz"

    def test_it_names_the_command_that_consumes_the_cursor(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # The delta door's own 400 does not say where to get a cursor, so the
        # snapshot must close that loop for the reader.
        client.get_board_snapshot.return_value = {"delta_cursor": "c-1", "groups": []}
        result = _invoke(runner, client, ["plan", "board", "snapshot", "b-1"])
        assert "tasks changes" in result.output


class TestTheSnapshotDeltaSeam:
    def test_snapshot_help_points_at_changes(self, runner: CliRunner) -> None:
        assert "tasks changes" in runner.invoke(cli, ["plan", "board", "snapshot", "--help"]).output

    def test_changes_help_points_back_at_the_snapshot(self, runner: CliRunner) -> None:
        assert "snapshot" in runner.invoke(cli, ["plan", "tasks", "changes", "--help"]).output


class TestFormerlyDeferredDoors:
    # `visit` was once excluded as a UI ordering signal. The CLI now covers every
    # live Tasks door (full parity with the web), so it exists and feeds recents.
    @pytest.mark.parametrize("sub", ["visit"])
    def test_now_built(self, runner: CliRunner, sub: str) -> None:
        assert sub in runner.invoke(cli, ["plan", "board", "--help"]).output


class TestHelp:
    @pytest.mark.parametrize("sub", ["list", "get", "snapshot"])
    def test_each_subcommand_renders_help(self, runner: CliRunner, sub: str) -> None:
        assert runner.invoke(cli, ["plan", "board", sub, "--help"]).exit_code == 0


# ---------------------------------------------------------------------------
# Container writes (plan task 16)
# ---------------------------------------------------------------------------


def _invoke_auth(runner: CliRunner, client: MagicMock, args: list[str], auth: str) -> Any:
    # The guard refuses when there is no PERSON token, not when a key exists:
    # both credentials can be configured at once, and the HTTP layer prefers
    # Bearer in that case.
    token: str | None = None if auth == "api_key" else "tok"
    with (
        patch("dailybot_cli.commands.board.require_auth", return_value=client),
        patch("dailybot_cli.commands.board.get_person_token", return_value=token, create=True),
    ):
        return runner.invoke(cli, args)


class TestGuestIsDistinctFromScope:
    def test_guest_not_allowed_talks_about_role(self, runner: CliRunner, client: MagicMock) -> None:
        client.create_board.side_effect = APIError(403, "guest", code="guest_not_allowed")
        result = _invoke_auth(
            runner,
            client,
            [
                "plan",
                "board",
                "create",
                "--project",
                "00000000-0000-0000-0000-000000000002",
                "--key",
                "DSN",
                "--name",
                "x",
            ],
            "bearer",
        )
        assert "role" in " ".join(result.output.lower().split())


_BOARD_PREVIEW: dict[str, Any] = {
    "operation": "board.archive",
    "dry_run": True,
    "reversible": True,
    "restore_path": "/v1/plan/boards/b-1/restore/",
    "consequence": "Archives the board and cascade-archives 12 live tasks.",
    "affects": {"boards": 1, "tasks_cascaded": 12},
    "_idempotency_replayed": False,
}


class TestBoardArchivePreviews:
    def test_dry_run_mutates_nothing(self, runner: CliRunner, client: MagicMock) -> None:
        client.archive_board.return_value = _BOARD_PREVIEW
        result = _invoke(runner, client, ["plan", "board", "archive", "b-1", "--dry-run"])
        assert result.exit_code == 0
        assert client.archive_board.call_count == 1

    def test_the_cascade_count_is_shown(self, runner: CliRunner, client: MagicMock) -> None:
        client.archive_board.return_value = _BOARD_PREVIEW
        result = _invoke(runner, client, ["plan", "board", "archive", "b-1", "--dry-run"])
        assert "12" in result.output

    def test_it_warns_that_restoring_does_not_restore_cascaded_tasks(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.archive_board.side_effect = [_BOARD_PREVIEW, {"_idempotency_replayed": False}]
        result = _invoke(runner, client, ["plan", "board", "archive", "b-1", "--yes"])
        out: str = " ".join(result.output.lower().split())
        assert "not restore" in out or "stay archived" in out

    def test_a_failed_preview_aborts(self, runner: CliRunner, client: MagicMock) -> None:
        client.archive_board.side_effect = APIError(500, "boom", code="server_error")
        result = _invoke(runner, client, ["plan", "board", "archive", "b-1", "--yes"])
        assert result.exit_code != 0
        assert client.archive_board.call_count == 1


class TestBoardLimitIsSurfaced:
    def test_the_entitlement_refusal_is_explained(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.create_board.side_effect = APIError(402, "limit", code="task_boards_limit_reached")
        result = _invoke_auth(
            runner,
            client,
            [
                "plan",
                "board",
                "create",
                "--project",
                "00000000-0000-0000-0000-000000000002",
                "--key",
                "DSN",
                "--name",
                "x",
            ],
            "bearer",
        )
        assert result.exit_code != 0
        assert "limit" in " ".join(result.output.lower().split())


class TestTablesAtEightyColumns:
    """The tables an agent copies from must stay readable in a plain 80-column terminal."""

    STATES: ClassVar[list[str]] = [
        "Backlog",
        "To do",
        "In progress",
        "In review",
        "Done",
        "Canceled",
    ]
    CATEGORIES: ClassVar[list[str]] = [
        "backlog",
        "todo",
        "in_progress",
        "in_progress",
        "done",
        "canceled",
    ]
    PEOPLE: ClassVar[list[tuple[str, str]]] = [
        ("Emma Watson", "00000000-0000-0000-0000-0000000000e1"),
        ("Oscar Marin Molina", "00000000-0000-0000-0000-0000000000e2"),
    ]

    @pytest.fixture(autouse=True)
    def eighty_columns(self) -> Any:
        previous: int | None = display_console._width
        display_console.width = 80
        try:
            yield
        finally:
            display_console._width = previous

    def test_board_states_shows_every_column_name_in_full(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_board_states.return_value = [
            {
                "position": i + 1,
                "name": name,
                "category": self.CATEGORIES[i],
                "is_archived": False,
                "uuid": f"00000000-0000-0000-0000-00000000000{i}",
            }
            for i, name in enumerate(self.STATES)
        ]
        result = _invoke(runner, client, ["plan", "board", "states", "b-1"])
        assert result.exit_code == 0, result.output
        for name in self.STATES:
            assert name in result.output
        assert "…" not in result.output
        assert "00000000-0000-0000-0000-000000000005" in result.output

    def test_the_archived_column_only_appears_when_something_is_archived(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        live: dict[str, Any] = {
            "position": 1,
            "name": "Backlog",
            "category": "backlog",
            "is_archived": False,
            "uuid": "00000000-0000-0000-0000-000000000001",
        }
        client.list_board_states.return_value = [live]
        assert "Archived" not in _invoke(runner, client, ["plan", "board", "states", "b-1"]).output
        client.list_board_states.return_value = [
            live,
            {
                **live,
                "position": 2,
                "is_archived": True,
                "name": "Old",
                "uuid": live["uuid"][:-1] + "2",
            },
        ]
        assert (
            "Archived"
            in _invoke(
                runner, client, ["plan", "board", "states", "b-1", "--include-archived"]
            ).output
        )

    def test_mentionables_shows_the_name_and_the_whole_token(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_board_mentionables.return_value = [
            {"uuid": uuid, "name": name, "kind": "user"} for name, uuid in self.PEOPLE
        ]
        result = _invoke(runner, client, ["plan", "board", "mentionables", "b-1"])
        assert result.exit_code == 0, result.output
        for name, uuid in self.PEOPLE:
            assert name in result.output
            assert f"<@DB@{uuid}>" in result.output
        assert "…" not in result.output

    def test_a_row_without_a_mention_token_keeps_its_uuid(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_board_mentionables.return_value = [
            {"uuid": "00000000-0000-0000-0000-0000000000aa", "name": "Ops team", "kind": "team"}
        ]
        result = _invoke(runner, client, ["plan", "board", "mentionables", "b-1"])
        assert "00000000-0000-0000-0000-0000000000aa" in result.output
        assert "(not mentionable)" in result.output
        assert "<@DB@" not in result.output


class TestUniformColumns:
    """`hide_when_uniform` hides a column that says nothing, never one that says something."""

    def _states(self, archived: bool) -> list[dict[str, Any]]:
        return [
            {
                "position": 1,
                "name": "Old",
                "category": "backlog",
                "is_archived": archived,
                "uuid": "00000000-0000-0000-0000-000000000001",
            }
        ]

    def test_a_column_of_false_is_hidden(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_board_states.return_value = self._states(False)
        assert "Archived" not in _invoke(runner, client, ["plan", "board", "states", "b-1"]).output

    def test_a_column_of_true_is_kept(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_board_states.return_value = self._states(True)
        result = _invoke(runner, client, ["plan", "board", "states", "b-1", "--include-archived"])
        assert "Archived" in result.output
