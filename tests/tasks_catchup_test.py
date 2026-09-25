"""The catch-up surface (Tasks Beta PR6a).

`tasks status` asks the pulse for every band in its one request; inbox
read/read-all/unread and the activity cursor are person-only and refuse an API
key before any request; `board mentionables` resolves a name to the
`<@DB@{uuid}>` token a comment needs.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import IDEMPOTENCY_KEY_HEADER, DailyBotClient
from dailybot_cli.commands.public_api_helpers import EXIT_NOT_AUTHENTICATED, EXIT_USAGE_ERROR
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"
BASE: str = f"{API_URL}/v1/tasks/"
BANDS: str = "projects,attention,activity,goal_progress"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


@pytest.fixture
def real() -> DailyBotClient:
    return DailyBotClient(api_url=API_URL, token="test-token")


def _response(payload: Any = None, status: int = 200) -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = {} if payload is None else payload
    mock.headers = {}
    return mock


def _invoke(
    runner: CliRunner, client: Any, args: list[str], *, module: str = "tasks", person: bool = True
) -> Any:
    with (
        patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
        patch(f"dailybot_cli.commands.{module}.get_token", return_value="tok" if person else None),
    ):
        return runner.invoke(cli, args)


class TestPulseBands:
    def test_the_bands_ride_one_request(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response({})) as get:
            real.get_tasks_pulse(include=["projects", "attention", "activity", "goal_progress"])
        assert get.call_count == 1
        assert get.call_args.args[0] == f"{BASE}pulse/"
        assert get.call_args.kwargs["params"] == {"include": BANDS}

    def test_status_renders_bands_and_unread(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_pulse.return_value = {
            "open": 3,
            "unread_count": 7,
            "projects": [{"name": "Apollo", "health": "on_track", "uuid": "p-1"}],
            "attention": [{"key": "ENG-1", "title": "[b]x[/b]", "reason": "overdue"}],
            "activity": [],
            "goal_progress": [{"name": "Q4", "status": "at_risk", "percent_complete": 40}],
        }
        result = _invoke(runner, client, ["tasks", "status"])
        assert result.exit_code == 0, result.output
        for text in ("Apollo", "ENG-1", '"[b]x[/b]"', "Q4", "7"):
            assert text in result.output

    def test_json_is_the_pulse_unchanged(self, runner: CliRunner, client: MagicMock) -> None:
        pulse: dict[str, Any] = {"open": 3, "unread_count": 7, "projects": []}
        client.get_tasks_pulse.return_value = pulse
        result = _invoke(runner, client, ["tasks", "status", "--json"])
        assert json.loads(result.output) == pulse


class TestInbox:
    def test_wire(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({})) as post:
            real.mark_inbox_item_read("i-1")
            assert post.call_args.args[0] == f"{BASE}inbox/i-1/read/"
            real.mark_inbox_read_all()
            assert post.call_args.args[0] == f"{BASE}inbox/read-all/"
        assert IDEMPOTENCY_KEY_HEADER not in dict(post.call_args.kwargs.get("headers") or {})

    def test_read_reports_the_new_count(self, runner: CliRunner, client: MagicMock) -> None:
        client.mark_inbox_item_read.return_value = {"last_seen_at": "t", "unread_count": 2}
        result = _invoke(runner, client, ["tasks", "inbox-read", "i-1"])
        assert result.exit_code == 0, result.output
        assert "2" in result.output

    def test_read_all(self, runner: CliRunner, client: MagicMock) -> None:
        client.mark_inbox_read_all.return_value = {"last_seen_at": "t"}
        result = _invoke(runner, client, ["tasks", "inbox-read-all", "--json"])
        assert json.loads(result.output) == {"last_seen_at": "t"}

    def test_unread(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_inbox_unread_count.return_value = {"unread_count": 4}
        result = _invoke(runner, client, ["tasks", "inbox-unread"])
        assert "4" in result.output

    def test_the_inbox_list_shows_the_item_uuid(self, runner: CliRunner, client: MagicMock) -> None:
        from dailybot_cli.api_client import PaginatedResult

        client.list_tasks_inbox.return_value = PaginatedResult(
            results=[{"uuid": "i-9", "title": "moved"}], count=1, next=None, previous=None
        )
        result = _invoke(runner, client, ["tasks", "inbox"])
        assert "i-9" in result.output


class TestActivityCursor:
    def test_wire(self, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.get", return_value=_response({"last_seen_at": None})
        ) as get:
            real.get_activity_cursor()
        assert get.call_args.args[0] == f"{BASE}me/activity-cursor/"
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response({})) as put:
            real.set_activity_cursor("2026-09-25T09:00:00Z")
        assert put.call_args.args[0] == f"{BASE}me/activity-cursor/"
        assert put.call_args.kwargs["json"] == {"last_seen_at": "2026-09-25T09:00:00Z"}

    def test_read(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_activity_cursor.return_value = {"last_seen_at": "2026-09-25T09:00:00Z"}
        result = _invoke(runner, client, ["tasks", "cursor", "--json"])
        assert json.loads(result.output) == {"last_seen_at": "2026-09-25T09:00:00Z"}
        client.set_activity_cursor.assert_not_called()

    def test_set(self, runner: CliRunner, client: MagicMock) -> None:
        client.set_activity_cursor.return_value = {"last_seen_at": "x"}
        result = _invoke(runner, client, ["tasks", "cursor", "--set", "2026-09-25T09:00:00Z"])
        assert result.exit_code == 0, result.output
        assert client.set_activity_cursor.call_args.args[0].startswith("2026-09-25T09:00:00")

    def test_now_sends_a_utc_timestamp(self, runner: CliRunner, client: MagicMock) -> None:
        client.set_activity_cursor.return_value = {"last_seen_at": "x"}
        _invoke(runner, client, ["tasks", "cursor", "--now"])
        sent: str = client.set_activity_cursor.call_args.args[0]
        assert sent.endswith("Z")

    def test_set_and_now_conflict(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["tasks", "cursor", "--now", "--set", "2026-01-01"])
        assert result.exit_code == EXIT_USAGE_ERROR


@pytest.mark.parametrize(
    "argv",
    [
        ["tasks", "inbox-read", "i-1", "--json"],
        ["tasks", "inbox-read-all", "--json"],
        ["tasks", "inbox-unread", "--json"],
        ["tasks", "cursor", "--json"],
        ["tasks", "cursor", "--now", "--json"],
    ],
)
def test_person_only_doors_refuse_a_key(
    runner: CliRunner, client: MagicMock, argv: list[str]
) -> None:
    result = _invoke(runner, client, argv, person=False)
    assert result.exit_code == EXIT_NOT_AUTHENTICATED
    assert json.loads(result.output)["status"] == "error"
    for method in (
        "mark_inbox_item_read",
        "mark_inbox_read_all",
        "get_tasks_inbox_unread_count",
        "get_activity_cursor",
        "set_activity_cursor",
    ):
        getattr(client, method).assert_not_called()


class TestMentionables:
    ROWS: list[dict[str, Any]] = [  # noqa: RUF012
        {"uuid": "u-1", "name": "Jane Doe", "kind": "user"},
        {"uuid": "u-2", "name": "John Roe", "kind": "user"},
    ]

    def test_wire(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response([])) as get:
            real.list_board_mentionables("b-1")
        assert get.call_args.args[0] == f"{BASE}boards/b-1/mentionables/"

    def test_query_filters_and_shows_the_token(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_board_mentionables.return_value = self.ROWS
        result = _invoke(
            runner, client, ["board", "mentionables", "b-1", "-q", "jane"], module="board"
        )
        assert result.exit_code == 0, result.output
        assert "<@DB@u-1>" in result.output
        assert "John" not in result.output

    def test_json_unfiltered_is_the_payload(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_board_mentionables.return_value = {"results": self.ROWS}
        result = _invoke(runner, client, ["board", "mentionables", "b-1", "--json"], module="board")
        assert json.loads(result.output) == {"results": self.ROWS}

    def test_json_filtered_is_the_matching_rows(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_board_mentionables.return_value = self.ROWS
        result = _invoke(
            runner, client, ["board", "mentionables", "b-1", "-q", "roe", "--json"], module="board"
        )
        assert json.loads(result.output) == [self.ROWS[1]]

    def test_refuses_a_key(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner, client, ["board", "mentionables", "b-1", "--json"], module="board", person=False
        )
        assert result.exit_code == EXIT_NOT_AUTHENTICATED
        client.list_board_mentionables.assert_not_called()
