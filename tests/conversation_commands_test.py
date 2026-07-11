"""Tests for the `dailybot conversation` command group (open + optional send)."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError
from dailybot_cli.main import cli

U1: str = "294bf2cc-e3c7-401d-a1d6-bf20aa64bb33"
U2: str = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
CHANNEL: str = "G01ABCDEF12"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _client(**overrides: object) -> MagicMock:
    client: MagicMock = MagicMock()
    client.open_conversation.return_value = {"channel": CHANNEL}
    client.send_chat_message.return_value = {"bot_message_id": "999"}
    client.list_users.return_value = [
        {"uuid": U1, "full_name": "Sergio Florez", "email": "sergio@co.com", "is_active": True},
        {"uuid": U2, "full_name": "Mauricio Gomez", "email": "mauricio@co.com", "is_active": True},
    ]
    for key, value in overrides.items():
        setattr(client, key, value)
    return client


class TestConversationOpen:
    @patch("dailybot_cli.commands.conversation.require_auth")
    def test_open_with_comma_separated_uuids(self, mock_auth: MagicMock, runner: CliRunner) -> None:
        client = _client()
        mock_auth.return_value = client
        result = runner.invoke(cli, ["conversation", "open", "--users", f"{U1},{U2}"])
        assert result.exit_code == 0
        client.open_conversation.assert_called_once_with([U1, U2])
        assert CHANNEL in result.output
        client.send_chat_message.assert_not_called()
        client.list_users.assert_not_called()  # all-UUID path skips the directory fetch

    @patch("dailybot_cli.commands.conversation.require_auth")
    def test_open_with_repeatable_flag(self, mock_auth: MagicMock, runner: CliRunner) -> None:
        client = _client()
        mock_auth.return_value = client
        result = runner.invoke(cli, ["conversation", "open", "-u", U1, "-u", U2])
        assert result.exit_code == 0
        client.open_conversation.assert_called_once_with([U1, U2])

    @patch("dailybot_cli.commands.conversation.require_auth")
    def test_open_and_send_chains_group_chat(self, mock_auth: MagicMock, runner: CliRunner) -> None:
        client = _client()
        mock_auth.return_value = client
        result = runner.invoke(
            cli, ["conversation", "open", "-u", U1, "-u", U2, "-m", "Report ready"]
        )
        assert result.exit_code == 0
        client.send_chat_message.assert_called_once_with(
            {
                "message": "Report ready",
                "target_channels": [{"id": CHANNEL, "channel_type": "group_chat"}],
            }
        )

    @patch("dailybot_cli.commands.conversation.require_auth")
    def test_resolve_by_name(self, mock_auth: MagicMock, runner: CliRunner) -> None:
        client = _client()
        mock_auth.return_value = client
        result = runner.invoke(cli, ["conversation", "open", "-u", "Mauricio"])
        assert result.exit_code == 0
        client.list_users.assert_called_once()
        client.open_conversation.assert_called_once_with([U2])

    @patch("dailybot_cli.commands.conversation.require_auth")
    def test_resolve_by_email(self, mock_auth: MagicMock, runner: CliRunner) -> None:
        client = _client()
        mock_auth.return_value = client
        result = runner.invoke(cli, ["conversation", "open", "--emails", "mauricio@co.com"])
        assert result.exit_code == 0
        client.open_conversation.assert_called_once_with([U2])

    @patch("dailybot_cli.commands.conversation.require_auth")
    def test_dedupe_preserves_order(self, mock_auth: MagicMock, runner: CliRunner) -> None:
        client = _client()
        mock_auth.return_value = client
        result = runner.invoke(cli, ["conversation", "open", "-u", f"{U1},{U2},{U1}"])
        assert result.exit_code == 0
        client.open_conversation.assert_called_once_with([U1, U2])

    @patch("dailybot_cli.commands.conversation.require_auth")
    def test_no_participants_errors(self, mock_auth: MagicMock, runner: CliRunner) -> None:
        client = _client()
        mock_auth.return_value = client
        result = runner.invoke(cli, ["conversation", "open"])
        assert result.exit_code == 1
        assert "participant" in result.output.lower()
        client.open_conversation.assert_not_called()

    @patch("dailybot_cli.commands.conversation.require_auth")
    def test_json_mode(self, mock_auth: MagicMock, runner: CliRunner) -> None:
        client = _client()
        mock_auth.return_value = client
        result = runner.invoke(cli, ["conversation", "open", "-u", f"{U1},{U2}", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["channel"] == CHANNEL
        assert payload["message_sent"] is False

    @patch("dailybot_cli.commands.conversation.require_auth")
    def test_json_mode_with_message(self, mock_auth: MagicMock, runner: CliRunner) -> None:
        client = _client()
        mock_auth.return_value = client
        result = runner.invoke(
            cli, ["conversation", "open", "-u", f"{U1},{U2}", "-m", "hi", "--json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["channel"] == CHANNEL
        assert payload["message_sent"] is True

    @patch("dailybot_cli.commands.conversation.require_auth")
    def test_not_slack_406(self, mock_auth: MagicMock, runner: CliRunner) -> None:
        client = _client(
            open_conversation=MagicMock(
                side_effect=APIError(406, "nope", code="open_conversation_not_supported")
            )
        )
        mock_auth.return_value = client
        result = runner.invoke(cli, ["conversation", "open", "-u", f"{U1},{U2}"])
        assert result.exit_code != 0
        assert "Slack" in result.output

    @patch("dailybot_cli.commands.conversation.require_auth")
    def test_not_admin_403(self, mock_auth: MagicMock, runner: CliRunner) -> None:
        client = _client(open_conversation=MagicMock(side_effect=APIError(403, "forbidden")))
        mock_auth.return_value = client
        result = runner.invoke(cli, ["conversation", "open", "-u", f"{U1},{U2}"])
        assert result.exit_code != 0
        assert "admin" in result.output.lower()

    @patch("dailybot_cli.commands.conversation.require_auth")
    def test_users_not_found(self, mock_auth: MagicMock, runner: CliRunner) -> None:
        client = _client(
            open_conversation=MagicMock(
                side_effect=APIError(400, "x", code="one_or_more_users_not_found")
            )
        )
        mock_auth.return_value = client
        result = runner.invoke(cli, ["conversation", "open", "-u", f"{U1},{U2}"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()
