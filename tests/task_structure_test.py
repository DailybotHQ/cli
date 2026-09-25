"""Task structure and history (Tasks Beta PR3b): children, duplicate, events, activity.

Delegation (list / delegate / revoke / handback) is an x-phase-2 surface in the
contract and is deliberately NOT built; a test pins its absence.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import (
    IDEMPOTENCY_KEY_HEADER,
    APIError,
    DailyBotClient,
    PaginatedResult,
)
from dailybot_cli.commands.public_api_helpers import EXIT_NOT_FOUND, EXIT_USAGE_ERROR
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"
BASE: str = f"{API_URL}/v1/tasks/tasks/"
TASK: str = "ENG-142"


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


def _page(rows: list[dict[str, Any]]) -> PaginatedResult:
    return PaginatedResult(results=rows, count=len(rows), next=None, previous=None)


def _invoke(runner: CliRunner, client: Any, args: list[str]) -> Any:
    with patch("dailybot_cli.commands.task.require_auth", return_value=client):
        return runner.invoke(cli, args)


class TestWire:
    @pytest.mark.parametrize(
        ("method", "path"), [("list_task_children", "children"), ("list_task_events", "events")]
    )
    def test_reads_hit_their_door(self, real: DailyBotClient, method: str, path: str) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response([])) as get:
            getattr(real, method)(TASK)
        assert get.call_args.args[0] == f"{BASE}{TASK}/{path}/"

    def test_activity_sends_its_declared_filters(self, real: DailyBotClient) -> None:
        envelope: dict[str, Any] = {"count": 0, "next": None, "previous": None, "results": []}
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(envelope)) as get:
            real.list_task_activity(TASK, params={"type": "task.moved"})
        assert get.call_args.args[0] == f"{BASE}{TASK}/activity/"
        assert get.call_args.kwargs["params"]["type"] == "task.moved"

    def test_duplicate_defaults_to_an_empty_body_and_sends_a_key(
        self, real: DailyBotClient
    ) -> None:
        # R13: the door honours Idempotency-Key, so a retry after a timeout replays
        # the same copy instead of making a second one.
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"key": "ENG-143"}, 201)
        ) as post:
            result: Any = real.duplicate_task(TASK, idempotency_key="dup-12345678")
        assert post.call_args.args[0] == f"{BASE}{TASK}/duplicate/"
        assert post.call_args.kwargs["json"] == {}
        headers: dict[str, str] = dict(post.call_args.kwargs.get("headers") or {})
        assert headers[IDEMPOTENCY_KEY_HEADER] == "dup-12345678"
        assert result["_idempotency_key"] == "dup-12345678"

    def test_duplicate_sends_include(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({}, 201)) as post:
            real.duplicate_task(TASK, include=["title", "owner"])
        assert post.call_args.kwargs["json"] == {"include": ["title", "owner"]}


class TestChildren:
    def test_json_is_the_payload(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_task_children.return_value = [{"uuid": "t-2", "key": "ENG-143"}]
        result = _invoke(runner, client, ["task", "children", TASK, "--json"])
        assert json.loads(result.output) == [{"uuid": "t-2", "key": "ENG-143"}]

    def test_table_renders(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_task_children.return_value = {
            "results": [{"uuid": "t-2", "key": "ENG-143", "title": "child"}]
        }
        result = _invoke(runner, client, ["task", "children", TASK])
        assert result.exit_code == 0, result.output
        assert "ENG-143" in result.output

    def test_missing_task_is_not_found(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_task_children.side_effect = APIError(404, "Gone.", code="not_found")
        result = _invoke(runner, client, ["task", "children", TASK, "--json"])
        assert result.exit_code == EXIT_NOT_FOUND


class TestDuplicate:
    def test_include_is_forwarded(self, runner: CliRunner, client: MagicMock) -> None:
        client.duplicate_task.return_value = {"uuid": "t-9", "key": "ENG-143"}
        result = _invoke(
            runner,
            client,
            ["task", "duplicate", TASK, "--include", "title", "--include", "due_date", "--json"],
        )
        assert result.exit_code == 0, result.output
        assert client.duplicate_task.call_args.kwargs == {
            "include": ["title", "due_date"],
            "idempotency_key": None,
        }

    def test_no_include_lets_the_server_default(self, runner: CliRunner, client: MagicMock) -> None:
        client.duplicate_task.return_value = {"key": "ENG-143"}
        result = _invoke(runner, client, ["task", "duplicate", TASK])
        assert result.exit_code == 0, result.output
        assert client.duplicate_task.call_args.kwargs == {"include": None, "idempotency_key": None}
        assert "ENG-143" in result.output

    def test_an_unknown_field_is_a_usage_error(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["task", "duplicate", TASK, "--include", "state"])
        assert result.exit_code == EXIT_USAGE_ERROR
        client.duplicate_task.assert_not_called()

    def test_a_key_can_be_reused_for_a_safe_retry(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.duplicate_task.return_value = {"key": "ENG-143", "_idempotency_key": "k-12345678"}
        result = _invoke(
            runner, client, ["task", "duplicate", TASK, "--idempotency-key", "k-12345678"]
        )
        assert result.exit_code == 0, result.output
        assert client.duplicate_task.call_args.kwargs["idempotency_key"] == "k-12345678"


class TestEventsAndActivity:
    def test_events_render_actor_as_data(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_task_events.return_value = [
            {"type": "task.moved", "created_at": "2026-09-25", "actor": {"name": "[b]Eve[/b]"}}
        ]
        result = _invoke(runner, client, ["task", "events", TASK])
        assert result.exit_code == 0, result.output
        assert "task.moved" in result.output
        assert '"[b]Eve[/b]"' in result.output

    def test_activity_json_is_the_envelope(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_task_activity.return_value = _page([{"type": "task.moved"}])
        result = _invoke(runner, client, ["task", "activity", TASK, "--json"])
        assert result.exit_code == 0, result.output
        assert set(json.loads(result.output)) == {"count", "next", "previous", "results"}

    def test_activity_filters_reach_the_client(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_task_activity.return_value = _page([])
        result = _invoke(
            runner,
            client,
            [
                "task", "activity", TASK, "--updated-since", "2026-09-20T00:00:00Z",
                "--type", "task.moved", "--json",
            ],
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        params: dict[str, Any] = client.list_task_activity.call_args.kwargs["params"]
        assert params["type"] == "task.moved"
        assert params["updated_since"].startswith("2026-09-20T00:00:00")


def test_delegation_is_not_built() -> None:
    # x-phase 2 in the contract: excluded until it is promoted to the public surface.
    output: str = CliRunner().invoke(cli, ["task", "--help"]).output
    assert "delegat" not in output
