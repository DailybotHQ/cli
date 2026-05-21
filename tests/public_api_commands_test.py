"""Tests for user-scoped public API commands (checkin, form, kudos)."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


STATUS_PAYLOAD: dict[str, Any] = {
    "count": 1,
    "pending_checkins": [
        {
            "followup_name": "Daily Standup",
            "followup_uuid": "followup-uuid-1",
            "template_questions": [
                {
                    "uuid": "question-uuid-0",
                    "question": "What did you complete yesterday?",
                    "question_type": "text_field",
                    "is_blocker": False,
                },
                {
                    "uuid": "question-uuid-1",
                    "question": "What will you do today?",
                    "question_type": "text_field",
                    "is_blocker": False,
                },
            ],
        }
    ],
}


class TestCheckinCommand:
    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_list_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_status.return_value = STATUS_PAYLOAD

        result = runner.invoke(cli, ["checkin", "list"])
        assert result.exit_code == 0
        assert "Daily Standup" in result.output
        assert "followup-uuid-1" in result.output

    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_list_json(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_status.return_value = STATUS_PAYLOAD

        result = runner.invoke(cli, ["checkin", "list", "--json"])
        assert result.exit_code == 0
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["count"] == 1
        assert payload["pending_checkins"][0]["template_questions"][0]["index"] == 0

    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    def test_checkin_list_not_logged_in(
        self,
        mock_get_token: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = None
        result = runner.invoke(cli, ["checkin", "list"])
        assert result.exit_code == 3

    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_list_auth_failure_json(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_status.side_effect = APIError(401, "Unauthorized")

        result = runner.invoke(cli, ["checkin", "list", "--json"])
        assert result.exit_code == 3
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["status"] == 401

    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_complete_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_status.return_value = STATUS_PAYLOAD
        mock_client.complete_checkin.return_value = {"uuid": "response-uuid"}

        result = runner.invoke(
            cli,
            [
                "checkin",
                "complete",
                "followup-uuid-1",
                "-a",
                "0=Shipped auth",
                "-a",
                "1=Reviewing migrations",
                "--yes",
            ],
        )
        assert result.exit_code == 0
        mock_client.complete_checkin.assert_called_once_with(
            followup_uuid="followup-uuid-1",
            responses=[
                {"uuid": "question-uuid-0", "index": 0, "response": "Shipped auth"},
                {"uuid": "question-uuid-1", "index": 1, "response": "Reviewing migrations"},
            ],
            last_question_index=1,
            response_date=None,
        )

    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_complete_json_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_status.return_value = STATUS_PAYLOAD
        mock_client.complete_checkin.return_value = {"uuid": "response-uuid"}

        result = runner.invoke(
            cli,
            [
                "checkin",
                "complete",
                "followup-uuid-1",
                "-a",
                "0=Done",
                "-a",
                "1=Next",
                "--yes",
                "--json",
            ],
        )
        assert result.exit_code == 0
        assert json.loads(result.output) == {"uuid": "response-uuid"}

    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_complete_user_abort(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_status.return_value = STATUS_PAYLOAD

        result = runner.invoke(
            cli,
            [
                "checkin",
                "complete",
                "followup-uuid-1",
                "-a",
                "0=Done",
                "-a",
                "1=Next",
            ],
            input="n\n",
        )
        assert result.exit_code == 7
        mock_client.complete_checkin.assert_not_called()


class TestFormCommand:
    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_list_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_forms.return_value = [
            {
                "id": "form-uuid-1",
                "name": "Team feedback",
                "is_active": True,
                "privacy": "everyone",
            }
        ]

        result = runner.invoke(cli, ["form", "list"])
        assert result.exit_code == 0
        assert "Team feedback" in result.output
        assert "form-uuid-1" in result.output

    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_submit_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_forms.return_value = [{"id": "form-uuid-1", "name": "Team feedback"}]
        mock_client.submit_form_response.return_value = {"uuid": "response-uuid"}

        result = runner.invoke(
            cli,
            [
                "form",
                "submit",
                "form-uuid-1",
                "--content",
                '{"question-uuid-1":"Yes"}',
                "--yes",
            ],
        )
        assert result.exit_code == 0
        mock_client.submit_form_response.assert_called_once_with(
            form_uuid="form-uuid-1",
            content={"question-uuid-1": "Yes"},
        )

    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_submit_quota_exhausted(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_forms.return_value = []
        mock_client.submit_form_response.side_effect = APIError(402, "Quota exhausted")

        result = runner.invoke(
            cli,
            [
                "form",
                "submit",
                "form-uuid-1",
                "--content",
                '{"question-uuid-1":"Yes"}',
                "--yes",
            ],
        )
        assert result.exit_code == 5

    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_submit_rate_limited_json(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_forms.return_value = []
        mock_client.submit_form_response.side_effect = APIError(429, "Too many requests")

        result = runner.invoke(
            cli,
            [
                "form",
                "submit",
                "form-uuid-1",
                "--content",
                '{"question-uuid-1":"Yes"}',
                "--yes",
                "--json",
            ],
        )
        assert result.exit_code == 6
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["status"] == 429


class TestUserCommand:
    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_user_list_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_users.return_value = [
            {
                "uuid": "user-uuid-1",
                "full_name": "Jane Doe",
                "email": "jane@example.com",
            }
        ]

        result = runner.invoke(cli, ["user", "list"])
        assert result.exit_code == 0
        assert "Jane Doe" in result.output
        assert "user-uuid-1" in result.output

    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_user_list_json(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_users.return_value = [{"uuid": "user-uuid-1", "full_name": "Jane Doe"}]

        result = runner.invoke(cli, ["user", "list", "--json"])
        assert result.exit_code == 0
        payload: list[dict[str, Any]] = json.loads(result.output)
        assert payload[0]["uuid"] == "user-uuid-1"


class TestKudosCommand:
    @patch("dailybot_cli.commands.kudos.get_current_user_uuid")
    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_kudos_give_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        mock_current_uuid: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_current_uuid.return_value = "self-uuid"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_users.return_value = [
            {"uuid": "user-uuid-1", "full_name": "Jane Doe"},
        ]
        mock_client.give_kudos.return_value = {"uuid": "kudos-uuid"}

        result = runner.invoke(
            cli,
            [
                "kudos",
                "give",
                "--to",
                "Jane Doe",
                "--message",
                "Great work!",
                "--yes",
            ],
        )
        assert result.exit_code == 0
        mock_client.give_kudos.assert_called_once_with(
            receivers=["user-uuid-1"],
            content="Great work!",
            company_value=None,
        )

    @patch("dailybot_cli.commands.kudos.get_current_user_uuid")
    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_kudos_give_self_rejected(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        mock_current_uuid: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_current_uuid.return_value = "self-uuid"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_users.return_value = [
            {"uuid": "self-uuid", "full_name": "Me"},
        ]

        result = runner.invoke(
            cli,
            [
                "kudos",
                "give",
                "--to",
                "Me",
                "--message",
                "Nice",
                "--yes",
            ],
        )
        assert result.exit_code == 4
        mock_client.give_kudos.assert_not_called()

    @patch("dailybot_cli.commands.kudos.get_current_user_uuid")
    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_kudos_give_daily_limit(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        mock_current_uuid: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_current_uuid.return_value = "self-uuid"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_users.return_value = [
            {"uuid": "user-uuid-1", "full_name": "Jane Doe"},
        ]
        mock_client.give_kudos.side_effect = APIError(406, "Daily limit reached")

        result = runner.invoke(
            cli,
            [
                "kudos",
                "give",
                "--to",
                "Jane Doe",
                "--message",
                "Great work!",
                "--yes",
            ],
        )
        assert result.exit_code == 4

    @patch("dailybot_cli.commands.kudos.get_current_user_uuid")
    @patch("dailybot_cli.commands.public_api_helpers.get_token")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_kudos_give_ambiguous_receiver(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        mock_current_uuid: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_current_uuid.return_value = "self-uuid"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_users.return_value = [
            {"uuid": "user-uuid-1", "full_name": "Jane Doe"},
            {"uuid": "user-uuid-2", "full_name": "Jane Smith"},
        ]

        result = runner.invoke(
            cli,
            [
                "kudos",
                "give",
                "--to",
                "Jane",
                "--message",
                "Great work!",
                "--yes",
            ],
        )
        assert result.exit_code == 2
