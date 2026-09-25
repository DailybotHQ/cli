"""Owner vocabulary on the wire (P0 regression guard).

`/v1/tasks/tasks/` filters by `owner` (repeatable, OR-ed; a uuid, `me` or
`unowned`) and refuses `assignee` with 400 `invalid_filter_value`. The
accountable person is WRITTEN as `owner`; `executor` is read-only and a write
carrying it is refused with 400. These tests drive the real `DailyBotClient`
through the CLI and assert the exact query string / JSON body that leaves the
process, so a regression to the old wire fails here rather than in production.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import DailyBotClient
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"
TASK_PATH: str = f"{API_URL}/v1/tasks/tasks/"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> DailyBotClient:
    return DailyBotClient(api_url=API_URL, token="test-token")


def _response(payload: Any) -> MagicMock:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = 200
    mock.json.return_value = payload
    mock.headers = {}
    return mock


def _envelope() -> dict[str, Any]:
    return {"count": 0, "next": None, "previous": None, "results": []}


def _invoke(runner: CliRunner, client: DailyBotClient, args: list[str]) -> Any:
    with patch("dailybot_cli.commands.task.require_auth", return_value=client):
        return runner.invoke(cli, args)


def _sent_params(mock_get: MagicMock) -> Any:
    return mock_get.call_args.kwargs["params"]


class TestListFiltersByOwner:
    def test_owner_is_sent_as_the_owner_parameter(
        self, runner: CliRunner, client: DailyBotClient
    ) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(_envelope())) as get:
            result = _invoke(runner, client, ["task", "list", "--owner", "u-1"])
        assert result.exit_code == 0, result.output
        params: Any = _sent_params(get)
        assert params["owner"] == ["u-1"]
        assert "assignee" not in params

    def test_owner_is_repeatable_and_keeps_every_value(
        self, runner: CliRunner, client: DailyBotClient
    ) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(_envelope())) as get:
            _invoke(runner, client, ["task", "list", "--owner", "me", "--owner", "unowned"])
        assert _sent_params(get)["owner"] == ["me", "unowned"]

    def test_owner_values_reach_the_url_as_repeated_keys(self) -> None:
        # httpx encodes a list value as repeated keys — the OR-ed form the API reads.
        url: httpx.URL = httpx.URL(TASK_PATH, params={"owner": ["me", "u-2"]})
        assert url.query == b"owner=me&owner=u-2"

    def test_the_deprecated_assignee_flag_sends_owner(
        self, runner: CliRunner, client: DailyBotClient
    ) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(_envelope())) as get:
            result = _invoke(runner, client, ["task", "list", "--assignee", "u-1", "--json"])
        assert result.exit_code == 0, result.output
        params: Any = _sent_params(get)
        assert params["owner"] == ["u-1"]
        assert "assignee" not in params

    def test_the_deprecation_note_never_pollutes_json_stdout(
        self, runner: CliRunner, client: DailyBotClient
    ) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(_envelope())):
            result = _invoke(runner, client, ["task", "list", "--assignee", "u-1", "--json"])
        assert result.stdout.lstrip().startswith("{")
        assert "--owner" in result.stderr

    def test_assignee_is_hidden_from_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["task", "list", "--help"])
        assert "--owner" in result.output
        assert "--assignee" not in result.output


class TestCreateWritesOwner:
    def test_owner_is_written_as_owner(self, runner: CliRunner, client: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": "t-1"})
        ) as post:
            result = _invoke(runner, client, ["task", "create", "-t", "x", "--owner", "me"])
        assert result.exit_code == 0, result.output
        body: dict[str, Any] = post.call_args.kwargs["json"]
        assert body == {"title": "x", "owner": "me"}

    def test_the_deprecated_assignee_flag_writes_owner(
        self, runner: CliRunner, client: DailyBotClient
    ) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": "t-1"})
        ) as post:
            _invoke(runner, client, ["task", "create", "-t", "x", "--assignee", "u-1"])
        body: dict[str, Any] = post.call_args.kwargs["json"]
        assert body["owner"] == "u-1"
        assert "executor" not in body and "assignee" not in body


class TestUpdateWritesOwner:
    def test_owner_is_written_as_owner(self, runner: CliRunner, client: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.patch", return_value=_response({"uuid": "t-1"})
        ) as patch_:
            result = _invoke(runner, client, ["task", "update", "ENG-1", "--owner", "u-9"])
        assert result.exit_code == 0, result.output
        assert patch_.call_args.args[0] == f"{TASK_PATH}ENG-1/"
        assert patch_.call_args.kwargs["json"] == {"owner": "u-9"}


class TestSetOwner:
    def test_set_owner_patches_owner(self, runner: CliRunner, client: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.patch", return_value=_response({"uuid": "t-1"})
        ) as patch_:
            result = _invoke(runner, client, ["task", "set-owner", "ENG-7", "me"])
        assert result.exit_code == 0, result.output
        assert patch_.call_args.args[0] == f"{TASK_PATH}ENG-7/"
        assert patch_.call_args.kwargs["json"] == {"owner": "me"}

    def test_the_deprecated_assign_alias_patches_owner(
        self, runner: CliRunner, client: DailyBotClient
    ) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.patch", return_value=_response({"uuid": "t-1"})
        ) as patch_:
            result = _invoke(runner, client, ["task", "assign", "t-1", "--to", "u-1"])
        assert result.exit_code == 0, result.output
        assert patch_.call_args.kwargs["json"] == {"owner": "u-1"}
        assert "set-owner" in result.stderr

    def test_assign_is_hidden_from_the_group_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["task", "--help"])
        assert "set-owner" in result.output
        assert " assign " not in result.output


def test_no_command_writes_executor() -> None:
    import inspect

    from dailybot_cli.commands import task as task_module

    source: str = inspect.getsource(task_module)
    assert "executor=" not in source
    assert 'filters["assignee"]' not in source
