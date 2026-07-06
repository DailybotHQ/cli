"""Tests for the interactive question builder and its --interactive wiring."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.commands.authoring_helpers import (
    AuthoringError,
    build_questions_interactively,
)
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _prompt(value: Any) -> MagicMock:
    """A questionary prompt object whose .ask() returns value."""
    prompt: MagicMock = MagicMock()
    prompt.ask.return_value = value
    return prompt


class TestBuildQuestionsInteractively:
    @patch("dailybot_cli.commands.authoring_helpers.sys.stdin.isatty", return_value=True)
    @patch("dailybot_cli.commands.authoring_helpers.questionary")
    def test_builds_two_questions(self, mock_q: MagicMock, _isatty: MagicMock) -> None:
        # Q1: text, required, add another -> yes. Q2: multiple_choice + options, stop.
        mock_q.select.side_effect = [_prompt("text"), _prompt("multiple_choice")]
        # text() order per question: question text, (options for mc), short title.
        mock_q.text.side_effect = [
            _prompt("What went well?"),
            _prompt("Wins"),  # Q1 short report title
            _prompt("Rating?"),
            _prompt("A, B, C"),
            _prompt("Rating"),  # Q2 short report title
        ]
        mock_q.confirm.side_effect = [
            _prompt(True),  # Q1 required?
            _prompt(False),  # Q1 blocker?
            _prompt(True),  # add another?
            _prompt(True),  # Q2 required?
            _prompt(False),  # Q2 blocker?
            _prompt(False),  # add another? -> stop
        ]

        result: list[dict[str, Any]] = build_questions_interactively()
        assert len(result) == 2
        assert result[0]["question_type"] == "text"
        assert result[0]["is_blocker"] is False
        assert result[0]["short_question"] == "Wins"
        assert result[1]["question_type"] == "multiple_choice"
        assert result[1]["options"] == ["A", "B", "C"]
        assert result[1]["short_question"] == "Rating"

    @patch("dailybot_cli.commands.authoring_helpers.sys.stdin.isatty", return_value=True)
    @patch("dailybot_cli.commands.authoring_helpers.questionary")
    def test_ai_short_question_skips_title_prompt(
        self, mock_q: MagicMock, _isatty: MagicMock
    ) -> None:
        mock_q.select.side_effect = [_prompt("text")]
        mock_q.text.side_effect = [_prompt("What went well?")]  # no short-title prompt
        mock_q.confirm.side_effect = [
            _prompt(True),  # required?
            _prompt(False),  # blocker?
            _prompt(False),  # add another? -> stop
        ]
        result: list[dict[str, Any]] = build_questions_interactively(ai_short_question=True)
        assert len(result) == 1
        assert "short_question" not in result[0]

    @patch("dailybot_cli.commands.authoring_helpers.sys.stdin.isatty", return_value=True)
    @patch("dailybot_cli.commands.authoring_helpers.questionary")
    def test_cancel_returns_empty(self, mock_q: MagicMock, _isatty: MagicMock) -> None:
        mock_q.select.return_value = _prompt(None)  # user pressed Esc
        assert build_questions_interactively() == []

    @patch("dailybot_cli.commands.authoring_helpers.sys.stdin.isatty", return_value=False)
    def test_non_tty_raises(self, _isatty: MagicMock) -> None:
        with pytest.raises(AuthoringError):
            build_questions_interactively()


class TestInteractiveWiring:
    @patch("dailybot_cli.commands.form.build_questions_interactively")
    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_form_create_interactive(
        self,
        mock_client_cls: MagicMock,
        _auth: MagicMock,
        mock_builder: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_builder.return_value = [{"question_type": "text", "question": "Q?"}]
        client: MagicMock = mock_client_cls.return_value
        client.create_form.return_value = {"id": "f-1", "name": "Retro", "questions": []}

        result = runner.invoke(
            cli, ["form", "create", "-n", "Retro", "--interactive", "--ai-short-question"]
        )
        assert result.exit_code == 0
        mock_builder.assert_called_once()
        assert client.create_form.call_args[0][1] == [{"question_type": "text", "question": "Q?"}]

    @patch("dailybot_cli.commands.checkin.build_questions_interactively")
    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
    @patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
    def test_checkin_create_interactive(
        self,
        mock_client_cls: MagicMock,
        _auth: MagicMock,
        mock_builder: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_builder.return_value = [{"question_type": "boolean", "question": "Blockers?"}]
        client: MagicMock = mock_client_cls.return_value
        client.create_checkin.return_value = {"id": "fu-1", "name": "Standup", "questions": []}
        client.list_teams.return_value = [{"uuid": "t-1", "name": "Eng"}]

        result = runner.invoke(
            cli,
            [
                "checkin",
                "create",
                "-n",
                "Standup",
                "--interactive",
                "--team",
                "Eng",
                "--ai-short-question",
            ],
        )
        assert result.exit_code == 0
        mock_builder.assert_called_once()
        assert client.create_checkin.call_args[1]["questions"] == [
            {"question_type": "boolean", "question": "Blockers?"}
        ]
