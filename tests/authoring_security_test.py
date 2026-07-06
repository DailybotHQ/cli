"""Security-focused tests for authoring commands: error mapping, confirmations,
no-secret-leakage, and client-side validation running before any network call."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import ERROR_CODE_MESSAGES
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _auth() -> Any:
    return patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")


def _client() -> Any:
    return patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")


# Every new server error code must have a friendly message.
NEW_CODES: list[str] = [
    "invalid_question_type",
    "multiple_choice_requires_options",
    "question_label_required",
    "questions_limit_exceeded",
    "form_name_required",
    "invalid_schedule_days",
    "invalid_schedule_time",
    "invalid_timezone",
    "checkin_permission_denied",
    "form_edit_forbidden",
    "form_response_view_all_forbidden",
    "form_response_edit_forbidden",
    "form_not_found",
    "checkin_not_found",
    "question_not_found",
]


class TestErrorCodeMapping:
    @pytest.mark.parametrize("code", NEW_CODES)
    def test_code_is_mapped(self, code: str) -> None:
        assert code in ERROR_CODE_MESSAGES
        assert ERROR_CODE_MESSAGES[code]

    def test_403_forbidden_shows_role_message(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.list_form_responses.side_effect = APIError(
                status_code=403,
                detail="Forbidden",
                code="form_response_view_all_forbidden",
            )
            result = runner.invoke(cli, ["form", "responses", "form-uuid", "--all"])
        assert result.exit_code == 4
        assert "admins/owners" in result.output
        assert "within your role" in result.output

    def test_403_never_implies_elevation(self) -> None:
        for code in (
            "checkin_permission_denied",
            "form_edit_forbidden",
            "form_response_edit_forbidden",
        ):
            assert "can't elevate" in ERROR_CODE_MESSAGES[code]


class TestClientSideValidationFailsFast:
    def test_invalid_question_type_never_calls_client(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            result = runner.invoke(
                cli,
                [
                    "form",
                    "questions",
                    "add",
                    "form-uuid",
                    "--type",
                    "stars",
                    "--question",
                    "How many?",
                    "--ai-short-question",
                ],
            )
            cls.return_value.add_form_question.assert_not_called()
        assert result.exit_code != 0
        assert "Invalid question type" in result.output

    def test_bad_schedule_never_calls_client(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            result = runner.invoke(cli, ["checkin", "create", "-n", "Standup", "--days", "9"])
            cls.return_value.create_checkin.assert_not_called()
        assert result.exit_code != 0


class TestDestructiveConfirmations:
    def test_form_archive_prompts(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            result = runner.invoke(cli, ["form", "archive", "form-uuid"], input="n\n")
            cls.return_value.archive_form.assert_not_called()
        assert result.exit_code != 0

    def test_checkin_archive_prompts(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            result = runner.invoke(cli, ["checkin", "archive", "fu-1"], input="n\n")
            cls.return_value.archive_checkin.assert_not_called()
        assert result.exit_code != 0

    def test_form_question_delete_prompts(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            result = runner.invoke(
                cli, ["form", "questions", "delete", "form-uuid", "q1"], input="n\n"
            )
            cls.return_value.delete_form_question.assert_not_called()
        assert result.exit_code != 0


class TestNoSecretLeakage:
    def test_token_not_in_output(self, runner: CliRunner) -> None:
        secret: str = "super-secret-bearer-token-value"
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.token = secret
            client.api_key = "super-secret-api-key"
            client.create_form.return_value = {"id": "f-1", "name": "Retro", "questions": []}
            result = runner.invoke(cli, ["form", "create", "-n", "Retro"])
        assert result.exit_code == 0
        assert secret not in result.output
        assert "super-secret-api-key" not in result.output
