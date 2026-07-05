"""Tests for form authoring commands (create/edit/archive/questions)."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError
from dailybot_cli.main import cli

FORM_PAYLOAD: dict[str, Any] = {
    "id": "form-uuid",
    "name": "Retro",
    "questions": [
        {"uuid": "q1", "question": "What went well?", "question_type": "text", "required": True},
    ],
}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _auth() -> Any:
    return patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")


def _client() -> Any:
    return patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")


class TestFormCreate:
    def test_create_minimal(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            cls.return_value.create_form.return_value = FORM_PAYLOAD
            result = runner.invoke(cli, ["form", "create", "--name", "Retro"])
        assert result.exit_code == 0
        assert "Retro" in result.output

    def test_create_with_questions_file(self, runner: CliRunner, tmp_path: Any) -> None:
        qfile = tmp_path / "q.json"
        qfile.write_text(json.dumps([{"question_type": "text", "question": "Well?"}]))
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.create_form.return_value = FORM_PAYLOAD
            result = runner.invoke(
                cli, ["form", "create", "-n", "Retro", "--questions-file", str(qfile)]
            )
        assert result.exit_code == 0
        sent_questions = client.create_form.call_args[0][1]
        assert sent_questions[0]["question_type"] == "text"

    def test_create_with_report_channel_inline(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.create_form.return_value = FORM_PAYLOAD
            result = runner.invoke(
                cli, ["form", "create", "-n", "Retro", "--report-channel", "chan-1"]
            )
        assert result.exit_code == 0
        # Report channels go directly in the create body — no follow-up config call.
        assert client.create_form.call_args[1]["report_channels"] == ["chan-1"]
        client.update_form_config.assert_not_called()

    def test_create_bogus_channel_shows_friendly_error(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.create_form.side_effect = APIError(
                status_code=400,
                detail="Report channel 'NOT_REAL' not found in organization.",
                code="report_channel_not_found",
            )
            result = runner.invoke(
                cli, ["form", "create", "-n", "Retro", "--report-channel", "NOT_REAL"]
            )
        assert result.exit_code != 0
        assert "dailybot channels list" in result.output

    def test_create_invalid_question_type_fails_fast(
        self, runner: CliRunner, tmp_path: Any
    ) -> None:
        qfile = tmp_path / "q.json"
        qfile.write_text(json.dumps([{"question_type": "rating", "question": "Stars?"}]))
        with _auth(), _client() as cls:
            result = runner.invoke(
                cli, ["form", "create", "-n", "Retro", "--questions-file", str(qfile)]
            )
            cls.return_value.create_form.assert_not_called()
        assert result.exit_code != 0
        assert "Invalid question type" in result.output


class TestFormEdit:
    def test_edit_name(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.update_form_config.return_value = FORM_PAYLOAD
            result = runner.invoke(cli, ["form", "edit", "form-uuid", "--name", "New"])
        assert result.exit_code == 0
        assert client.update_form_config.call_args[1]["name"] == "New"

    def test_edit_requires_a_field(self, runner: CliRunner) -> None:
        with _auth(), _client():
            result = runner.invoke(cli, ["form", "edit", "form-uuid"])
        assert result.exit_code != 0
        assert "Nothing to edit" in result.output


class TestFormArchive:
    def test_archive_confirmed(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.archive_form.return_value = {}
            result = runner.invoke(cli, ["form", "archive", "form-uuid"], input="y\n")
        assert result.exit_code == 0
        client.archive_form.assert_called_once_with("form-uuid")

    def test_archive_aborts_without_confirm(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            result = runner.invoke(cli, ["form", "archive", "form-uuid"], input="n\n")
        assert result.exit_code != 0
        client.archive_form.assert_not_called()

    def test_archive_yes_skips_prompt(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.archive_form.return_value = {}
            result = runner.invoke(cli, ["form", "archive", "form-uuid", "--yes"])
        assert result.exit_code == 0


class TestFormQuestions:
    def test_list(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            cls.return_value.get_form.return_value = FORM_PAYLOAD
            result = runner.invoke(cli, ["form", "questions", "list", "form-uuid"])
        assert result.exit_code == 0
        assert "What went well?" in result.output

    def test_add_text(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.add_form_question.return_value = {"uuid": "q-new", "question": "New?"}
            result = runner.invoke(
                cli,
                ["form", "questions", "add", "form-uuid", "--type", "text", "--question", "New?"],
            )
        assert result.exit_code == 0
        assert client.add_form_question.call_args[0][1]["question_type"] == "text"

    def test_add_with_blocker(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.add_form_question.return_value = {"uuid": "q-new", "question": "Blocked?"}
            result = runner.invoke(
                cli,
                [
                    "form",
                    "questions",
                    "add",
                    "form-uuid",
                    "--type",
                    "boolean",
                    "--question",
                    "Blocked?",
                    "--blocker",
                ],
            )
        assert result.exit_code == 0
        assert client.add_form_question.call_args[0][1]["is_blocker"] is True

    def test_add_multiple_choice_needs_options(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            result = runner.invoke(
                cli,
                [
                    "form",
                    "questions",
                    "add",
                    "form-uuid",
                    "--type",
                    "multiple_choice",
                    "--question",
                    "Rating?",
                ],
            )
            cls.return_value.add_form_question.assert_not_called()
        assert result.exit_code != 0
        assert "require at least one option" in result.output

    def test_edit_requires_a_field(self, runner: CliRunner) -> None:
        with _auth(), _client():
            result = runner.invoke(cli, ["form", "questions", "edit", "form-uuid", "q1"])
        assert result.exit_code != 0
        assert "Nothing to edit" in result.output

    def test_edit_question_text(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.update_form_question.return_value = {"uuid": "q1", "question": "Reworded?"}
            result = runner.invoke(
                cli,
                ["form", "questions", "edit", "form-uuid", "q1", "--question", "Reworded?"],
            )
        assert result.exit_code == 0
        assert client.update_form_question.call_args[0][2] == {"question": "Reworded?"}

    def test_delete_confirmed(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.delete_form_question.return_value = {}
            result = runner.invoke(
                cli, ["form", "questions", "delete", "form-uuid", "q1"], input="y\n"
            )
        assert result.exit_code == 0
        client.delete_form_question.assert_called_once_with("form-uuid", "q1")

    def test_reorder(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.reorder_form_questions.return_value = {"reordered": True}
            result = runner.invoke(cli, ["form", "questions", "reorder", "form-uuid", "q2", "q1"])
        assert result.exit_code == 0
        assert client.reorder_form_questions.call_args[0][1] == ["q2", "q1"]


class TestFormListArchived:
    def test_include_archived_forwarded(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.list_forms.return_value = [
                {"id": "f1", "name": "Old", "is_archived": True, "questions": []}
            ]
            result = runner.invoke(cli, ["form", "list", "--include-archived"])
        assert result.exit_code == 0
        assert client.list_forms.call_args[1]["include_archived"] is True

    def test_archived_hidden_by_default(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.list_forms.return_value = []
            result = runner.invoke(cli, ["form", "list"])
        assert result.exit_code == 0
        assert client.list_forms.call_args[1]["include_archived"] is False


class TestFormResponsesExtended:
    def test_all_and_dates_forwarded(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.list_form_responses.return_value = []
            client.get_form.return_value = FORM_PAYLOAD
            result = runner.invoke(
                cli,
                [
                    "form",
                    "responses",
                    "form-uuid",
                    "--all",
                    "--user",
                    "user-uuid",
                    "--from",
                    "2026-01-01",
                    "--to",
                    "2026-06-30",
                ],
            )
        assert result.exit_code == 0
        kwargs = client.list_form_responses.call_args[1]
        assert kwargs["all_responses"] is True
        assert kwargs["user"] == "user-uuid"
        assert kwargs["date_from"] == "2026-01-01"
        assert kwargs["date_to"] == "2026-06-30"

    def test_member_all_forbidden(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.list_form_responses.side_effect = APIError(
                status_code=403,
                detail="Forbidden",
                code="form_response_view_all_forbidden",
            )
            result = runner.invoke(cli, ["form", "responses", "form-uuid", "--all"])
        assert result.exit_code == 4
