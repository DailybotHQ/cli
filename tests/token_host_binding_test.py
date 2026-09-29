"""A login token only travels to the API host it was issued for.

`dailybot login` stores the Bearer token next to the `api_url` it was issued
by. When `.dailybot/env.json` (or `--api-url`) points the CLI at another host,
that token must not ride along — not as the first credential and not as the
401/403 fallback. Every test sandboxes the config dir; no network (rule 7).
"""

import contextlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from dailybot_cli import config
from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.config import get_login_token_for, save_credentials

PROD: str = "https://api.dailybot.com"
LOCAL: str = "http://host.docker.internal:8000"


@pytest.fixture(autouse=True)
def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILYBOT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("DAILYBOT_CLI_TOKEN", raising=False)
    monkeypatch.delenv("DAILYBOT_API_KEY", raising=False)
    monkeypatch.setattr(config, "_api_url_override", None)


def _login(api_url: str | None = PROD) -> None:
    save_credentials(
        token="prod-session-token",
        email="me@example.com",
        organization="My Org",
        organization_uuid="org-1",
        **({"api_url": api_url} if api_url else {}),
    )


class TestGetLoginTokenFor:
    def test_same_host_gets_the_token(self) -> None:
        _login()
        assert get_login_token_for(PROD) == "prod-session-token"
        assert get_login_token_for(PROD + "/") == "prod-session-token"

    def test_a_default_port_is_the_same_origin(self) -> None:
        _login()
        assert get_login_token_for("https://api.dailybot.com:443") == "prod-session-token"
        assert get_login_token_for("https://api.dailybot.com:8443") is None

    def test_another_host_gets_nothing(self) -> None:
        _login()
        assert get_login_token_for(LOCAL) is None
        assert get_login_token_for("https://api.dailybot.com.evil.example") is None
        assert get_login_token_for("http://api.dailybot.com") is None

    def test_a_legacy_login_without_api_url_belongs_to_the_default_host(self) -> None:
        _login(api_url=None)
        creds = config.load_credentials()
        assert creds is not None
        creds.pop("api_url", None)
        config._credentials_path().write_text(__import__("json").dumps(creds))
        assert get_login_token_for(PROD) == "prod-session-token"
        assert get_login_token_for(LOCAL) is None

    def test_an_explicit_env_token_is_the_callers_choice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DAILYBOT_CLI_TOKEN", "ci-token")
        assert get_login_token_for(LOCAL) == "ci-token"


class TestClientNeverCarriesTheTokenElsewhere:
    def _response(self, status: int) -> MagicMock:
        mock: MagicMock = MagicMock(spec=httpx.Response)
        mock.status_code = status
        mock.json.return_value = {"code": "insufficient_scope", "detail": "no"}
        mock.headers = {}
        return mock

    def test_a_local_client_has_no_production_token(self) -> None:
        _login()
        assert DailyBotClient(api_url=LOCAL, api_key="local-key").token is None

    def test_a_refused_key_is_not_retried_with_the_production_token(self) -> None:
        _login()
        client: DailyBotClient = DailyBotClient(
            api_url=LOCAL, api_key="local-key", prefer_api_key=True
        )
        with (
            patch("httpx.post", return_value=self._response(403)) as mock_post,
            contextlib.suppress(APIError),
        ):
            client.comment_on_task("7f1c2b3a-0000-4000-8000-000000000001", body="x")
        for call in mock_post.call_args_list:
            assert "Authorization" not in call.kwargs["headers"]

    def test_the_home_host_still_uses_the_token(self) -> None:
        _login()
        assert DailyBotClient(api_url=PROD).token == "prod-session-token"


class TestPreflightsAskTheCurrentHost:
    """A production login on disk must not satisfy a testing host's person preflight."""

    def test_person_token_follows_the_current_api(self) -> None:
        _login()
        config.set_api_url_override(LOCAL)
        assert config.get_person_token() is None
        config.set_api_url_override(PROD)
        assert config.get_person_token() == "prod-session-token"


class TestLogoutRevokesOnTheIssuingHost:
    def test_logout_posts_to_the_login_host_even_when_env_points_elsewhere(self) -> None:
        from click.testing import CliRunner

        from dailybot_cli.main import cli

        _login()
        response: MagicMock = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.json.return_value = {}
        response.headers = {}
        with patch("httpx.post", return_value=response) as post:
            result = CliRunner().invoke(cli, ["--api-url", LOCAL, "logout"])
        assert result.exit_code == 0, result.output
        assert post.call_args.args[0] == f"{PROD}/v1/cli/auth/logout/"
        headers: dict[str, str] = post.call_args.kwargs["headers"]
        assert headers.get("Authorization") == "Bearer prod-session-token"
        assert "X-API-KEY" not in headers

    def test_http_and_https_are_different_hosts(self) -> None:
        _login()
        assert get_login_token_for("http://api.dailybot.com") is None


class TestLogoutWithAnEnvToken:
    def test_env_token_is_revoked_on_the_current_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from click.testing import CliRunner

        from dailybot_cli.main import cli

        _login()
        monkeypatch.setenv("DAILYBOT_CLI_TOKEN", "ci-token")
        response: MagicMock = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.json.return_value = {}
        response.headers = {}
        with patch("httpx.post", return_value=response) as post:
            result = CliRunner().invoke(cli, ["--api-url", LOCAL, "logout"])
        assert result.exit_code == 0, result.output
        calls = [(c.args[0], c.kwargs["headers"]["Authorization"]) for c in post.call_args_list]
        assert calls == [
            (f"{LOCAL}/v1/cli/auth/logout/", "Bearer ci-token"),
            (f"{PROD}/v1/cli/auth/logout/", "Bearer prod-session-token"),
        ]
        assert config.load_credentials() is None
