"""`dailybot logout` revokes a device-flow pair (PLAN_002 T-logout-pair, DEVICE_FLOW_WIRE §5).

Bearer form while the access token is valid; the `{"refresh": ...}` body form when it
has expired (locally, or as the server answers), with no refresh round-trip. Legacy
tokens keep today's request byte for byte.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner, Result

from dailybot_cli.api_client import DailyBotClient
from dailybot_cli.config import load_credentials, save_credentials
from dailybot_cli.main import cli
from tests.wire_fixture_loader import fixture_response

API: str = "https://api.example.com"
ACCESS: str = "dbc_at_live-access"
REFRESH: str = "dbc_rt_live-refresh"
LOGOUT_URL: str = f"{API}/v1/cli/auth/logout/"
FUTURE: str = "2999-01-01T00:00:00Z"
PAST: str = "2000-01-01T00:00:00Z"


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DAILYBOT_API_KEY", "DAILYBOT_CLI_TOKEN", "DAILYBOT_API_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _save_pair(expires_at: str = FUTURE) -> None:
    save_credentials(
        token=ACCESS,
        email="me@example.com",
        organization="My Team",
        organization_uuid="org-1",
        api_url=API,
        refresh=REFRESH,
        expires_at=expires_at,
        refresh_expires_at=FUTURE,
    )


def _logout(runner: CliRunner) -> tuple[Result, MagicMock]:
    with patch(
        "dailybot_cli.api_client.httpx.post", return_value=fixture_response("logout_200")
    ) as post:
        result: Result = runner.invoke(cli, ["logout"])
    return result, post


class TestPairLogout:
    def test_a_valid_access_uses_the_bearer_form(self, runner: CliRunner) -> None:
        _save_pair()
        result, post = _logout(runner)
        assert result.exit_code == 0, result.output
        assert post.call_count == 1
        assert post.call_args.args[0] == LOGOUT_URL
        assert post.call_args.kwargs["headers"]["Authorization"] == f"Bearer {ACCESS}"
        assert "json" not in post.call_args.kwargs
        assert load_credentials() is None

    def test_an_expired_access_uses_the_refresh_body_without_refreshing(
        self, runner: CliRunner
    ) -> None:
        _save_pair(expires_at=PAST)
        result, post = _logout(runner)
        assert result.exit_code == 0, result.output
        assert [c.args[0] for c in post.call_args_list] == [LOGOUT_URL]
        assert post.call_args.kwargs["json"] == {"refresh": REFRESH}
        assert "Authorization" not in post.call_args.kwargs["headers"]
        assert "X-API-KEY" not in post.call_args.kwargs["headers"]
        assert load_credentials() is None

    def test_a_server_expired_access_retries_with_the_refresh_body(self, runner: CliRunner) -> None:
        _save_pair()
        with patch(
            "dailybot_cli.api_client.httpx.post",
            side_effect=[
                fixture_response("bearer_access_token_expired_401"),
                fixture_response("logout_200"),
            ],
        ) as post:
            result: Result = runner.invoke(cli, ["logout"])
        assert result.exit_code == 0, result.output
        assert [c.args[0] for c in post.call_args_list] == [LOGOUT_URL, LOGOUT_URL]
        assert post.call_args_list[1].kwargs["json"] == {"refresh": REFRESH}
        assert "Authorization" not in post.call_args_list[1].kwargs["headers"]
        assert load_credentials() is None

    def test_an_already_revoked_family_still_logs_out(self, runner: CliRunner) -> None:
        _save_pair(expires_at=PAST)
        result, _post = _logout(runner)
        assert result.exit_code == 0
        assert "Logged out" in result.output
        assert load_credentials() is None

    def test_a_failed_revocation_says_so(self, runner: CliRunner) -> None:
        _save_pair()
        with patch(
            "dailybot_cli.api_client.httpx.post",
            return_value=fixture_response("refresh_user_disabled_401"),
        ):
            result: Result = runner.invoke(cli, ["logout"])
        assert result.exit_code == 0
        assert "could not revoke" in result.output.lower()
        assert load_credentials() is None

    def test_tokens_never_reach_the_output(self, runner: CliRunner) -> None:
        _save_pair(expires_at=PAST)
        result, _post = _logout(runner)
        assert ACCESS not in result.output
        assert REFRESH not in result.output


class TestLegacyLogout:
    def test_a_legacy_token_keeps_todays_request(self, runner: CliRunner) -> None:
        save_credentials(
            token="legacy-test-token",
            email="me@example.com",
            organization="O",
            organization_uuid="org-1",
            api_url=API,
        )
        result, post = _logout(runner)
        assert result.exit_code == 0, result.output
        assert post.call_count == 1
        assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer legacy-test-token"
        assert "json" not in post.call_args.kwargs
        assert load_credentials() is None


class TestClientLogout:
    def test_the_refresh_body_form(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API, token=ACCESS, api_key="test-key")
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=fixture_response("logout_200")
        ) as post:
            result: dict[str, Any] = client.logout(refresh=REFRESH, access_expired=True)
        assert result == {"detail": "Successfully logged out."}
        headers: dict[str, str] = post.call_args.kwargs["headers"]
        assert "Authorization" not in headers and "X-API-KEY" not in headers

    def test_without_a_refresh_it_is_todays_call(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API, token="legacy-test-token")
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=fixture_response("logout_200")
        ) as post:
            client.logout()
        assert post.call_count == 1
        assert "json" not in post.call_args.kwargs
