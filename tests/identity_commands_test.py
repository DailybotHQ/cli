"""Tests for the me / org / user get read-only commands (Task 7)."""

from typing import Any
from unittest.mock import MagicMock

from click.testing import CliRunner

from dailybot_cli.api_client import APIError
from dailybot_cli.main import cli


def _auth_client(monkeypatch: Any) -> MagicMock:
    client = MagicMock()
    monkeypatch.setattr("dailybot_cli.commands.public_api_helpers.get_agent_auth", lambda: "tok")
    monkeypatch.setattr(
        "dailybot_cli.commands.public_api_helpers.DailyBotClient", lambda *a, **k: client
    )
    return client


def test_me_renders_profile(monkeypatch: Any) -> None:
    client = _auth_client(monkeypatch)
    client.get_me.return_value = {
        "full_name": "Jane Doe",
        "role": "ADMIN_ORG",
        "organization_name": "Acme",
    }
    result = CliRunner().invoke(cli, ["me"])
    assert result.exit_code == 0
    assert "Jane Doe" in result.output
    client.get_me.assert_called_once_with(include_email=False)


def test_me_json_and_include_email(monkeypatch: Any) -> None:
    client = _auth_client(monkeypatch)
    client.get_me.return_value = {"full_name": "Jane", "email": "jane@example.com"}
    result = CliRunner().invoke(cli, ["me", "--include-email", "--json"])
    assert result.exit_code == 0
    assert "jane@example.com" in result.output
    client.get_me.assert_called_once_with(include_email=True)


def test_org_renders(monkeypatch: Any) -> None:
    client = _auth_client(monkeypatch)
    client.get_organization.return_value = {"name": "Acme", "uuid": "org-1"}
    result = CliRunner().invoke(cli, ["org"])
    assert result.exit_code == 0
    assert "Acme" in result.output


def test_user_get_renders(monkeypatch: Any) -> None:
    client = _auth_client(monkeypatch)
    client.get_user.return_value = {"full_name": "Bob", "uuid": "u-1"}
    result = CliRunner().invoke(cli, ["user", "get", "u-1"])
    assert result.exit_code == 0
    assert "Bob" in result.output
    client.get_user.assert_called_once_with("u-1", include_email=False)


def test_me_handles_api_error(monkeypatch: Any) -> None:
    client = _auth_client(monkeypatch)
    client.get_me.side_effect = APIError(401, "Unauthorized")
    result = CliRunner().invoke(cli, ["me", "--json"])
    assert result.exit_code == 3
