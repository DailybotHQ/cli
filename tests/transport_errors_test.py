"""Transport and unexpected-error handling (plan task 17).

Reproduced at plan time: `dailybot status --auth` against an unreachable API
printed a raw `httpx.ConnectError` traceback. Only `httpx.TimeoutException` was
handled, in 2 of ~30 command modules, and `api_client.py` caught nothing.

Every test here patches `httpx` at the call site — no network (rule 7).
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import (
    EXIT_TRANSPORT_ERROR,
    APIError,
    DailyBotClient,
    TransportError,
)
from dailybot_cli.main import cli


@pytest.fixture
def client() -> DailyBotClient:
    return DailyBotClient(
        api_url="http://test-api.example.com", token="test-token", api_key="test-api-key"
    )


TRANSPORT_FAILURES: list[tuple[str, Exception]] = [
    ("connect refused", httpx.ConnectError("[Errno 111] Connection refused")),
    ("connect timeout", httpx.ConnectTimeout("timed out")),
    ("read timeout", httpx.ReadTimeout("timed out")),
    ("read error", httpx.ReadError("broken")),
    ("proxy error", httpx.ProxyError("bad proxy")),
    ("unsupported protocol", httpx.UnsupportedProtocol("no scheme")),
    ("remote protocol", httpx.RemoteProtocolError("bad frame")),
    ("pool timeout", httpx.PoolTimeout("exhausted")),
]


class TestEveryTransportFailureBecomesACliError:
    @pytest.mark.parametrize(
        "label,exc", TRANSPORT_FAILURES, ids=[label for label, _ in TRANSPORT_FAILURES]
    )
    def test_no_httpx_exception_escapes_the_client(
        self, client: DailyBotClient, label: str, exc: Exception
    ) -> None:
        with patch("httpx.get", side_effect=exc), pytest.raises(TransportError):
            client.get_tasks_pulse()

    def test_a_transport_error_is_not_an_api_error(self, client: DailyBotClient) -> None:
        # It has no status code and no server `code`, so the ~30 existing
        # `except APIError` blocks are structurally unable to catch it. The root
        # safety net is what covers them.
        assert not issubclass(TransportError, APIError)

    def test_it_carries_the_underlying_cause(self, client: DailyBotClient) -> None:
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            try:
                client.get_tasks_pulse()
            except TransportError as exc:
                assert exc.__cause__ is not None


class TestTheMessageDistinguishesFailureModes:
    def test_unreachable_names_the_url_and_suggests_checking_it(
        self, client: DailyBotClient
    ) -> None:
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            try:
                client.get_tasks_pulse()
            except TransportError as exc:
                message: str = str(exc)
        assert "test-api.example.com" in message
        assert "--api-url" in message or "connection" in message.lower()

    def test_a_timeout_on_a_write_warns_it_may_have_been_applied(
        self, client: DailyBotClient
    ) -> None:
        # A write that timed out is NOT known to have failed. This is the
        # existing update.py wording's whole point and it must survive.
        with patch("httpx.post", side_effect=httpx.ReadTimeout("slow")):
            try:
                client.create_task(title="x")
            except TransportError as exc:
                message = str(exc)
        assert "may have been" in message.lower()

    def test_a_timeout_on_a_read_does_not_warn_about_writes(
        self, client: DailyBotClient
    ) -> None:
        with patch("httpx.get", side_effect=httpx.ReadTimeout("slow")):
            try:
                client.get_tasks_pulse()
            except TransportError as exc:
                message = str(exc)
        assert "may have been" not in message.lower()

    def test_a_malformed_url_says_the_url_is_wrong(self, client: DailyBotClient) -> None:
        with patch("httpx.get", side_effect=httpx.UnsupportedProtocol("no scheme")):
            try:
                client.get_tasks_pulse()
            except TransportError as exc:
                message = str(exc)
        assert "url" in message.lower()


class TestMalformedSuccessBody:
    def test_a_non_json_200_is_a_cli_error_not_a_decode_traceback(
        self, client: DailyBotClient
    ) -> None:
        # A captive portal or proxy page returns 200 with HTML.
        mock: MagicMock = MagicMock(spec=httpx.Response)
        mock.status_code = 200
        mock.json.side_effect = ValueError("Expecting value")
        mock.text = "<html>Captive portal</html>" * 40
        mock.headers = {}
        with patch("httpx.get", return_value=mock), pytest.raises(TransportError) as caught:
            client.get_tasks_pulse()
        assert "unreadable" in str(caught.value).lower()

    def test_the_body_is_truncated_not_dumped(self, client: DailyBotClient) -> None:
        mock = MagicMock(spec=httpx.Response)
        mock.status_code = 200
        mock.json.side_effect = ValueError("nope")
        mock.text = "x" * 5000
        mock.headers = {}
        with patch("httpx.get", return_value=mock):
            try:
                client.get_tasks_pulse()
            except TransportError as exc:
                assert len(str(exc)) < 600


class TestNoSecretLeaks:
    def test_no_credential_appears_in_a_transport_message(self) -> None:
        secret: str = "sk-super-secret-value-1234567890"
        client = DailyBotClient(api_url="http://h.example.com", token=secret, api_key=secret)
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            try:
                client.get_tasks_pulse()
            except TransportError as exc:
                assert secret not in str(exc)


class TestNoRetryIsAdded:
    def test_a_transport_failure_is_reported_not_retried(self, client: DailyBotClient) -> None:
        # Retry policy exists only for a bounded 429. Silently retrying a
        # connection failure hides an outage from whoever owns the decision.
        with (
            patch("httpx.get", side_effect=httpx.ConnectError("refused")) as mock_get,
            pytest.raises(TransportError),
        ):
            client.get_tasks_pulse()
        assert mock_get.call_count == 1


class TestTheRootSafetyNet:
    def test_a_transport_failure_exits_with_the_documented_code(self) -> None:
        runner = CliRunner()
        with patch(
            "dailybot_cli.commands.tasks.require_auth",
            side_effect=TransportError("Could not reach Dailybot at http://x/."),
        ):
            result = runner.invoke(cli, ["tasks", "status"])
        assert result.exit_code == EXIT_TRANSPORT_ERROR
        assert "Traceback" not in result.output

    def test_the_new_exit_code_is_distinct(self) -> None:
        assert EXIT_TRANSPORT_ERROR not in (0, 1, 2, 3, 4, 5, 6, 7, 9)

    def test_it_does_not_swallow_system_exit(self) -> None:
        runner = CliRunner()
        with patch("dailybot_cli.commands.tasks.require_auth", side_effect=SystemExit(3)):
            result = runner.invoke(cli, ["tasks", "status"])
        assert result.exit_code == 3

    def test_it_does_not_swallow_a_usage_error(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["tasks", "search"])  # -q is required
        assert result.exit_code == 2

    def test_it_does_not_swallow_keyboard_interrupt(self) -> None:
        # The net re-raises it; Click's own standalone handling then turns it into
        # an exit. What matters here is that Ctrl-C is NOT reported as a bug — the
        # "Unexpected error ... please report it" path would be wrong and noisy.
        runner = CliRunner()
        with patch("dailybot_cli.commands.tasks.require_auth", side_effect=KeyboardInterrupt()):
            result = runner.invoke(cli, ["tasks", "status"])
        assert "unexpected error" not in result.output.lower()
        assert "please report it" not in result.output.lower()


class TestHookContractSurvives:
    def test_a_hook_still_exits_zero_when_the_api_is_unreachable(self) -> None:
        # docs/AGENT_HOOKS.md: always exit 0, never break the agent harness.
        runner = CliRunner()
        with patch(
            "dailybot_cli.ledger.evaluate_stop",
            side_effect=httpx.ConnectError("refused"),
        ):
            result = runner.invoke(cli, ["hook", "stop", "--format", "claude"])
        assert result.exit_code == 0
