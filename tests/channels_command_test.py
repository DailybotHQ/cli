"""Tests for the `channels` command group."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError
from dailybot_cli.main import cli

CHANNELS_PAYLOAD: list[dict[str, Any]] = [
    {"uuid": "chan-1", "name": "#engineering", "platform": "slack"},
    {"uuid": "chan-2", "name": "#general", "platform": "slack"},
]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestChannelsCommand:
    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_channels_list_table(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_report_channels.return_value = CHANNELS_PAYLOAD

        result = runner.invoke(cli, ["channels", "list"])
        assert result.exit_code == 0
        assert "engineering" in result.output
        assert "chan-1" in result.output

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_channels_list_json(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_report_channels.return_value = CHANNELS_PAYLOAD

        result = runner.invoke(cli, ["channels", "list", "--json"])
        assert result.exit_code == 0
        payload: list[dict[str, Any]] = json.loads(result.output)
        assert payload[0]["uuid"] == "chan-1"

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    def test_channels_list_not_authenticated(
        self,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = None
        result = runner.invoke(cli, ["channels", "list"])
        assert result.exit_code == 3

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_channels_list_auth_failure(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_report_channels.side_effect = APIError(status_code=401, detail="Nope")

        result = runner.invoke(cli, ["channels", "list"])
        assert result.exit_code == 3
        assert "dailybot login" in result.output
