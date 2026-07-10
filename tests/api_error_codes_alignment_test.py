"""Alignment with the API's role-audit fixes (F1 + F2).

The API now returns `org_admin_required` on *every* admin-only endpoint (kudos
org, webhooks, team member management, followup create), not just chat
send-as-user, and `invalid_kudos_filter` on a bad `?filter=` value.
"""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import ERROR_CODE_MESSAGES
from dailybot_cli.main import cli


def test_org_admin_required_message_is_generic() -> None:
    """It fires on many endpoints now, so it must not name --send-as-user."""
    msg = ERROR_CODE_MESSAGES["org_admin_required"].lower()
    assert "admin" in msg
    assert "send-as-user" not in msg
    assert "--send-as-user" not in msg


def test_invalid_kudos_filter_has_a_handler() -> None:
    assert "invalid_kudos_filter" in ERROR_CODE_MESSAGES
    assert "received" in ERROR_CODE_MESSAGES["invalid_kudos_filter"].lower()


@patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
@patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
def test_kudos_org_member_sees_generic_admin_message(
    mock_client_cls: MagicMock, _auth: MagicMock
) -> None:
    client = mock_client_cls.return_value
    client.list_kudos_organization.side_effect = APIError(
        403, "This endpoint requires organization admin privileges.", code="org_admin_required"
    )
    result = CliRunner().invoke(cli, ["kudos", "org"])
    assert result.exit_code == 4
    out = result.output.lower()
    assert "admin" in out
    assert "send-as-user" not in out  # the old, wrong message must be gone


@patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
@patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
def test_kudos_list_invalid_filter_maps_to_friendly_message(
    mock_client_cls: MagicMock, _auth: MagicMock
) -> None:
    client = mock_client_cls.return_value
    client.list_kudos.side_effect = APIError(
        400,
        "Not valid kudos filter. Accepted values: kudos_received, kudos_given.",
        code="invalid_kudos_filter",
    )
    result = CliRunner().invoke(cli, ["kudos", "list", "--filter", "nonsense"])
    assert result.exit_code != 0
    assert "received" in result.output.lower()
