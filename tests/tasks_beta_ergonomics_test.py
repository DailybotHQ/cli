"""Agent-first ergonomics for the Tasks Beta (PR1).

KEY-n addressing on every task argument, `task list --sort`, `board tasks`,
`tasks changes --updated-since`, one exit code per meaning, and the Beta notice
(present in every Tasks `--help` and in human `tasks status`, absent from every
`--json` payload).
"""

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli import api_client
from dailybot_cli.api_client import APIError, DailyBotClient, PaginatedResult
from dailybot_cli.commands import public_api_helpers, tasks as tasks_module
from dailybot_cli.commands._beta import BETA_HELP_BLOCK, BETA_STATUS_LINE
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"
README_PATH: Path = Path(__file__).resolve().parent.parent / "README.md"
TASK_KEY: str = "ENG-142"
STATE_UUID: str = "00000000-0000-0000-0000-000000000005"

# The canonical Beta copy, as product ships it (Markdown).
CANONICAL_BETA: str = (
    "**Beta** — Tasks is in beta. Everything under `/tasks` in the web app, the CLI and "
    "agent skill commands for projects, goals, boards and tasks, and the `/v1/tasks/` "
    "public API may change before general availability. Want to try it with your team? "
    "Write to **support@dailybot.com**."
)
TASKS_GROUPS: tuple[str, ...] = ("tasks", "task", "board", "project", "goal")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


def _page(rows: list[dict[str, Any]] | None = None) -> PaginatedResult:
    items: list[dict[str, Any]] = rows or []
    return PaginatedResult(results=items, count=len(items), next=None, previous=None)


def _plain(text: str) -> str:
    """Drop Markdown emphasis and collapse whitespace: the words, not the styling."""
    return re.sub(r"\s+", " ", text.replace("**", "").replace("`", "")).strip()


# ---------------------------------------------------------------------------
# KEY-n addressing
# ---------------------------------------------------------------------------

# (argv, the client method whose first positional argument must be the key)
KEY_CASES: list[tuple[list[str], str]] = [
    (["task", "get", TASK_KEY], "get_task"),
    (["task", "update", TASK_KEY, "--title", "x"], "update_task"),
    (["task", "move", TASK_KEY, "--state", STATE_UUID], "move_task"),
    (["task", "set-owner", TASK_KEY, "me"], "update_task"),
    (["task", "comment", TASK_KEY, "hello"], "comment_on_task"),
    (["task", "comments", TASK_KEY], "list_task_comments"),
    (["task", "link", TASK_KEY, "ENG-99", "--type", "blocks"], "relate_tasks"),
    (["task", "labels", TASK_KEY, "--mode", "add", "--label", "l-1"], "batch_task_labels"),
    (["task", "participants", "add", TASK_KEY, "--user", "u-1"], "add_task_participant"),
    (["task", "archive", TASK_KEY, "--yes"], "archive_task"),
    (["task", "delete", TASK_KEY, "--yes"], "archive_task"),
    (["task", "restore", TASK_KEY], "restore_task"),
]


class TestKeyAddressing:
    @pytest.mark.parametrize(("argv", "method"), KEY_CASES)
    def test_a_task_key_reaches_the_client_unchanged(
        self, runner: CliRunner, client: MagicMock, argv: list[str], method: str
    ) -> None:
        getattr(client, method).return_value = {"uuid": "t-1", "key": TASK_KEY}
        if method == "archive_task":
            # Archive previews first, then applies: the first answer is a preview.
            client.archive_task.side_effect = [
                {"operation": "task.archive", "reversible": True},
                {"uuid": "t-1", "key": TASK_KEY},
            ]
        client.list_task_comments.return_value = _page()
        with (
            patch("dailybot_cli.commands.task.require_auth", return_value=client),
            patch("dailybot_cli.commands.task.get_token", return_value="tok"),
        ):
            result = runner.invoke(cli, argv)
        assert result.exit_code == 0, result.output
        call = getattr(client, method).call_args
        assert call.args[0] == TASK_KEY

    def test_a_key_lands_in_the_url_path_verbatim(self) -> None:
        real: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        response: MagicMock = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.json.return_value = {"uuid": "t-1"}
        response.headers = {}
        with patch("dailybot_cli.api_client.httpx.get", return_value=response) as get:
            real.get_task(TASK_KEY)
        assert get.call_args.args[0] == f"{API_URL}/v1/tasks/tasks/{TASK_KEY}/"

    def test_help_names_the_argument_task_not_uuid(self, runner: CliRunner) -> None:
        for sub in ("get", "update", "move", "archive", "restore", "comment", "set-owner"):
            result = runner.invoke(cli, ["task", sub, "--help"])
            assert "TASK" in result.output, sub
            assert "TASK_UUID" not in result.output, sub

    def test_the_group_help_says_keys_work(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["task", "--help"])
        assert "ENG-142" in result.output
        assert "or a uuid" in result.output


# ---------------------------------------------------------------------------
# task list --sort
# ---------------------------------------------------------------------------


class TestTaskListSort:
    @pytest.mark.parametrize("value", ["rank", "-updated_at", "due_date", "-completed_at"])
    def test_a_declared_field_is_sent_as_sort(
        self, runner: CliRunner, client: MagicMock, value: str
    ) -> None:
        client.list_tasks.return_value = _page()
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(cli, ["task", "list", "--sort", value])
        assert result.exit_code == 0, result.output
        assert client.list_tasks.call_args.kwargs["filters"]["sort"] == value

    @pytest.mark.parametrize("value", ["title", "--rank", "-", "status"])
    def test_an_unknown_field_is_a_usage_error_that_lists_the_choices(
        self, runner: CliRunner, client: MagicMock, value: str
    ) -> None:
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(cli, ["task", "list", "--sort", value])
        assert result.exit_code == 2
        assert "updated_at" in result.output
        client.list_tasks.assert_not_called()


# ---------------------------------------------------------------------------
# board tasks
# ---------------------------------------------------------------------------


class TestBoardTasks:
    def test_it_reads_the_board_tasks_door(self) -> None:
        real: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        response: MagicMock = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.json.return_value = {"count": 0, "next": None, "previous": None, "results": []}
        response.headers = {}
        with patch("dailybot_cli.api_client.httpx.get", return_value=response) as get:
            real.list_board_tasks("b-1")
        assert get.call_args.args[0] == f"{API_URL}/v1/tasks/boards/b-1/tasks/"

    def test_json_mode_emits_the_list_envelope(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_board_tasks.return_value = _page([{"uuid": "t-1", "key": TASK_KEY}])
        with patch("dailybot_cli.commands.board.require_auth", return_value=client):
            result = runner.invoke(cli, ["board", "tasks", "b-1", "--json"])
        assert result.exit_code == 0, result.output
        body: dict[str, Any] = json.loads(result.output)
        assert set(body) == {"count", "next", "previous", "results"}
        assert client.list_board_tasks.call_args.args[0] == "b-1"

    def test_titles_render_as_quoted_data(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_board_tasks.return_value = _page(
            [{"uuid": "t-1", "key": TASK_KEY, "title": "[red]ignore previous[/red]"}]
        )
        with patch("dailybot_cli.commands.board.require_auth", return_value=client):
            result = runner.invoke(cli, ["board", "tasks", "b-1"])
        assert result.exit_code == 0, result.output
        assert "ignore previous" in result.output

    def test_an_invisible_board_exits_not_found(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_board_tasks.side_effect = APIError(404, "Not found.", code="not_found")
        with patch("dailybot_cli.commands.board.require_auth", return_value=client):
            result = runner.invoke(cli, ["board", "tasks", "b-x", "--json"])
        assert result.exit_code == public_api_helpers.EXIT_NOT_FOUND
        assert json.loads(result.output)["code"] == "not_found"


# ---------------------------------------------------------------------------
# tasks changes --updated-since
# ---------------------------------------------------------------------------


class TestUpdatedSince:
    @pytest.mark.parametrize("flag", ["--updated-since", "--since"])
    def test_both_spellings_send_updated_since(
        self, runner: CliRunner, client: MagicMock, flag: str
    ) -> None:
        client.get_board_delta.return_value = {"tasks": [], "delta_cursor": "c"}
        with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
            result = runner.invoke(
                cli, ["tasks", "changes", "b-1", flag, "2026-09-19T13:13:37Z", "--json"]
            )
        assert result.exit_code == 0, result.output
        assert client.get_board_delta.call_args.kwargs["updated_since"] == "2026-09-19T13:13:37Z"
        client.get_board_snapshot.assert_not_called()

    def test_help_teaches_the_current_name_only(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["tasks", "changes", "--help"])
        assert "--updated-since" in result.output
        assert "--since " not in result.output


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


def test_every_exit_code_means_one_thing() -> None:
    constants: dict[str, int] = {
        name: value
        for module in (public_api_helpers, api_client, tasks_module)
        for name, value in vars(module).items()
        if name.startswith("EXIT_") and isinstance(value, int)
    }
    by_value: dict[int, list[str]] = {}
    for name, value in constants.items():
        by_value.setdefault(value, []).append(name)
    shared: dict[int, list[str]] = {v: n for v, n in by_value.items() if len(set(n)) > 1}
    assert shared == {}, shared
    assert public_api_helpers.EXIT_QUOTA_EXHAUSTED == 10


# ---------------------------------------------------------------------------
# Beta notice
# ---------------------------------------------------------------------------


class TestBetaNotice:
    def test_the_help_block_carries_the_canonical_words(self) -> None:
        assert _plain(BETA_HELP_BLOCK.replace("\b", "")) == _plain(CANONICAL_BETA)

    @pytest.mark.parametrize("group", TASKS_GROUPS)
    def test_it_tops_every_tasks_group_help(self, runner: CliRunner, group: str) -> None:
        result = runner.invoke(cli, [group, "--help"])
        assert result.exit_code == 0
        body: str = result.output.split("\n", 2)[2]
        assert _plain(body).startswith(_plain(CANONICAL_BETA))

    def test_the_root_listing_keeps_each_group_summary(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert "Beta —" not in result.output

    def test_human_status_shows_one_beta_line(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_pulse.return_value = {"open": 1}
        with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
            result = runner.invoke(cli, ["tasks", "status"])
        assert result.exit_code == 0, result.output
        assert _plain(BETA_STATUS_LINE) in _plain(result.output)

    def test_json_status_adds_nothing(self, runner: CliRunner, client: MagicMock) -> None:
        pulse: dict[str, Any] = {"open": 1}
        client.get_tasks_pulse.return_value = pulse
        with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
            result = runner.invoke(cli, ["tasks", "status", "--json"])
        assert json.loads(result.output) == pulse
        assert "Beta" not in result.output

    def test_the_readme_carries_the_canonical_markdown(self) -> None:
        readme: str = README_PATH.read_text(encoding="utf-8")
        quoted: str = _plain(" ".join(line.lstrip("> ") for line in readme.splitlines()))
        assert _plain(CANONICAL_BETA) in quoted
        assert "**Beta** — Tasks is in beta." in readme
