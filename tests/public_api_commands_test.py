"""Tests for user-scoped public API commands (checkin, form, kudos)."""

import json
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


_USER_UUID: str = "294bf2cc-e3c7-401d-a1d6-bf20aa64bb33"  # --user accepts only a UUID

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
    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_list_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_status.return_value = STATUS_PAYLOAD

        result = runner.invoke(cli, ["checkin", "list"])
        assert result.exit_code == 0
        assert "Daily Standup" in result.output
        assert "followup-uuid-1" in result.output

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_list_json(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_status.return_value = STATUS_PAYLOAD

        result = runner.invoke(cli, ["checkin", "list", "--json"])
        assert result.exit_code == 0
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["count"] == 1
        assert payload["pending_checkins"][0]["template_questions"][0]["index"] == 0

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_list_succeeds_with_api_key_only(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        """User-scoped commands work with an API key and no login session."""
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_status.return_value = STATUS_PAYLOAD

        result = runner.invoke(cli, ["checkin", "list"])
        assert result.exit_code == 0
        assert "Daily Standup" in result.output

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    def test_checkin_list_not_authenticated(
        self,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = None
        result = runner.invoke(cli, ["checkin", "list"])
        assert result.exit_code == 3
        assert "Not authenticated" in result.output

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_list_auth_failure_json(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_status.side_effect = APIError(401, "Unauthorized")

        result = runner.invoke(cli, ["checkin", "list", "--json"])
        assert result.exit_code == 3
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["status"] == 401

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_complete_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
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

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_complete_json_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
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

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_complete_user_abort(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
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
    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_list_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
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

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_submit_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
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

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_submit_guided_prompts(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_form.return_value = {
            "id": "form-uuid-1",
            "name": "Team feedback",
            "questions": [
                {"uuid": "question-uuid-1", "question": "How was your week?"},
                {"uuid": "question-uuid-2", "question": "Any blockers?"},
            ],
        }
        mock_client.submit_form_response.return_value = {"uuid": "response-uuid"}

        result = runner.invoke(
            cli,
            ["form", "submit", "form-uuid-1", "--yes"],
            input="Great week\nNone\n",
        )
        assert result.exit_code == 0
        mock_client.get_form.assert_called_once_with("form-uuid-1")
        mock_client.submit_form_response.assert_called_once_with(
            form_uuid="form-uuid-1",
            content={
                "question-uuid-1": "Great week",
                "question-uuid-2": "None",
            },
        )

    @patch("dailybot_cli.commands.user_scoped_actions._prompt_form_answer")
    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_submit_guided_question_types(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        mock_prompt_answer: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_form.return_value = {
            "id": "form-uuid-1",
            "questions": [
                {"uuid": "q-text", "question": "Comments?", "question_type": "text_field"},
                {"uuid": "q-num", "question": "Score?", "question_type": "numeric"},
                {"uuid": "q-bool", "question": "Recommend?", "question_type": "boolean"},
                {
                    "uuid": "q-choice",
                    "question": "Pick one",
                    "question_type": "choice",
                    "choices": ["A", "B"],
                },
            ],
        }
        mock_client.submit_form_response.return_value = {"uuid": "response-uuid"}
        mock_prompt_answer.side_effect = ["Looks good", 9, True, "A"]

        result = runner.invoke(cli, ["form", "submit", "form-uuid-1", "--yes"])
        assert result.exit_code == 0
        assert mock_prompt_answer.call_count == 4
        mock_client.submit_form_response.assert_called_once_with(
            form_uuid="form-uuid-1",
            content={
                "q-text": "Looks good",
                "q-num": 9,
                "q-bool": True,
                "q-choice": "A",
            },
        )

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_submit_quota_exhausted(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
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

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_submit_rate_limited_json(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
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
    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_user_list_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
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

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_user_list_json(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_users.return_value = [{"uuid": "user-uuid-1", "full_name": "Jane Doe"}]

        result = runner.invoke(cli, ["user", "list", "--json"])
        assert result.exit_code == 0
        payload: list[dict[str, Any]] = json.loads(result.output)
        assert payload[0]["uuid"] == "user-uuid-1"
        mock_client.list_users.assert_called_once_with(include_inactive=False)

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_user_list_include_inactive_flag(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_users.return_value = []

        result = runner.invoke(cli, ["user", "list", "--include-inactive", "--json"])
        assert result.exit_code == 0
        mock_client.list_users.assert_called_once_with(include_inactive=True)


class TestKudosCommand:
    @patch("dailybot_cli.commands.kudos.get_current_user_uuid")
    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_kudos_give_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        mock_current_uuid: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
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
            content="Great work!",
            user_uuid_receivers=["user-uuid-1"],
            team_uuid_receivers=None,
            company_value=None,
        )

    @patch("dailybot_cli.commands.kudos.get_current_user_uuid")
    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_kudos_give_self_rejected(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        mock_current_uuid: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
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
    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_kudos_give_daily_limit(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        mock_current_uuid: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
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
    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_kudos_give_ambiguous_receiver(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        mock_current_uuid: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
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

    @patch("dailybot_cli.commands.kudos.get_current_user_uuid")
    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_kudos_give_team_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        mock_current_uuid: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_current_uuid.return_value = "self-uuid"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_teams.return_value = [
            {"uuid": "team-uuid-1", "name": "Engineering"},
        ]
        mock_client.give_kudos.return_value = {"uuid": "kudos-uuid"}

        result = runner.invoke(
            cli,
            [
                "kudos",
                "give",
                "--team",
                "Engineering",
                "--message",
                "Shipped flawlessly",
                "--yes",
            ],
        )
        assert result.exit_code == 0
        mock_client.give_kudos.assert_called_once_with(
            content="Shipped flawlessly",
            user_uuid_receivers=None,
            team_uuid_receivers=["team-uuid-1"],
            company_value=None,
        )

    @patch("dailybot_cli.commands.kudos.get_current_user_uuid")
    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_kudos_give_user_and_team(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        mock_current_uuid: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_current_uuid.return_value = "self-uuid"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_users.return_value = [
            {"uuid": "user-uuid-1", "full_name": "Alice"},
        ]
        mock_client.list_teams.return_value = [
            {"uuid": "team-uuid-1", "name": "QA"},
        ]
        mock_client.give_kudos.return_value = {"uuid": "kudos-uuid"}

        result = runner.invoke(
            cli,
            [
                "kudos",
                "give",
                "--to",
                "Alice",
                "--team",
                "QA",
                "--message",
                "Both nailed it",
                "--yes",
            ],
        )
        assert result.exit_code == 0
        mock_client.give_kudos.assert_called_once_with(
            content="Both nailed it",
            user_uuid_receivers=["user-uuid-1"],
            team_uuid_receivers=["team-uuid-1"],
            company_value=None,
        )

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_kudos_give_unseen_team(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_teams.return_value = [
            {"uuid": "team-uuid-1", "name": "Engineering"},
        ]

        result = runner.invoke(
            cli,
            [
                "kudos",
                "give",
                "--team",
                "Marketing",
                "--message",
                "Nice",
                "--yes",
            ],
        )
        assert result.exit_code == 2
        assert "Marketing" in result.output or "Marketing" in result.stderr_bytes.decode()
        mock_client.give_kudos.assert_not_called()

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_kudos_give_requires_to_or_team(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"

        result = runner.invoke(
            cli,
            ["kudos", "give", "--message", "Nice", "--yes"],
        )
        assert result.exit_code == 2


class TestTeamCommand:
    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_team_list_success(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_teams.return_value = [
            {"uuid": "team-uuid-1", "name": "General", "active": True, "members_count": 12},
        ]

        result = runner.invoke(cli, ["team", "list"])
        assert result.exit_code == 0
        assert "General" in result.output
        assert "team-uuid-1" in result.output

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_team_list_json(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_teams.return_value = [
            {"uuid": "team-uuid-1", "name": "General"},
        ]

        result = runner.invoke(cli, ["team", "list", "--json"])
        assert result.exit_code == 0
        payload: list[dict[str, Any]] = json.loads(result.output)
        assert payload[0]["uuid"] == "team-uuid-1"

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_team_get_by_name(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_teams.return_value = [
            {"uuid": "team-uuid-1", "name": "Engineering"},
        ]
        mock_client.get_team.return_value = {"uuid": "team-uuid-1", "name": "Engineering"}

        result = runner.invoke(cli, ["team", "get", "Engineering"])
        assert result.exit_code == 0
        mock_client.get_team.assert_called_once_with("team-uuid-1")

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_team_get_with_members(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        team_uuid: str = "13883b5b-7066-47aa-ad0c-63bbc89eb986"
        mock_client.list_teams.return_value = [
            {"uuid": team_uuid, "name": "Engineering"},
        ]
        mock_client.get_team.return_value = {"uuid": team_uuid, "name": "Engineering"}
        mock_client.list_team_members.return_value = [
            {"uuid": "u1", "full_name": "Jane"},
        ]

        result = runner.invoke(cli, ["team", "get", team_uuid, "--with-members", "--json"])
        assert result.exit_code == 0
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["members"][0]["full_name"] == "Jane"


class TestFormLifecycle:
    FORM_PAYLOAD: ClassVar[dict[str, Any]] = {
        "id": "form-uuid-1",
        "name": "Code Release",
        "slug": "code-release-form",
        "workflow_enabled": True,
        "workflow_config": {
            "states": [
                {"key": "pre_release", "label": "Pre Release", "order": 0},
                {"key": "qa", "label": "QA", "order": 1},
                {"key": "released", "label": "Released", "order": 2},
            ]
        },
        "questions": [
            {"uuid": "q-1", "question": "PR?", "question_type": "text"},
        ],
    }

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_get(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_form.return_value = self.FORM_PAYLOAD

        result = runner.invoke(cli, ["form", "get", "form-uuid-1", "--json"])
        assert result.exit_code == 0
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["slug"] == "code-release-form"

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_responses_latest(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_form_responses.return_value = [
            {"id": "r1", "current_state": "qa"},
            {"id": "r0", "current_state": "pre_release"},
        ]

        result = runner.invoke(cli, ["form", "responses", "form-uuid-1", "--latest", "--json"])
        assert result.exit_code == 0
        payload: list[dict[str, Any]] = json.loads(result.output)
        assert len(payload) == 1
        assert payload[0]["id"] == "r1"
        mock_client.list_form_responses.assert_called_once_with(
            "form-uuid-1",
            state=None,
            all_responses=False,
            user=None,
            date_from=None,
            date_to=None,
            search=None,
            page=None,
            page_size=None,
            fetch_all=True,
            limit=None,
            meta={},
        )

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_responses_state_filter(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_form_responses.return_value = []

        result = runner.invoke(cli, ["form", "responses", "form-uuid-1", "--state", "qa", "--json"])
        assert result.exit_code == 0
        mock_client.list_form_responses.assert_called_once_with(
            "form-uuid-1",
            state="qa",
            all_responses=False,
            user=None,
            date_from=None,
            date_to=None,
            search=None,
            page=None,
            page_size=None,
            fetch_all=True,
            limit=None,
            meta={},
        )

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_response_get(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_form_response.return_value = {
            "id": "r1",
            "current_state": "qa",
            "content": {"q-1": "PR #4242"},
        }

        result = runner.invoke(cli, ["form", "response", "get", "f1", "r1", "--json"])
        assert result.exit_code == 0
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["id"] == "r1"

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_response_get_not_found(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_form_response.side_effect = APIError(
            404, "Form response not found.", code="form_response_not_found"
        )

        result = runner.invoke(cli, ["form", "response", "get", "f1", "r1", "--json"])
        assert result.exit_code == 5
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["code"] == "form_response_not_found"

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_update(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.update_form_response.return_value = {
            "id": "r1",
            "current_state": "qa",
            "allowed_transitions": [{"to_state": "released", "label": "Released"}],
        }

        result = runner.invoke(
            cli,
            [
                "form",
                "update",
                "f1",
                "r1",
                "--content",
                '{"q-1": "PR #4242"}',
                "--yes",
                "--json",
            ],
        )
        assert result.exit_code == 0
        mock_client.update_form_response.assert_called_once_with(
            form_uuid="f1",
            response_uuid="r1",
            content={"q-1": "PR #4242"},
        )

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_transition(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_form.return_value = {
            "workflow": {
                "enabled": True,
                "states": [
                    {"key": "pre_release", "label": "Pre-Release"},
                    {"key": "qa", "label": "QA"},
                ],
            },
        }
        mock_client.transition_form_response.return_value = {
            "id": "r1",
            "current_state": "qa",
            "allowed_transitions": [],
            "can_change_state": True,
            "state_history": [
                {"from_state": "pre_release", "to_state": "qa", "note": "QA assigned"}
            ],
        }

        result = runner.invoke(
            cli,
            [
                "form",
                "transition",
                "f1",
                "r1",
                "qa",
                "--note",
                "QA assigned",
                "--yes",
                "--json",
            ],
        )
        assert result.exit_code == 0
        mock_client.transition_form_response.assert_called_once_with(
            form_uuid="f1",
            response_uuid="r1",
            to_state="qa",
            note="QA assigned",
        )

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_transition_label_resolves_to_key(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Regression: user passes label 'Done' instead of key 'done' — CORE-2261."""
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_form.return_value = {
            "workflow": {
                "enabled": True,
                "states": [
                    {"key": "draft", "label": "Draft"},
                    {"key": "in_review", "label": "In Review"},
                    {"key": "done", "label": "Done"},
                ],
            },
        }
        mock_client.transition_form_response.return_value = {
            "id": "r1",
            "current_state": "done",
            "allowed_transitions": [],
            "can_change_state": True,
            "state_history": [],
        }

        result = runner.invoke(
            cli, ["form", "transition", "f1", "r1", "Done", "--yes", "--json"]
        )
        assert result.exit_code == 0
        mock_client.transition_form_response.assert_called_once_with(
            form_uuid="f1",
            response_uuid="r1",
            to_state="done",
            note=None,
        )

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_transition_label_case_insensitive(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_form.return_value = {
            "workflow": {
                "enabled": True,
                "states": [
                    {"key": "in_review", "label": "In Review"},
                ],
            },
        }
        mock_client.transition_form_response.return_value = {
            "id": "r1",
            "current_state": "in_review",
            "allowed_transitions": [],
            "can_change_state": True,
            "state_history": [],
        }

        result = runner.invoke(
            cli, ["form", "transition", "f1", "r1", "in review", "--yes", "--json"]
        )
        assert result.exit_code == 0
        mock_client.transition_form_response.assert_called_once_with(
            form_uuid="f1",
            response_uuid="r1",
            to_state="in_review",
            note=None,
        )

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_transition_forbidden(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_form.return_value = {"workflow": None}
        mock_client.transition_form_response.side_effect = APIError(
            403,
            "You don't have permission",
            code="form_response_change_state_forbidden",
        )

        result = runner.invoke(cli, ["form", "transition", "f1", "r1", "qa", "--yes", "--json"])
        assert result.exit_code == 4
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["code"] == "form_response_change_state_forbidden"

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_transition_final_state_locked(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_form.return_value = {"workflow": None}
        mock_client.transition_form_response.side_effect = APIError(
            403, "Locked", code="final_state_locked"
        )

        result = runner.invoke(
            cli, ["form", "transition", "f1", "r1", "released", "--yes", "--json"]
        )
        assert result.exit_code == 4
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["code"] == "final_state_locked"

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_delete(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.delete_form_response.return_value = {}

        result = runner.invoke(cli, ["form", "delete", "f1", "r1", "--yes", "--json"])
        assert result.exit_code == 0
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["deleted"] is True
        mock_client.delete_form_response.assert_called_once_with(form_uuid="f1", response_uuid="r1")

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_delete_forbidden(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.delete_form_response.side_effect = APIError(
            403, "Forbidden", code="form_response_delete_forbidden"
        )

        result = runner.invoke(cli, ["form", "delete", "f1", "r1", "--yes", "--json"])
        assert result.exit_code == 4
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["code"] == "form_response_delete_forbidden"


class TestGetCurrentUserUuid:
    def test_returns_uuid_when_auth_status_succeeds(self) -> None:
        from dailybot_cli.commands.public_api_helpers import get_current_user_uuid

        client: MagicMock = MagicMock()
        client.auth_status.return_value = {"user": {"uuid": "u-123"}}
        assert get_current_user_uuid(client) == "u-123"

    def test_returns_none_when_auth_status_rejects_api_key(self) -> None:
        """Under API-key auth, /v1/cli/auth/status/ 401s — degrade to None, not raise."""
        from dailybot_cli.commands.public_api_helpers import get_current_user_uuid

        client: MagicMock = MagicMock()
        client.auth_status.side_effect = APIError(
            401, "Authentication credentials were not provided."
        )
        assert get_current_user_uuid(client) is None


class TestCheckinExtendedCommands:
    def _client(self, mock_client_cls: MagicMock, mock_get_auth: MagicMock) -> MagicMock:
        mock_get_auth.return_value = "tok"
        return mock_client_cls.return_value

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_status_json(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        client: MagicMock = self._client(mock_client_cls, mock_get_auth)
        client.list_checkins.return_value = [
            {
                "uuid": "f1",
                "name": "Standup",
                "response_completed": False,
                "template_questions": [{}],
            }
        ]
        result = runner.invoke(cli, ["checkin", "status", "--json"])
        assert result.exit_code == 0
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["count"] == 1
        client.list_checkins.assert_called_once_with(date=None, include_summary=True)

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_show_json(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        client: MagicMock = self._client(mock_client_cls, mock_get_auth)
        client.get_checkin_detail.return_value = {
            "id": "f1",
            "name": "Standup",
            "is_archived": False,
            "schedule": {"days": [1, 2, 3], "time": "09:00", "timezone": "UTC"},
            "questions": [
                {
                    "uuid": "q1",
                    "index": 0,
                    "question": "Done?",
                    "question_type": "text",
                    "required": True,
                    "is_blocker": False,
                    "choices": [],
                }
            ],
            "participants": {"users": [{"uuid": "u1", "name": "Jane Doe"}], "teams": []},
            "report_channels": [{"id": "C1", "type": "channel", "reporting_enabled": True}],
        }
        result = runner.invoke(cli, ["checkin", "show", "f1", "--json"])
        assert result.exit_code == 0
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["questions"][0]["uuid"] == "q1"
        assert payload["participants"]["users"][0]["name"] == "Jane Doe"
        client.get_checkin_detail.assert_called_once_with("f1")

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_history_days_json(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        client: MagicMock = self._client(mock_client_cls, mock_get_auth)
        client.list_checkin_responses.return_value = [
            {"response_date": "2026-07-01", "response_completed": True, "responses": []}
        ]
        result = runner.invoke(cli, ["checkin", "history", "f1", "--days", "7", "--json"])
        assert result.exit_code == 0
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["count"] == 1
        client.list_checkin_responses.assert_called_once()
        assert client.list_checkin_responses.call_args.kwargs["user"] is None

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_history_user_filter_forwarded(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        client: MagicMock = self._client(mock_client_cls, mock_get_auth)
        client.list_checkin_responses.return_value = []
        result = runner.invoke(
            cli, ["checkin", "history", "f1", "--days", "7", "--user", _USER_UUID, "--json"]
        )
        assert result.exit_code == 0
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["user"] == _USER_UUID
        assert client.list_checkin_responses.call_args.kwargs["user"] == _USER_UUID

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_reset_json_skips_confirm(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        client: MagicMock = self._client(mock_client_cls, mock_get_auth)
        client.delete_checkin_response.return_value = {"deleted": True, "deleted_count": 1}
        result = runner.invoke(cli, ["checkin", "reset", "f1", "--json"])
        assert result.exit_code == 0
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["deleted_count"] == 1
        client.delete_checkin_response.assert_called_once_with("f1", response_date=None)

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_edit_overrides_answer(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        client: MagicMock = self._client(mock_client_cls, mock_get_auth)
        client.list_checkin_responses.return_value = [
            {
                "responses": [
                    {"uuid": "q1", "index": 0, "response": "old"},
                    {"uuid": "q2", "index": 1, "response": "keep"},
                ]
            }
        ]
        client.update_checkin_response.return_value = {"uuid": "r1"}
        result = runner.invoke(cli, ["checkin", "edit", "f1", "-a", "0=new", "--json"])
        assert result.exit_code == 0
        new_responses: list[dict[str, Any]] = client.update_checkin_response.call_args.args[1]
        assert new_responses[0]["response"] == "new"
        assert new_responses[1]["response"] == "keep"

    @patch("dailybot_cli.commands.user_scoped_actions.get_current_user_uuid")
    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_edit_scopes_prefill_to_self(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        mock_self_uuid: MagicMock,
        runner: CliRunner,
    ) -> None:
        # The responses endpoint now returns every participant by default, so the
        # pre-fill read must be scoped to the caller's own UUID.
        mock_self_uuid.return_value = "me-uuid"
        client: MagicMock = self._client(mock_client_cls, mock_get_auth)
        client.list_checkin_responses.return_value = [
            {"responses": [{"uuid": "q1", "index": 0, "response": "old"}]}
        ]
        client.update_checkin_response.return_value = {"uuid": "r1"}
        result = runner.invoke(cli, ["checkin", "edit", "f1", "-a", "0=new", "--json"])
        assert result.exit_code == 0
        assert client.list_checkin_responses.call_args.kwargs["user"] == "me-uuid"

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_reset_maps_backfill_error_code(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        client: MagicMock = self._client(mock_client_cls, mock_get_auth)
        client.delete_checkin_response.side_effect = APIError(
            409, "nope", code="previous_responses_are_not_allowed"
        )
        result = runner.invoke(cli, ["checkin", "reset", "f1", "--json"])
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["status"] == 409
        assert payload["code"] == "previous_responses_are_not_allowed"


class TestQueryFlagsWiring:
    """Task 6: shared query flags wired into list commands (real client, mocked httpx)."""

    def _envelope(self, results: list[dict[str, Any]], nxt: str | None, count: int) -> MagicMock:
        r: MagicMock = MagicMock(spec=httpx.Response)
        r.status_code = 200
        r.json.return_value = {
            "count": count,
            "next": nxt,
            "previous": None,
            "results": results,
        }
        r.headers = {}
        return r

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
    def test_form_list_composes_search_and_date(self, _auth: MagicMock) -> None:
        page = self._envelope([{"id": "f1", "name": "Retro"}], None, 1)
        with patch("dailybot_cli.api_client.httpx.get", return_value=page) as mock_get:
            result = CliRunner().invoke(
                cli, ["form", "list", "--search", "retro", "--since", "2026-07-01"]
            )
        assert result.exit_code == 0
        params = mock_get.call_args[1]["params"]
        assert params["search"] == "retro"
        assert params["start_date"] == "2026-07-01"
        assert "paginated" not in params  # the envelope is unconditional now

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
    def test_form_list_all_iterates_multiple_pages(self, _auth: MagicMock) -> None:
        p1 = self._envelope(
            [{"id": "f1", "name": "A"}],
            "http://test/v1/forms/?page=2&paginated=true",
            2,
        )
        p2 = self._envelope([{"id": "f2", "name": "B"}], None, 2)
        with patch("dailybot_cli.api_client.httpx.get", side_effect=[p1, p2]) as mock_get:
            result = CliRunner().invoke(cli, ["form", "list", "--all", "--json"])
        assert result.exit_code == 0
        assert mock_get.call_count == 2
        payload = json.loads(result.output)
        assert {f["id"] for f in payload} == {"f1", "f2"}

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
    def test_form_list_renders_count_footer(self, _auth: MagicMock) -> None:
        page = self._envelope([{"id": "f1", "name": "A"}], None, 1)
        with patch("dailybot_cli.api_client.httpx.get", return_value=page):
            result = CliRunner().invoke(cli, ["form", "list"])
        assert "Showing" in result.output

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
    def test_bare_form_list_still_works(self, _auth: MagicMock) -> None:
        page = self._envelope([{"id": "f1", "name": "A"}], None, 1)
        with patch("dailybot_cli.api_client.httpx.get", return_value=page):
            result = CliRunner().invoke(cli, ["form", "list"])
        assert result.exit_code == 0
        assert "A" in result.output

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
    def test_all_and_limit_conflict_rejected(self, _auth: MagicMock) -> None:
        result = CliRunner().invoke(cli, ["form", "list", "--all", "--limit", "3"])
        assert result.exit_code != 0
        assert "--all" in result.output and "--limit" in result.output

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
    def test_form_list_mine_passes_owner_me(self, _auth: MagicMock) -> None:
        page = self._envelope([{"id": "f1", "name": "Mine"}], None, 1)
        with patch("dailybot_cli.api_client.httpx.get", return_value=page) as mock_get:
            result = CliRunner().invoke(cli, ["form", "list", "--mine"])
        assert result.exit_code == 0
        assert mock_get.call_args[1]["params"]["owner"] == "me"

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
    def test_form_list_default_omits_owner(self, _auth: MagicMock) -> None:
        page = self._envelope([{"id": "f1", "name": "A"}], None, 1)
        with patch("dailybot_cli.api_client.httpx.get", return_value=page) as mock_get:
            result = CliRunner().invoke(cli, ["form", "list"])
        assert result.exit_code == 0
        assert "owner" not in mock_get.call_args[1]["params"]

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
    def test_form_list_search_too_long(self, _auth: MagicMock) -> None:
        """CORE-2263: search >256 chars gives a friendly error, not empty results."""
        result = CliRunner().invoke(cli, ["form", "list", "--search", "a" * 301])
        assert result.exit_code == 1
        assert "too long" in result.output.lower()
