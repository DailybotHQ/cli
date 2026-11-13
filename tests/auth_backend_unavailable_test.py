"""`503 auth_backend_unavailable` is transient, never a logout (PLAN_002 T-auth-backend-503).

Frozen (W1, L38): `Retry-After: 2`, server range 1-5 s; the CLI retries 3 times,
each waiting `min(Retry-After, 5)`. CLI tokens are DB-validated and should never
meet this 503; the handling is defensive and must never refresh, fall back to the
API key, or touch `credentials.json`.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner, Result

from dailybot_cli.api_client import (
    AUTH_BACKEND_MAX_RETRIES,
    AUTH_BACKEND_MAX_WAIT_SECS,
    APIError,
    DailyBotClient,
)
from dailybot_cli.commands.public_api_helpers import EXIT_RATE_LIMITED, exit_for_api_error
from dailybot_cli.config import save_credentials
from dailybot_cli.main import cli
from tests.wire_fixture_loader import fixture_response

API: str = "https://api.example.com"
SLEEP: str = "dailybot_cli.api_client.time.sleep"


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DAILYBOT_API_KEY", "DAILYBOT_CLI_TOKEN", "DAILYBOT_API_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def pair_file(_isolated_environment: Path) -> Path:
    save_credentials(
        token="dbc_at_access",
        email="me@example.com",
        organization="My Team",
        organization_uuid="org-1",
        api_url=API,
        refresh="dbc_rt_refresh",
        expires_at="2999-01-01T00:00:00Z",
        refresh_expires_at="2999-01-01T00:00:00Z",
    )
    return _isolated_environment / "credentials.json"


def _unavailable(retry_after: str | None = "2") -> MagicMock:
    response: MagicMock = fixture_response("auth_backend_unavailable_503")
    response.headers = {} if retry_after is None else {"Retry-After": retry_after}
    return response


def _ok() -> MagicMock:
    response: MagicMock = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.json.return_value = {"ok": True}
    return response


class TestBoundedRetry:
    def test_the_budget_then_a_transient_error(self, pair_file: Path) -> None:
        before: bytes = pair_file.read_bytes()
        client: DailyBotClient = DailyBotClient(api_url=API, api_key="test-key")
        with (
            patch(SLEEP) as sleep,
            patch(
                "dailybot_cli.api_client.httpx.get",
                side_effect=[_unavailable() for _ in range(AUTH_BACKEND_MAX_RETRIES + 1)],
            ) as get,
            patch("dailybot_cli.api_client.httpx.post") as post,
            pytest.raises(APIError) as caught,
        ):
            client.get_status()
        assert caught.value.status_code == 503
        assert caught.value.code == "auth_backend_unavailable"
        assert "Session expired" not in caught.value.detail
        assert get.call_count == AUTH_BACKEND_MAX_RETRIES + 1 == 4
        assert [c.args[0] for c in sleep.call_args_list] == [2.0, 2.0, 2.0]
        post.assert_not_called()  # no refresh
        for call in get.call_args_list:
            assert "X-API-KEY" not in call.kwargs["headers"]  # no API-key fallback
        assert pair_file.read_bytes() == before

    def test_a_recovery_inside_the_budget_succeeds(self, pair_file: Path) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API)
        with (
            patch(SLEEP) as sleep,
            patch("dailybot_cli.api_client.httpx.get", side_effect=[_unavailable(), _ok()]),
        ):
            assert client.get_status() == {"ok": True}
        assert sleep.call_count == 1

    @pytest.mark.parametrize(
        "header,wait", [("1", 1.0), ("9", AUTH_BACKEND_MAX_WAIT_SECS), (None, 2.0), ("soon", 2.0)]
    )
    def test_retry_after_is_honoured_and_capped(
        self, pair_file: Path, header: str | None, wait: float
    ) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API)
        with (
            patch(SLEEP) as sleep,
            patch("dailybot_cli.api_client.httpx.get", side_effect=[_unavailable(header), _ok()]),
        ):
            client.get_status()
        assert sleep.call_args.args[0] == wait

    def test_the_agent_path_retries_too(self, pair_file: Path) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API, api_key="test-key")
        with (
            patch(SLEEP),
            patch(
                "dailybot_cli.api_client.httpx.request", side_effect=[_unavailable(), _ok()]
            ) as request,
        ):
            client.get_agent_health(agent_name="a")
        assert request.call_count == 2
        assert (
            request.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer dbc_at_access"
        )

    def test_a_plain_503_is_not_retried(self, pair_file: Path) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API)
        plain: MagicMock = _ok()
        plain.status_code = 503
        plain.json.return_value = {"detail": "Maintenance."}
        with (
            patch(SLEEP) as sleep,
            patch("dailybot_cli.api_client.httpx.get", return_value=plain),
            pytest.raises(APIError),
        ):
            client.get_status()
        sleep.assert_not_called()


class TestRendering:
    def test_a_transient_message_and_the_wait_and_retry_exit(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        error: APIError = APIError(503, "x", code="auth_backend_unavailable", retry_after=2.0)
        with pytest.raises(SystemExit) as caught:
            exit_for_api_error(error, json_mode=False)
        assert caught.value.code == EXIT_RATE_LIMITED
        err: str = capsys.readouterr().err
        assert "temporarily unavailable" in err.lower()
        assert "login" not in err.lower()

    def test_json_mode_carries_the_code(self, capsys: pytest.CaptureFixture[str]) -> None:
        error: APIError = APIError(503, "x", code="auth_backend_unavailable", retry_after=2.0)
        with pytest.raises(SystemExit):
            exit_for_api_error(error, json_mode=True)
        payload: dict[str, Any] = json.loads(capsys.readouterr().out)
        assert payload["code"] == "auth_backend_unavailable"
        assert payload["status"] == 503


def test_logout_on_503_keeps_the_credentials(pair_file: Path) -> None:
    before: bytes = pair_file.read_bytes()
    with (
        patch(SLEEP),
        patch(
            "dailybot_cli.api_client.httpx.post",
            side_effect=[_unavailable() for _ in range(AUTH_BACKEND_MAX_RETRIES + 1)],
        ),
    ):
        result: Result = CliRunner().invoke(cli, ["logout"])
    assert result.exit_code == EXIT_RATE_LIMITED
    assert pair_file.read_bytes() == before
    assert "Logged out" not in result.output
