"""Task 4: API-key ↔ Bearer parity on all endpoints."""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import DailyBotClient
from dailybot_cli.commands.auth import logout


def test_user_scoped_endpoint_uses_api_key_when_no_token() -> None:
    """With only an API key configured, X-API-KEY is attached on a non-agent call."""
    client = DailyBotClient(api_url="http://test-api.example.com", token=None, api_key="key-123")
    resp: MagicMock = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"count": 0, "next": None, "results": []}
    with patch("httpx.get", return_value=resp) as mock_get:
        client.list_forms()
    headers: dict[str, Any] = mock_get.call_args[1]["headers"]
    assert headers.get("X-API-KEY") == "key-123"
    assert "Authorization" not in headers


def test_bearer_preferred_when_both_present() -> None:
    client = DailyBotClient(api_url="http://test-api.example.com", token="tok", api_key="key-123")
    resp: MagicMock = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"count": 0, "next": None, "results": []}
    with patch("httpx.get", return_value=resp) as mock_get:
        client.list_forms()
    headers: dict[str, Any] = mock_get.call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer tok"


def test_logout_with_only_api_key_sends_no_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("dailybot_cli.commands.auth.get_token", lambda: None)
    monkeypatch.setattr("dailybot_cli.commands.auth.get_api_key", lambda: "key-123")
    runner = CliRunner()
    with patch("httpx.post") as mock_post:
        result = runner.invoke(logout, [])
    assert mock_post.call_count == 0  # no doomed X-API-KEY logout request
    assert result.exit_code == 0
    assert "login" in result.output.lower()


def test_logout_with_bearer_proceeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dailybot_cli.commands.auth.get_token", lambda: "tok")
    resp: MagicMock = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"detail": "ok"}
    with (
        patch("httpx.post", return_value=resp) as mock_post,
        patch("dailybot_cli.commands.auth.clear_credentials"),
    ):
        runner = CliRunner()
        result = runner.invoke(logout, [])
    assert mock_post.call_count == 1
    assert result.exit_code == 0
