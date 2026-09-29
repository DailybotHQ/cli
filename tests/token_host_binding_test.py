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
