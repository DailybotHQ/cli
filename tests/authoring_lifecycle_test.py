"""End-to-end authoring lifecycle tests (mocked httpx / client).

Exercises the full flows a real agent would drive, plus credential parity,
error paths, and JSON mode. No network calls.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _auth() -> Any:
    return patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")


def _client() -> Any:
    return patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")


class TestFormLifecycle:
    def test_full_form_authoring_flow(self, runner: CliRunner, tmp_path: Any) -> None:
        qfile = tmp_path / "q.json"
        qfile.write_text(
            json.dumps([{"question_type": "text", "question": "Well?", "short_question": "Wins"}])
        )
        form: dict[str, Any] = {
            "id": "f-1",
            "name": "Retro",
            "questions": [{"uuid": "q1", "question": "Well?", "question_type": "text"}],
        }
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.list_report_channels.return_value = [{"uuid": "chan-1", "name": "#eng"}]
            client.create_form.return_value = form
            client.update_form_config.return_value = form
            client.add_form_question.return_value = {"uuid": "q2", "question": "Rating?"}
            client.reorder_form_questions.return_value = {"reordered": True}
            client.update_form_question.return_value = {"uuid": "q2", "question": "Rate?"}
            client.delete_form_question.return_value = {}
            client.list_form_responses.return_value = [{"id": "r1"}]
            client.get_form.return_value = form
            client.update_form_response.return_value = {"id": "r1"}
            client.archive_form.return_value = {}

            steps: list[list[str]] = [
                ["channels", "list"],
                ["form", "create", "-n", "Retro", "--questions-file", str(qfile)],
                [
                    "form",
                    "questions",
                    "add",
                    "f-1",
                    "--type",
                    "text",
                    "--question",
                    "Rating?",
                    "--short-question",
                    "Rating",
                ],
                ["form", "questions", "reorder", "f-1", "q2", "q1"],
                ["form", "questions", "edit", "f-1", "q2", "--question", "Rate?"],
                ["form", "questions", "delete", "f-1", "q2", "--yes"],
                ["form", "responses", "f-1", "--all", "--from", "2026-01-01"],
                ["form", "update", "f-1", "r1", "-c", '{"q1": "fixed"}', "--yes"],
                ["form", "archive", "f-1", "--yes"],
            ]
            for step in steps:
                result = runner.invoke(cli, step)
                assert result.exit_code == 0, f"{step} -> {result.output}"

            client.create_form.assert_called_once()
            client.add_form_question.assert_called_once()
            client.reorder_form_questions.assert_called_once_with("f-1", ["q2", "q1"])
            client.delete_form_question.assert_called_once_with("f-1", "q2")
            client.archive_form.assert_called_once_with("f-1")
            assert client.list_form_responses.call_args[1]["all_responses"] is True
            # Editing another user's response goes through the same update path.
            client.update_form_response.assert_called_once()


class TestCheckinLifecycle:
    def test_full_checkin_authoring_flow(self, runner: CliRunner) -> None:
        checkin: dict[str, Any] = {"id": "fu-1", "name": "Standup", "questions": []}
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.create_checkin.return_value = checkin
            client.add_checkin_question.return_value = {"uuid": "q1"}
            client.update_checkin_question.return_value = {"uuid": "q1"}
            client.reorder_checkin_questions.return_value = {"reordered": True}
            client.delete_checkin_question.return_value = {}
            client.update_checkin_config.return_value = checkin
            client.list_checkin_responses.return_value = [{"uuid": "r1"}]
            client.archive_checkin.return_value = {}
            client.list_teams.return_value = [{"uuid": "t-1", "name": "Eng"}]

            steps: list[list[str]] = [
                [
                    "checkin",
                    "create",
                    "-n",
                    "Standup",
                    "--time",
                    "09:00",
                    "--days",
                    "1,2,3",
                    "--team",
                    "Eng",
                ],
                [
                    "checkin",
                    "questions",
                    "add",
                    "fu-1",
                    "--type",
                    "text",
                    "--question",
                    "Today?",
                    "--short-question",
                    "Today",
                ],
                ["checkin", "questions", "edit", "fu-1", "q1", "--question", "Focus?"],
                ["checkin", "questions", "reorder", "fu-1", "q1"],
                ["checkin", "questions", "delete", "fu-1", "q1", "--yes"],
                ["checkin", "config", "fu-1", "--inactive"],
                ["checkin", "archive", "fu-1", "--yes"],
            ]
            for step in steps:
                result = runner.invoke(cli, step)
                assert result.exit_code == 0, f"{step} -> {result.output}"

            assert client.update_checkin_config.call_args[1]["is_active"] is False
            client.archive_checkin.assert_called_once_with("fu-1")


class TestCredentialParity:
    """Both Bearer and API key must reach the authoring endpoints (client-level)."""

    def test_create_form_bearer_header(self) -> None:
        client: DailyBotClient = DailyBotClient(
            api_url="http://test-api.example.com", token="bearer-tok", api_key=None
        )
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "f-1"}
        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.create_form("Retro")
        headers = mock_post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer bearer-tok"
        assert "X-API-KEY" not in headers

    def test_create_form_api_key_header(self) -> None:
        client: DailyBotClient = DailyBotClient(
            api_url="http://test-api.example.com", token=None, api_key="org-key"
        )
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "f-1"}
        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.create_form("Retro")
        headers = mock_post.call_args[1]["headers"]
        assert headers["X-API-KEY"] == "org-key"
        assert "Authorization" not in headers


class TestErrorPaths:
    def test_member_all_forbidden(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            cls.return_value.list_form_responses.side_effect = APIError(
                status_code=403, detail="Forbidden", code="form_response_view_all_forbidden"
            )
            result = runner.invoke(cli, ["form", "responses", "f-1", "--all"])
        assert result.exit_code == 4

    def test_unknown_form_404(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            cls.return_value.archive_form.side_effect = APIError(
                status_code=404, detail="Not found", code="form_not_found"
            )
            result = runner.invoke(cli, ["form", "archive", "f-1", "--yes"])
        assert result.exit_code == 5
        assert "Form not found" in result.output

    def test_invalid_question_type_400ish(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            result = runner.invoke(
                cli, ["form", "questions", "add", "f-1", "--type", "x", "--question", "Q?"]
            )
            cls.return_value.add_form_question.assert_not_called()
        assert result.exit_code != 0


class TestJsonMode:
    def test_create_form_json(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            cls.return_value.create_form.return_value = {"id": "f-1", "name": "Retro"}
            result = runner.invoke(cli, ["form", "create", "-n", "Retro", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["id"] == "f-1"

    def test_channels_list_json(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            cls.return_value.list_report_channels.return_value = [{"uuid": "chan-1"}]
            result = runner.invoke(cli, ["channels", "list", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)[0]["uuid"] == "chan-1"
