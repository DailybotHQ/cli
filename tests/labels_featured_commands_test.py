"""Tests for label and featured commands."""

from typing import Any
from unittest.mock import MagicMock

from click.testing import CliRunner

from dailybot_cli.main import cli


def _client(monkeypatch: Any) -> MagicMock:
    client = MagicMock()
    monkeypatch.setattr("dailybot_cli.commands.public_api_helpers.get_agent_auth", lambda: "tok")
    monkeypatch.setattr(
        "dailybot_cli.commands.public_api_helpers.DailyBotClient", lambda *a, **k: client
    )
    return client


def test_label_list_renders(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.list_labels.return_value = {
        "count": 1,
        "results": [
            {
                "name": "Release",
                "uuid": "lbl-1",
                "color": "#4A90E2",
                "usage": {"total": 2},
                "is_archived": False,
            }
        ],
    }
    result = CliRunner().invoke(cli, ["label", "list"])
    assert result.exit_code == 0
    assert "Release" in result.output


def test_featured_list_json(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.list_featured.return_value = {
        "entity_type": "forms",
        "entity_uuids": ["form-1", "form-2"],
    }
    result = CliRunner().invoke(
        cli,
        ["featured", "list", "--entity-type", "forms", "--json"],
    )
    assert result.exit_code == 0
    assert "form-1" in result.output


def test_featured_set_calls_client(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.set_featured.return_value = {
        "entity_type": "checkins",
        "entity_uuid": "chk-1",
        "is_featured": True,
    }
    result = CliRunner().invoke(
        cli,
        ["featured", "set", "chk-1", "--entity-type", "checkins", "--json"],
    )
    assert result.exit_code == 0
    client.set_featured.assert_called_once_with("checkins", "chk-1", featured=True)
