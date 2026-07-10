"""The `--user` response filter accepts only a UUID.

The API rejects anything else with `invalid_user_identifier`. Catching it in the
client turns a network round-trip into an immediate, actionable message.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.main import cli

VALID_UUID: str = "294bf2cc-e3c7-401d-a1d6-bf20aa64bb33"
FORM_UUID: str = "76174afc-490b-489b-b5cf-e9f84e000001"

REJECTED: list[str] = ["me@example.com", "Jane Doe", "garbage", "294bf2cc-e3c7"]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.mark.parametrize("bad_value", REJECTED)
@patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
@patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
def test_form_responses_rejects_non_uuid_user(
    _auth: MagicMock, mock_client_cls: MagicMock, runner: CliRunner, bad_value: str
) -> None:
    result = runner.invoke(cli, ["form", "responses", FORM_UUID, "--user", bad_value])
    assert result.exit_code == 1
    assert "UUID" in result.output
    mock_client_cls.assert_not_called()  # never reaches the network


@pytest.mark.parametrize("bad_value", REJECTED)
@patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
@patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
def test_checkin_history_rejects_non_uuid_user(
    _auth: MagicMock, mock_client_cls: MagicMock, runner: CliRunner, bad_value: str
) -> None:
    result = runner.invoke(cli, ["checkin", "history", FORM_UUID, "--user", bad_value])
    assert result.exit_code == 1
    assert "UUID" in result.output
    mock_client_cls.assert_not_called()


@patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
@patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
def test_valid_uuid_passes_through(mock_client_cls: MagicMock, _auth: MagicMock) -> None:
    client = mock_client_cls.return_value
    client.list_form_responses.return_value = []
    result = CliRunner().invoke(
        cli, ["form", "responses", FORM_UUID, "--user", VALID_UUID, "--json"]
    )
    assert result.exit_code == 0
    assert client.list_form_responses.call_args.kwargs["user"] == VALID_UUID
