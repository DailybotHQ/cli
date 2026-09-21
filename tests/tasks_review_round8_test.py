"""Regression tests for the CI AI review's eighth pass on PR #85.

Five findings, two of them consequential in the same specific way: **the CLI said
something about a write that was not true, and a caller acting on it would do the
wrong thing.**

- `task create` promised that "a retry that times out cannot create a second task".
  It generated a fresh uuid4 per invocation and never let that key out, so the
  retry the sentence describes was impossible to perform — re-running the command
  duplicated.
- A timed-out destructive **preview** reported "it may have been applied". A
  `dry_run=true` POST writes no rows and no audit events, so the operator was sent
  into recovery for a mutation that provably never ran.

Both are cases where a reassuring message is worse than no message.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import (
    IDEMPOTENCY_KEY_SENT_KEY,
    APIError,
    DailyBotClient,
    TransportError,
)
from dailybot_cli.commands.public_api_helpers import resolve_error_message
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


@pytest.fixture
def real_client() -> DailyBotClient:
    return DailyBotClient(api_url="http://t.example.com", token="t", api_key="k")


def _created(**extra: Any) -> dict[str, Any]:
    return {"uuid": "t-1", "title": "x", "_idempotency_replayed": False, **extra}


class TestTheGeneratedKeyLeavesTheClient:
    """Finding 1: the key that makes a retry safe was never surfaced.

    `_tasks_write` minted a uuid4 when `--idempotency-key` was omitted and kept it.
    Re-running the command minted a different one, so the documented guarantee —
    "a retry that times out cannot create a second task" — could not be exercised.
    """

    def test_the_client_annotates_the_key_it_sent(self, real_client: DailyBotClient) -> None:
        ok: MagicMock = MagicMock(spec=httpx.Response)
        ok.status_code = 201
        ok.json.return_value = {"uuid": "t-1"}
        ok.headers = {}
        with patch("httpx.post", return_value=ok) as mock_post:
            result: dict[str, Any] = real_client.create_task(title="x")
        sent: str = mock_post.call_args[1]["headers"]["Idempotency-Key"]
        assert result[IDEMPOTENCY_KEY_SENT_KEY] == sent

    def test_an_explicit_key_is_echoed_unchanged(self, real_client: DailyBotClient) -> None:
        ok: MagicMock = MagicMock(spec=httpx.Response)
        ok.status_code = 201
        ok.json.return_value = {"uuid": "t-1"}
        ok.headers = {}
        with patch("httpx.post", return_value=ok):
            result: dict[str, Any] = real_client.create_task(title="x", idempotency_key="mine-1")
        assert result[IDEMPOTENCY_KEY_SENT_KEY] == "mine-1"

    def test_json_mode_carries_it(self, runner: CliRunner, client: MagicMock) -> None:
        client.create_task.return_value = _created(_idempotency_key="abc-123")
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(cli, ["task", "create", "-t", "x", "--json"])
        assert json.loads(result.stdout)["_idempotency_key"] == "abc-123"

    def test_the_human_path_prints_it(self, runner: CliRunner, client: MagicMock) -> None:
        client.create_task.return_value = _created(_idempotency_key="abc-123")
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(cli, ["task", "create", "-t", "x"])
        assert "abc-123" in result.stdout
        assert "--idempotency-key" in result.stdout

    def test_a_replay_does_not_claim_a_new_write(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # The replay branch is the one place the key is not the headline.
        client.create_task.return_value = {
            "uuid": "t-1",
            "_idempotency_replayed": True,
            "_idempotency_key": "abc-123",
        }
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(cli, ["task", "create", "-t", "x"])
        assert "already applied" in result.stdout

    def test_the_help_no_longer_overpromises(self, runner: CliRunner) -> None:
        out: str = runner.invoke(cli, ["task", "create", "--help"]).stdout
        collapsed: str = " ".join(out.split())
        assert "cannot create a second task" not in collapsed
        assert "--idempotency-key" in collapsed


class TestAPreviewTimeoutDoesNotClaimAWrite:
    """Finding 2: a timed-out dry run said the operation may have been applied.

    The preview is a POST, so it matched the "write that timed out" branch. But a
    `dry_run=true` POST writes no rows and no audit events — telling the operator
    otherwise sends them to check state, or start recovery, for nothing.
    """

    def test_a_dry_run_timeout_says_retry(self, real_client: DailyBotClient) -> None:
        with (
            patch("httpx.post", side_effect=httpx.ReadTimeout("slow")),
            pytest.raises(TransportError) as caught,
        ):
            real_client.archive_task("t-1", dry_run=True)
        message: str = str(caught.value)
        assert "may have been applied" not in message
        assert "retry" in message.lower()

    def test_a_real_write_timeout_still_warns(self, real_client: DailyBotClient) -> None:
        with (
            patch("httpx.post", side_effect=httpx.ReadTimeout("slow")),
            pytest.raises(TransportError) as caught,
        ):
            real_client.archive_task("t-1", dry_run=False)
        assert "may have been applied" in str(caught.value)

    def test_a_read_timeout_is_unchanged(self, real_client: DailyBotClient) -> None:
        with (
            patch("httpx.get", side_effect=httpx.ReadTimeout("slow")),
            pytest.raises(TransportError) as caught,
        ):
            real_client.get_task("t-1")
        assert "may have been applied" not in str(caught.value)


class TestPlanRefusalNamesTheRightProduct:
    """Finding 3: a Tasks plan refusal described the agent-report allowlist.

    True of the shared code, and about a different product surface. A reader told
    that "on the free plan the CLI can only submit agent reports and emails" while
    trying to list boards is steered somewhere that cannot help them.
    """

    def _refusal(self) -> APIError:
        return APIError(status_code=403, detail="paid plan", code="plan_upgrade_required")

    def test_a_tasks_door_gets_a_tasks_sentence(self) -> None:
        message: str = resolve_error_message(self._refusal(), door="boards")
        assert "Tasks" in message
        assert "agent reports" not in message

    def test_the_upgrade_url_is_surfaced_when_present(self) -> None:
        exc = APIError(
            status_code=403,
            detail="paid plan",
            code="plan_upgrade_required",
            extra={"upgrade_url": "https://example.com/upgrade"},
        )
        assert "https://example.com/upgrade" in resolve_error_message(exc, door="boards")

    def test_the_shared_message_is_untouched_off_the_tasks_surface(self) -> None:
        # No `door` means this is not a Tasks call; the agent-allowlist sentence is
        # correct there and must not change.
        assert "agent reports" in resolve_error_message(self._refusal())


class TestBoundedPagingIsDocumented:
    """Finding 5: `--limit` looks like "fetch N across pages" and is not.

    Under `paging_options` there is no `--all`, and `--limit` sizes the single page
    the command fetches. An agent assuming `--limit 500` walks the list gets 100
    rows and no signal.
    """

    @pytest.mark.parametrize(
        "argv",
        [
            ["task", "list", "--help"],
            ["tasks", "search", "--help"],
            ["tasks", "inbox", "--help"],
            ["tasks", "mine", "--help"],
        ],
    )
    def test_the_help_says_one_page_per_call(self, runner: CliRunner, argv: list[str]) -> None:
        collapsed: str = " ".join(runner.invoke(cli, argv).stdout.split())
        assert "one page per call" in collapsed
