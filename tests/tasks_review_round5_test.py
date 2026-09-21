"""Regression tests for the CI AI review's fifth pass on PR #85.

Five findings. Three of them are the round-4 fixes applied too narrowly — the
markup escape reached `--operation` but not the failure line beside it, the
stderr rule reached `preview_then_confirm` but not `task bulk`'s own prompt, and
the transport net reached list reads but not the agent and login call sites. The
other two are contract disagreements the round-4 change itself introduced.

The lesson, recorded because it outlives this branch: a fix applied to one call
site of a pattern is a fix applied to none of them.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient, TransportError
from dailybot_cli.commands.public_api_helpers import EXIT_NOT_FOUND
from dailybot_cli.main import cli

_PREVIEW: dict[str, Any] = {
    "operation": "archive",
    "reversible": True,
    "consequence": "Archives the task.",
    "affects": {"tasks": 1},
}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


@pytest.fixture
def real_client() -> DailyBotClient:
    return DailyBotClient(api_url="http://t.example.com", token="t", api_key="k")


@pytest.fixture
def batch(tmp_path: Any) -> str:
    path = tmp_path / "batch.json"
    path.write_text('[{"uuid": "t-1"}]')
    return str(path)


class TestEveryEchoedValueIsEscaped:
    """Finding 1: the bulk failure line interpolated caller data into markup.

    Round 4 escaped `--operation`. The line that reports a failed item echoes the
    `uuid` and `code` from the caller's own batch file into the same kind of
    markup string — and it fires *after* the success line has printed, so the
    caller sees "OK Bulk archive…" followed by "this is a bug, please report it".
    """

    def test_a_markup_uuid_does_not_crash_the_report(
        self, runner: CliRunner, client: MagicMock, batch: str
    ) -> None:
        client.bulk_tasks.return_value = {
            "results": [{"uuid": "[/dim][bold red]pwned", "status": "error", "code": "not_found"}]
        }
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(
                cli, ["task", "bulk", "--operation", "archive", "-f", batch, "--yes"]
            )
        assert "Unexpected error" not in result.stderr
        assert "MarkupError" not in result.stderr

    def test_a_markup_code_does_not_crash_the_report(
        self, runner: CliRunner, client: MagicMock, batch: str
    ) -> None:
        client.bulk_tasks.return_value = {
            "results": [{"uuid": "t-1", "status": "error", "code": "[/dim][red]x"}]
        }
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(
                cli, ["task", "bulk", "--operation", "archive", "-f", batch, "--yes"]
            )
        assert "Unexpected error" not in result.stderr

    def test_the_failure_is_still_reported(
        self, runner: CliRunner, client: MagicMock, batch: str
    ) -> None:
        # Escaping must not swallow the row: a partial failure still exits non-zero.
        client.bulk_tasks.return_value = {
            "results": [{"uuid": "t-1", "status": "error", "code": "not_found"}]
        }
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(
                cli, ["task", "bulk", "--operation", "archive", "-f", batch, "--yes"]
            )
        assert result.exit_code == 1
        assert "not_found" in result.stdout


class TestBulkHonoursTheJsonStreamContract:
    """Finding 2: `task bulk --json` without `--yes` wrote its prompt to stdout.

    Round 4 moved the destructive helper's panel and prompt to stderr under
    `--json`. `task bulk` has no dry run, so it never used that helper — and kept
    its own confirmation on stdout, in front of the JSON document.
    """

    def test_the_prompt_never_reaches_stdout(
        self, runner: CliRunner, client: MagicMock, batch: str
    ) -> None:
        # CliRunner echoes the supplied keystrokes onto stdout itself, so the
        # assertion is about what the *program* writes: neither the warning nor the
        # prompt may appear there.
        client.bulk_tasks.return_value = {"results": [{"uuid": "t-1", "status": "ok"}]}
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(
                cli,
                ["task", "bulk", "--operation", "archive", "-f", batch, "--json"],
                input="y\n",
            )
        assert "About to apply" not in result.stdout
        assert "Proceed?" not in result.stdout
        assert '"status": "ok"' in result.stdout

    def test_yes_json_emits_exactly_one_document(
        self, runner: CliRunner, client: MagicMock, batch: str
    ) -> None:
        client.bulk_tasks.return_value = {"results": [{"uuid": "t-1", "status": "ok"}]}
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(
                cli,
                ["task", "bulk", "--operation", "archive", "-f", batch, "--yes", "--json"],
            )
        assert json.loads(result.stdout) == {"results": [{"uuid": "t-1", "status": "ok"}]}

    def test_the_warning_still_reaches_the_operator(
        self, runner: CliRunner, client: MagicMock, batch: str
    ) -> None:
        client.bulk_tasks.return_value = {"results": []}
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(
                cli,
                ["task", "bulk", "--operation", "archive", "-f", batch, "--json"],
                input="y\n",
            )
        assert "There is no dry run for bulk" in result.stderr

    def test_without_json_the_warning_stays_on_stdout(
        self, runner: CliRunner, client: MagicMock, batch: str
    ) -> None:
        client.bulk_tasks.return_value = {"results": []}
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(
                cli, ["task", "bulk", "--operation", "archive", "-f", batch], input="y\n"
            )
        assert "There is no dry run for bulk" in result.stdout


class TestFailedPreviewUsesTheDocumentedExit:
    """Finding 3: an aborted preview always exited 1, whatever the refusal was.

    `dailybot task archive <already-gone> --yes` exited 1 instead of the
    documented 5, so an agent branching "5 → skip, 1 → alert" paged on every
    object someone else had already archived.
    """

    def test_not_found_exits_five(self, runner: CliRunner, client: MagicMock) -> None:
        client.archive_task.side_effect = APIError(status_code=404, detail="gone", code="not_found")
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(cli, ["task", "archive", "t-1", "--yes"])
        assert result.exit_code == EXIT_NOT_FOUND

    def test_nothing_was_mutated(self, runner: CliRunner, client: MagicMock) -> None:
        # The exit code changed; the abort did not.
        client.archive_task.side_effect = APIError(status_code=404, detail="gone")
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            runner.invoke(cli, ["task", "archive", "t-1", "--yes"])
        assert client.archive_task.call_count == 1

    def test_the_message_still_says_nothing_changed(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.archive_task.side_effect = APIError(status_code=404, detail="gone")
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(cli, ["task", "archive", "t-1", "--yes"])
        assert "nothing was changed" in result.stderr.lower()


class TestActorRequiredIsACredentialRefusal:
    """Finding 5: `400 actor_required` skipped the alt-credential retry.

    The retry fires on 401/403. The person-shaped Tasks doors have a third
    refusal shape that means the same thing — wrong *kind* of credential — but
    arrives as a 400. With `.dailybot/env.json` supplying the key, `X-API-KEY`
    goes first even though a Bearer session exists, so without this the CLI told
    an already-signed-in user to run `dailybot login`.
    """

    def _resp(self, status: int, body: Any) -> MagicMock:
        mock: MagicMock = MagicMock(spec=httpx.Response)
        mock.status_code = status
        mock.json.return_value = body
        mock.headers = {}
        return mock

    def test_the_alt_credential_is_tried(self, real_client: DailyBotClient) -> None:
        refused = self._resp(400, {"code": "actor_required", "detail": "no actor"})
        ok = self._resp(200, {"count": 0, "next": None, "previous": None, "results": []})
        with patch("httpx.get", side_effect=[refused, ok]) as mock_get:
            real_client.list_my_tasks()
        assert mock_get.call_count == 2

    def test_an_ordinary_four_hundred_is_not_retried(self, real_client: DailyBotClient) -> None:
        # Only the credential-shaped refusal earns a second request; retrying a
        # plain validation error would double every bad call.
        bad = self._resp(400, {"code": "invalid_filter_value", "detail": "nope"})
        with patch("httpx.get", return_value=bad) as mock_get, pytest.raises(APIError):
            real_client.list_my_tasks()
        assert mock_get.call_count == 1

    def test_a_non_json_four_hundred_is_not_retried(self, real_client: DailyBotClient) -> None:
        bad: MagicMock = MagicMock(spec=httpx.Response)
        bad.status_code = 400
        bad.json.side_effect = ValueError("nope")
        bad.headers = {}
        bad.text = "<html>"
        with patch("httpx.get", return_value=bad) as mock_get, pytest.raises(APIError):
            real_client.list_my_tasks()
        assert mock_get.call_count == 1


class TestTransportNetCoversEveryCallSite:
    """Finding 4 (carried from an earlier round): agent and login calls were bare.

    `_agent_request`, `request_code` / `verify_code` / `logout` and the agent
    registration pair call `httpx` directly — the test suite patches exactly those
    functions, so they cannot be routed through the per-method dispatcher. They
    still need the same guard, or a dead host exits 1 with "Unexpected error"
    instead of the documented transport code.
    """

    @pytest.mark.parametrize(
        ("target", "call"),
        [
            ("httpx.post", lambda c: c.request_code("me@example.com")),
            ("httpx.post", lambda c: c.verify_code("me@example.com", "123456")),
            ("httpx.post", lambda c: c.logout()),
            ("httpx.get", lambda c: c.get_registration_challenge()),
        ],
    )
    def test_a_dead_host_raises_transport_error(
        self, real_client: DailyBotClient, target: str, call: Any
    ) -> None:
        with (
            patch(target, side_effect=httpx.ConnectError("refused")),
            pytest.raises(TransportError),
        ):
            call(real_client)

    def test_the_agent_path_is_covered_too(self, real_client: DailyBotClient) -> None:
        with (
            patch("httpx.request", side_effect=httpx.ConnectError("refused")),
            pytest.raises(TransportError),
        ):
            real_client.submit_agent_report(content="hi", agent_name="a")

    def test_the_message_names_the_host(self, real_client: DailyBotClient) -> None:
        with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
            try:
                real_client.request_code("me@example.com")
            except TransportError as exc:
                assert "t.example.com" in str(exc)
            else:  # pragma: no cover - the call above always raises
                pytest.fail("expected TransportError")
