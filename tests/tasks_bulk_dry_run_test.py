"""`task bulk --dry-run` (server-side preview) and the bulk contract corrections.

The dry run is the real bulk, run and rolled back by the server: same body, no
Idempotency-Key, nothing written. Safety property worth pinning: because a real
bulk REQUIRES the key, a server that predates the dry run refuses a keyless call
with `idempotency_key_required` instead of applying it — the CLI turns that into a
"this server cannot preview" message, never into a write.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import IDEMPOTENCY_KEY_HEADER, APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import EXIT_USAGE_ERROR
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"
BULK_URL: str = f"{API_URL}/v1/tasks/tasks/bulk/"
ITEMS: str = '[{"task": "ENG-142", "owner": "u-1"}]'

PREVIEW: dict[str, Any] = {
    "operation": "task.bulk.set_owner",
    "dry_run": True,
    "reversible": True,
    "consequence": "Set the owner of 1 task.",
    "affects": {"tasks": 1},
    "items": [
        {
            "index": 0,
            "task": "t-1",
            "key": "ENG-142",
            "changes": {"owner": {"from": None, "to": "u-1"}},
        }
    ],
    "refused": [],
}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


@pytest.fixture
def real() -> DailyBotClient:
    return DailyBotClient(api_url=API_URL, token="test-token")


def _response(payload: Any, status: int = 200) -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = payload
    mock.headers = {}
    return mock


def _invoke(runner: CliRunner, client: Any, args: list[str], stdin: str = ITEMS) -> Any:
    with patch("dailybot_cli.commands.task.require_auth", return_value=client):
        return runner.invoke(cli, args, input=stdin)


class TestWire:
    def test_a_dry_run_sends_the_param_and_no_key(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response(PREVIEW)) as post:
            real.bulk_tasks(operation="set_owner", items=[{"task": "ENG-142"}], dry_run=True)
        assert post.call_args.args[0] == BULK_URL
        assert post.call_args.kwargs["params"] == {"dry_run": "true"}
        assert IDEMPOTENCY_KEY_HEADER not in dict(post.call_args.kwargs.get("headers") or {})

    def test_the_real_call_always_sends_a_key(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({})) as post:
            real.bulk_tasks(operation="archive", items=[{"task": "ENG-142"}])
        assert IDEMPOTENCY_KEY_HEADER in dict(post.call_args.kwargs.get("headers") or {})
        assert not post.call_args.kwargs.get("params")

    def test_create_carries_the_board_at_the_top(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({})) as post:
            real.bulk_tasks(operation="create", items=[{"title": "x"}], board="ENG")
        assert post.call_args.kwargs["json"] == {
            "operation": "create",
            "items": [{"title": "x"}],
            "board": "ENG",
        }


class TestDryRunCommand:
    def test_json_is_the_preview_and_nothing_else_is_called(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.bulk_tasks.return_value = PREVIEW
        result = _invoke(
            runner,
            client,
            ["task", "bulk", "--operation", "set_owner", "-f", "-", "--dry-run", "--json"],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == PREVIEW
        assert client.bulk_tasks.call_count == 1
        assert client.bulk_tasks.call_args.kwargs["dry_run"] is True

    def test_human_output_states_the_consequence_and_the_changes(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.bulk_tasks.return_value = PREVIEW
        result = _invoke(
            runner, client, ["task", "bulk", "--operation", "set_owner", "-f", "-", "--dry-run"]
        )
        assert result.exit_code == 0, result.output
        collapsed: str = " ".join(result.output.split())
        assert "Set the owner of 1 task." in collapsed
        assert "ENG-142" in collapsed and "owner" in collapsed
        assert "Nothing was changed" in collapsed

    def test_predicted_refusals_exit_non_zero(self, runner: CliRunner, client: MagicMock) -> None:
        refused: dict[str, Any] = {
            **PREVIEW,
            "refused": [{"index": 0, "code": "version_conflict", "detail": "changed"}],
        }
        client.bulk_tasks.return_value = refused
        result = _invoke(
            runner,
            client,
            ["task", "bulk", "--operation", "set_owner", "-f", "-", "--dry-run", "--json"],
        )
        assert result.exit_code == 1
        assert json.loads(result.output)["refused"][0]["code"] == "version_conflict"

    def test_a_server_without_dry_run_is_explained_not_applied(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.bulk_tasks.side_effect = APIError(
            400, "Key required.", code="idempotency_key_required"
        )
        result = _invoke(
            runner,
            client,
            ["task", "bulk", "--operation", "archive", "-f", "-", "--dry-run", "--json"],
        )
        assert result.exit_code == EXIT_USAGE_ERROR
        body: dict[str, Any] = json.loads(result.output)
        assert body["code"] == "bulk_dry_run_unsupported"
        assert "preview" in body["message"].lower()
        assert client.bulk_tasks.call_count == 1

    def test_a_dry_run_needs_no_confirmation(self, runner: CliRunner, client: MagicMock) -> None:
        client.bulk_tasks.return_value = PREVIEW
        result = _invoke(
            runner, client, ["task", "bulk", "--operation", "set_owner", "-f", "-", "--dry-run"]
        )
        assert "Proceed?" not in result.output


class TestBulkContract:
    def test_create_requires_board(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner,
            client,
            ["task", "bulk", "--operation", "create", "-f", "-", "--yes"],
            stdin='[{"title": "x"}]',
        )
        assert result.exit_code == EXIT_USAGE_ERROR
        client.bulk_tasks.assert_not_called()

    def test_create_sends_the_board(self, runner: CliRunner, client: MagicMock) -> None:
        client.bulk_tasks.return_value = {"succeeded": 1, "failed": 0, "results": []}
        result = _invoke(
            runner,
            client,
            [
                "task",
                "bulk",
                "--operation",
                "create",
                "--board",
                "ENG",
                "-f",
                "-",
                "--yes",
                "--json",
            ],
            stdin='[{"title": "x"}]',
        )
        assert result.exit_code == 0, result.output
        assert client.bulk_tasks.call_args.kwargs["board"] == "ENG"

    def test_an_undeclared_operation_is_refused(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner, client, ["task", "bulk", "--operation", "explode", "-f", "-", "--yes"]
        )
        assert result.exit_code == EXIT_USAGE_ERROR
        client.bulk_tasks.assert_not_called()

    def test_failed_rows_are_named_by_task(self, runner: CliRunner, client: MagicMock) -> None:
        client.bulk_tasks.return_value = {
            "succeeded": 0,
            "failed": 1,
            "results": [{"task": "ENG-9", "status": "error", "code": "version_conflict"}],
        }
        result = _invoke(
            runner, client, ["task", "bulk", "--operation", "archive", "-f", "-", "--yes"]
        )
        assert result.exit_code == 1
        assert "ENG-9" in result.output

    def test_the_prompt_points_at_the_dry_run(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner, client, ["task", "bulk", "--operation", "archive", "-f", "-"], stdin=ITEMS
        )
        # stdin is the batch, so the prompt reads EOF and aborts; the notice is what matters.
        assert "--dry-run" in result.output
