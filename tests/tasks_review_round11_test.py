"""Regression tests for the CI AI review's eleventh pass on PR #85.

Five findings, and the two serious ones are both about a fix reaching past its own
boundary.

`TransportError` was introduced to stop transport failures surfacing as tracebacks.
Making it a bare `Exception` meant the ~25 pre-existing `except (APIError,
httpx.HTTPError)` handlers in the TUI and the interactive menu stopped catching
them — so a timeout that used to print "that took longer than expected" inside the
app now killed the app. **Wrapping a failure must not make it less catchable than
it was before.**

And the idempotency key, added in round 8 so a timed-out write could be retried
safely, was attached to the response body — which the timed-out call does not have.
The one case the feature exists for was the one case it did not cover.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import (
    APIError,
    DailyBotClient,
    TransportError,
    TransportTimeout,
)
from dailybot_cli.commands.public_api_helpers import (
    ERROR_CODE_MESSAGES,
    EXIT_USER_ABORTED,
)
from dailybot_cli.main import cli

EXIT_TRANSPORT: int = 8


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


@pytest.fixture
def real_client() -> DailyBotClient:
    return DailyBotClient(api_url="http://t.example.com", token="t", api_key="k")


_PREVIEW: dict[str, Any] = {"operation": "task.archive", "dry_run": True, "reversible": True}


def _emitted(stdout: str) -> dict[str, Any]:
    """The JSON document the program wrote.

    CliRunner echoes the keystrokes it feeds to a prompt onto stdout itself, so the
    raw stream starts with the typed answer. That is the harness, not the CLI — the
    program wrote only the last line, and the prompt went to stderr.
    """
    return json.loads(stdout.strip().splitlines()[-1])


class TestTheWrapperStaysCatchable:
    """Finding 1: the wrapper walked past every handler that already existed.

    `dailybot_cli/tui/app.py` carries ~25 `except (APIError, httpx.HTTPError)`
    blocks and `commands/interactive.py` an `except httpx.TimeoutException`. A
    `TransportError` that subclassed nothing reached none of them: the Textual app
    died instead of showing its message, and the interactive menu exited 8 instead
    of returning to the menu.
    """

    def test_it_is_an_httpx_error(self) -> None:
        assert issubclass(TransportError, httpx.HTTPError)

    def test_a_timeout_is_still_a_timeout(self) -> None:
        # The TUI distinguishes "took longer than expected" from "couldn't reach
        # Dailybot"; collapsing them would lose the more useful of the two.
        assert issubclass(TransportTimeout, httpx.TimeoutException)
        assert issubclass(TransportTimeout, TransportError)

    def test_it_is_not_an_api_error(self) -> None:
        # The other half of the contract: `except APIError` must NOT treat a dead
        # network as a server verdict.
        assert not issubclass(TransportError, APIError)

    def test_a_connect_failure_is_caught_by_the_broad_handler(
        self, real_client: DailyBotClient
    ) -> None:
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            try:
                real_client.get_task("t-1")
            except (APIError, httpx.HTTPError) as exc:
                assert isinstance(exc, TransportError)
            else:  # pragma: no cover - the call above always raises
                pytest.fail("expected a transport failure")

    def test_a_timeout_is_caught_by_the_narrow_handler(self, real_client: DailyBotClient) -> None:
        with patch("httpx.get", side_effect=httpx.ReadTimeout("slow")):
            try:
                real_client.get_task("t-1")
            except httpx.TimeoutException as exc:
                assert isinstance(exc, TransportTimeout)
            else:  # pragma: no cover - the call above always raises
                pytest.fail("expected a timeout")


class TestTheKeyReachesTheCallThatNeedsIt:
    """Finding 2: the key was on the response body a timed-out call never gets.

    Round 8 surfaced `_idempotency_key` so a retry could reuse it. It was attached
    after `_request` returned — so on the timeout, the exact case the feature
    exists for, it was discarded and the next invocation minted a new uuid4 the
    server could not replay.
    """

    def test_the_error_carries_the_key(self, real_client: DailyBotClient) -> None:
        with (
            patch("httpx.post", side_effect=httpx.ReadTimeout("slow")),
            pytest.raises(TransportError) as caught,
        ):
            real_client.create_task(title="x")
        assert caught.value.idempotency_key

    def test_an_explicit_key_comes_back_unchanged(self, real_client: DailyBotClient) -> None:
        with (
            patch("httpx.post", side_effect=httpx.ReadTimeout("slow")),
            pytest.raises(TransportError) as caught,
        ):
            real_client.create_task(title="x", idempotency_key="mine-1")
        assert caught.value.idempotency_key == "mine-1"

    def test_a_read_carries_none(self, real_client: DailyBotClient) -> None:
        with (
            patch("httpx.get", side_effect=httpx.ReadTimeout("slow")),
            pytest.raises(TransportError) as caught,
        ):
            real_client.get_task("t-1")
        assert caught.value.idempotency_key is None

    def test_the_cli_prints_it(self, runner: CliRunner, client: MagicMock) -> None:
        client.create_task.side_effect = TransportError("timed out", idempotency_key="key-7")
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(cli, ["task", "create", "-t", "x"])
        assert result.exit_code == EXIT_TRANSPORT
        assert "key-7" in result.stderr
        assert "--idempotency-key" in result.stderr

    def test_json_mode_carries_it(self, runner: CliRunner, client: MagicMock) -> None:
        client.create_task.side_effect = TransportError("timed out", idempotency_key="key-7")
        with (
            patch("dailybot_cli.commands.task.require_auth", return_value=client),
            patch("sys.argv", ["dailybot", "task", "create", "-t", "x", "--json"]),
        ):
            result = runner.invoke(cli, ["task", "create", "-t", "x", "--json"])
        assert json.loads(result.stdout)["idempotency_key"] == "key-7"


class TestOtpTimeoutsDoNotBurnTheCode:
    """Finding 3: the generic write advice destroys the thing it is protecting.

    "A write that timed out may have been applied — check the state before
    retrying" is right for a task. For `request_code` it is wrong: asking again
    **invalidates the code already in the inbox** (AGENTS.md DON'T #17). For
    `verify_code` a timeout may have consumed the code, so the user needs a new one
    rather than another attempt at the spent one.
    """

    def test_request_code_says_check_the_inbox(self, real_client: DailyBotClient) -> None:
        with (
            patch("httpx.post", side_effect=httpx.ReadTimeout("slow")),
            pytest.raises(TransportError) as caught,
        ):
            real_client.request_code("me@example.com")
        message: str = str(caught.value)
        assert "inbox" in message
        assert "may have been applied" not in message

    def test_verify_code_says_request_a_new_one(self, real_client: DailyBotClient) -> None:
        with (
            patch("httpx.post", side_effect=httpx.ReadTimeout("slow")),
            pytest.raises(TransportError) as caught,
        ):
            real_client.verify_code("me@example.com", "123456")
        message: str = str(caught.value)
        assert "new one" in message
        assert "may have been applied" not in message

    def test_a_connection_failure_keeps_the_ordinary_message(
        self, real_client: DailyBotClient
    ) -> None:
        # The override is for timeouts only: a refused connection sent nothing, so
        # the ordinary "could not reach" wording is correct.
        with (
            patch("httpx.post", side_effect=httpx.ConnectError("refused")),
            pytest.raises(TransportError) as caught,
        ):
            real_client.request_code("me@example.com")
        assert "Could not reach" in str(caught.value)


class TestDecliningThePromptIsStillParseable:
    """Finding 4: answering "no" under `--json` exited 7 with empty stdout.

    The preview-failure branch beside it emits an envelope for exactly this reason.
    An abort is a refusal the caller can act on, not a crash.
    """

    def test_the_destructive_flow_emits_an_envelope(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.archive_task.return_value = _PREVIEW
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(cli, ["task", "archive", "t-1", "--json"], input="n\n")
        assert result.exit_code == EXIT_USER_ABORTED
        assert _emitted(result.stdout)["code"] == "user_aborted"

    def test_bulk_emits_the_same_envelope(
        self, runner: CliRunner, client: MagicMock, tmp_path: Any
    ) -> None:
        batch = tmp_path / "b.json"
        batch.write_text('[{"uuid": "t-1"}]')
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(
                cli,
                ["task", "bulk", "--operation", "archive", "-f", str(batch), "--json"],
                input="n\n",
            )
        assert result.exit_code == EXIT_USER_ABORTED
        assert _emitted(result.stdout)["code"] == "user_aborted"
        client.bulk_tasks.assert_not_called()

    def test_without_json_the_abort_is_prose(self, runner: CliRunner, client: MagicMock) -> None:
        client.archive_task.return_value = _PREVIEW
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(cli, ["task", "archive", "t-1"], input="n\n")
        assert "Aborted" in result.stderr


class TestRecoveryAdviceNamesSomethingThatExists:
    """Finding 5: `state_in_use` told the operator to pass a flag the CLI lacks.

    `migrate_to` appears nowhere in the command surface. Advice that cannot be
    followed is worse than admitting the limit, because the reader spends time
    looking for the flag before concluding the message was wrong.
    """

    def test_the_message_names_the_flag_that_now_exists(self) -> None:
        # PR2 of the Tasks Beta built `board state archive --migrate-to`, so the
        # advice points at it — and the test below proves the flag is declared.
        message: str = ERROR_CODE_MESSAGES["state_in_use"]
        assert "--migrate-to" in message

    def test_the_documented_tables_list_the_abort(self) -> None:
        import pathlib

        # An exit code the branching table omits is an exit code an agent treats as
        # an unknown failure — and the obvious "recovery" for a declined archive is
        # to re-run it with --yes, skipping the prompt the human just refused.
        repo: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent
        table: str = (repo / "docs/API_REFERENCE.md").read_text()
        assert "user_aborted" in table
        assert "--yes" in table

    def test_the_advised_flag_is_declared_by_a_command(self) -> None:
        import pathlib

        repo: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent
        declared = [
            str(path.relative_to(repo))
            for path in (repo / "dailybot_cli").rglob("*.py")
            if "--migrate-to" in path.read_text()
        ]
        # Advice must name something that exists: if this ever empties, the message
        # above has to stop promising the flag.
        assert "dailybot_cli/commands/board.py" in declared, declared


class TestAnUnreadableSuccessAlsoCarriesTheKey:
    """Grok's first review: the round-11 fix guarded one of two paths.

    `_handle_response` raises `TransportError` for an unreadable 2xx — a captive
    portal's HTML 200 — and that happens *after* the POST reached the server. The
    attach-and-reraise only wrapped `_request`, so this path left the key unset and
    a blind retry would mint a fresh uuid4 and duplicate the write.
    """

    def _html_200(self) -> MagicMock:
        mock: MagicMock = MagicMock(spec=httpx.Response)
        mock.status_code = 200
        mock.json.side_effect = ValueError("Expecting value")
        mock.headers = {}
        mock.text = "<html>captive portal</html>"
        return mock

    def test_the_key_survives_an_unreadable_2xx(self, real_client: DailyBotClient) -> None:
        with (
            patch("httpx.post", return_value=self._html_200()),
            pytest.raises(TransportError) as caught,
        ):
            real_client.create_task(title="x")
        assert caught.value.idempotency_key

    def test_an_explicit_key_is_the_one_returned(self, real_client: DailyBotClient) -> None:
        with (
            patch("httpx.post", return_value=self._html_200()),
            pytest.raises(TransportError) as caught,
        ):
            real_client.create_task(title="x", idempotency_key="mine-2")
        assert caught.value.idempotency_key == "mine-2"

    def test_a_read_still_carries_none(self, real_client: DailyBotClient) -> None:
        # Reads send no key, so there is nothing to attach — and claiming one
        # would invite a pointless --idempotency-key on a GET.
        with (
            patch("httpx.get", return_value=self._html_200()),
            pytest.raises(TransportError) as caught,
        ):
            real_client.get_task("t-1")
        assert caught.value.idempotency_key is None

    def test_the_cli_surfaces_it(self, runner: CliRunner, client: MagicMock) -> None:
        client.create_task.side_effect = TransportError(
            "unreadable response", idempotency_key="key-11"
        )
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(cli, ["task", "create", "-t", "x"])
        assert "key-11" in result.stderr
