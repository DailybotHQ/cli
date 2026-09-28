"""Open-org Tasks: members hold structure access; keys still cannot."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    ERROR_CODE_MESSAGES,
    EXIT_PERMISSION_DENIED,
    resolve_error_message,
)
from dailybot_cli.main import cli


def test_not_found_message_says_not_visible() -> None:
    message: str = ERROR_CODE_MESSAGES["not_found"].lower()
    assert "not visible" in message
    for forbidden in ("permission", "forbidden", "not allowed", "access denied"):
        assert forbidden not in message


def test_signed_in_tasks_admin_refusal_does_not_ask_for_admin_grant() -> None:
    exc = APIError(
        status_code=403,
        detail="x",
        code="insufficient_scope",
        extra={"required_scope": "tasks:admin"},
    )
    with patch("dailybot_cli.commands.public_api_helpers.get_token", return_value="tok"):
        message: str = resolve_error_message(exc)
    lower: str = message.lower()
    assert "guest" in lower
    assert "member" in lower
    assert "grant it" not in lower
    assert "be an admin" not in lower
    assert "organization admin to grant" not in lower


def test_key_tasks_admin_refusal_still_blames_the_key() -> None:
    exc = APIError(
        status_code=403,
        detail="x",
        code="insufficient_scope",
        extra={"required_scope": "tasks:admin"},
    )
    with patch("dailybot_cli.commands.public_api_helpers.get_token", return_value=None):
        message: str = resolve_error_message(exc)
    lower: str = message.lower()
    assert "api key" in lower
    assert "dailybot login" in lower
    assert "be an admin" not in lower


def test_board_create_help_does_not_require_organization_admin() -> None:
    result: Any = CliRunner().invoke(cli, ["board", "create", "--help"])
    assert result.exit_code == 0
    out: str = result.output.lower()
    assert "organization admin" not in out
    assert "non-guest member" in out or "signed-in person" in out


def test_project_create_as_person_reaches_the_server() -> None:
    client: MagicMock = MagicMock(spec=DailyBotClient)
    client.create_project.return_value = {
        "uuid": "00000000-0000-0000-0000-000000000099",
        "name": "Open Org",
    }
    with (
        patch("dailybot_cli.commands.project.require_auth", return_value=client),
        patch("dailybot_cli.commands.project.get_token", return_value="tok"),
    ):
        result: Any = CliRunner().invoke(cli, ["project", "create", "--name", "Open Org", "--json"])
    assert result.exit_code == 0, result.output
    client.create_project.assert_called_once()


def test_goal_create_as_person_reaches_the_server() -> None:
    client: MagicMock = MagicMock(spec=DailyBotClient)
    client.create_goal.return_value = {
        "uuid": "00000000-0000-0000-0000-000000000098",
        "name": "Q4",
    }
    with (
        patch("dailybot_cli.commands.goal.require_auth", return_value=client),
        # goal reuses project._require_person_for_admin, which reads project.get_token
        patch("dailybot_cli.commands.project.get_token", return_value="tok"),
    ):
        result: Any = CliRunner().invoke(
            cli,
            [
                "goal",
                "create",
                "--name",
                "Q4",
                "--period-start",
                "2026-10-01",
                "--period-end",
                "2026-12-31",
                "--json",
            ],
        )
    assert result.exit_code == 0, result.output
    client.create_goal.assert_called_once()


def test_key_still_refused_on_project_create() -> None:
    client: MagicMock = MagicMock(spec=DailyBotClient)
    with (
        patch("dailybot_cli.commands.project.require_auth", return_value=client),
        patch("dailybot_cli.commands.project.get_token", return_value=None),
    ):
        result: Any = CliRunner().invoke(cli, ["project", "create", "--name", "X", "--json"])
    assert result.exit_code == EXIT_PERMISSION_DENIED
    client.create_project.assert_not_called()
