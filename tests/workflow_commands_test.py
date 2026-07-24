"""Tests for the workflow list / get / trigger commands."""

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


def test_workflow_list_filter_api_trigger(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.list_workflows.return_value = [
        {"name": "Deploy", "uuid": "w-1", "trigger_type": "api_trigger", "active": True},
        {
            "name": "Nightly",
            "uuid": "w-2",
            "trigger_type": "scheduled_task_execution",
            "active": True,
        },
    ]
    result = CliRunner().invoke(cli, ["workflow", "list", "--filter", "api_trigger", "--json"])
    assert result.exit_code == 0
    assert "Deploy" in result.output
    assert "Nightly" not in result.output


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


def test_workflow_trigger_happy_path(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.trigger_workflow.return_value = {
        "detail": "Workflow trigger accepted.",
        "workflow_uuid": "w-1",
        "queued": True,
    }
    result = CliRunner().invoke(
        cli,
        ["workflow", "trigger", "w-1", "--payload", '{"env":"prod"}'],
    )
    assert result.exit_code == 0
    assert "Workflow queued" in result.output
    assert "w-1" in result.output
    client.trigger_workflow.assert_called_once_with("w-1", payload={"env": "prod"})


def test_workflow_trigger_json_mode(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.trigger_workflow.return_value = {
        "queued": True,
        "workflow_uuid": "w-1",
        "detail": "ok",
    }
    result = CliRunner().invoke(cli, ["workflow", "trigger", "w-1", "--json"])
    assert result.exit_code == 0
    assert '"queued": true' in result.output
    client.trigger_workflow.assert_called_once_with("w-1", payload=None)


def test_workflow_trigger_payload_must_be_object(monkeypatch: Any) -> None:
    _client(monkeypatch)
    result = CliRunner().invoke(cli, ["workflow", "trigger", "w-1", "--payload", "[1,2]"])
    assert result.exit_code == 1
    assert "JSON object" in result.output


def test_workflow_trigger_payload_size_guard(monkeypatch: Any) -> None:
    _client(monkeypatch)
    big = '{"blob":"' + ("x" * 9000) + '"}'
    result = CliRunner().invoke(cli, ["workflow", "trigger", "w-1", "--payload", big])
    assert result.exit_code == 1
    assert "8192" in result.output


def test_workflow_trigger_not_triggerable(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.trigger_workflow.side_effect = APIError(
        400, "not triggerable", code="workflow_not_triggerable"
    )
    result = CliRunner().invoke(cli, ["workflow", "trigger", "w-1"])
    assert result.exit_code == 2
    assert "api_trigger" in result.output


def test_workflow_trigger_execute_not_allowed(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.trigger_workflow.side_effect = APIError(
        403, "denied", code="workflow_execute_not_allowed"
    )
    result = CliRunner().invoke(cli, ["workflow", "trigger", "w-1", "--json"])
    assert result.exit_code == 4
    assert '"code": "workflow_execute_not_allowed"' in result.output


def test_workflow_trigger_frozen(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.trigger_workflow.side_effect = APIError(409, "frozen", code="workflow_frozen")
    result = CliRunner().invoke(cli, ["workflow", "trigger", "w-1"])
    assert result.exit_code == 1
    assert "frozen" in result.output.lower()
    assert "plan" in result.output.lower()


def test_workflow_trigger_not_found(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.trigger_workflow.side_effect = APIError(404, "missing")
    result = CliRunner().invoke(cli, ["workflow", "trigger", "w-missing"])
    assert result.exit_code == 5
    assert "missing" in result.output.lower()
