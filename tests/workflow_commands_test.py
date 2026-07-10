"""Tests for the workflow read commands (Task 9)."""

from typing import Any
from unittest.mock import MagicMock

from click.testing import CliRunner

from dailybot_cli.api_client import APIError
from dailybot_cli.main import cli


def _client(monkeypatch: Any) -> MagicMock:
    client = MagicMock()
    monkeypatch.setattr("dailybot_cli.commands.public_api_helpers.get_agent_auth", lambda: "tok")
    monkeypatch.setattr(
        "dailybot_cli.commands.public_api_helpers.DailyBotClient", lambda *a, **k: client
    )
    return client


def test_workflow_list_renders(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.list_workflows.return_value = [
        {"name": "Deploy", "uuid": "w-1", "trigger_type": "manual", "active": True, "total_runs": 3}
    ]
    result = CliRunner().invoke(cli, ["workflow", "list"])
    assert result.exit_code == 0
    assert "Deploy" in result.output
    assert "Showing" in result.output


def test_workflow_get_renders(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.get_workflow.return_value = {"name": "Deploy", "uuid": "w-1"}
    result = CliRunner().invoke(cli, ["workflow", "get", "w-1"])
    assert result.exit_code == 0
    assert "Deploy" in result.output
    client.get_workflow.assert_called_once_with("w-1")


def test_workflow_list_plan_gated_403(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.list_workflows.side_effect = APIError(
        403, "upgrade", code="plan_upgrade_required", extra={"upgrade_url": "https://x/up"}
    )
    result = CliRunner().invoke(cli, ["workflow", "list", "--json"])
    assert result.exit_code == 4
    assert "upgrade" in result.output.lower()
