"""Tests for forms & check-ins authoring helpers and display renderers."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from dailybot_cli import display
from dailybot_cli.commands.authoring_helpers import (
    MAX_QUESTIONS,
    AuthoringError,
    build_question,
    parse_options,
    parse_participants,
    parse_questions_file,
    parse_schedule,
)


class TestBuildQuestion:
    def test_text_question(self) -> None:
        result: dict[str, Any] = build_question("text", "What went well?")
        assert result == {
            "question_type": "text",
            "question": "What went well?",
            "required": True,
        }

    def test_multiple_choice_with_options(self) -> None:
        result: dict[str, Any] = build_question(
            "multiple_choice", "Rating?", options=["A", "B"], required=False
        )
        assert result["options"] == ["A", "B"]
        assert result["required"] is False

    def test_invalid_type_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_question("rating", "How many stars?")

    def test_multiple_choice_without_options_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_question("multiple_choice", "Rating?")

    def test_boolean_with_options_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_question("boolean", "Blockers?", options=["Yes", "No"])

    def test_blank_text_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_question("text", "   ")

    def test_type_is_normalized(self) -> None:
        assert build_question("TEXT", "Q?")["question_type"] == "text"


class TestParseOptions:
    def test_splits_and_trims(self) -> None:
        assert parse_options("a, b ,c") == ["a", "b", "c"]

    def test_none_passthrough(self) -> None:
        assert parse_options(None) is None

    def test_empty_becomes_none(self) -> None:
        assert parse_options(" , ") is None


class TestParseQuestionsFile:
    def test_valid_file(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "questions.json"
        path.write_text(
            json.dumps(
                [
                    {"question_type": "text", "question": "What went well?"},
                    {"type": "multiple_choice", "label": "Rating?", "options": ["A", "B"]},
                ]
            )
        )
        result: list[dict[str, Any]] = parse_questions_file(str(path))
        assert len(result) == 2
        assert result[1]["question_type"] == "multiple_choice"
        assert result[1]["question"] == "Rating?"

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(AuthoringError):
            parse_questions_file(str(tmp_path / "nope.json"))

    def test_non_array_rejected(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "q.json"
        path.write_text(json.dumps({"not": "a list"}))
        with pytest.raises(AuthoringError):
            parse_questions_file(str(path))

    def test_invalid_json_rejected(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "q.json"
        path.write_text("{not json")
        with pytest.raises(AuthoringError):
            parse_questions_file(str(path))

    def test_limit_exceeded_rejected(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "q.json"
        path.write_text(
            json.dumps(
                [{"question_type": "text", "question": f"Q{i}"} for i in range(MAX_QUESTIONS + 1)]
            )
        )
        with pytest.raises(AuthoringError):
            parse_questions_file(str(path))


class TestParseSchedule:
    def test_from_flags(self) -> None:
        result: dict[str, Any] | None = parse_schedule(
            days="1,2,3,4,5", time="09:00", timezone="UTC"
        )
        assert result == {"days": [1, 2, 3, 4, 5], "time": "09:00", "timezone": "UTC"}

    def test_none_when_empty(self) -> None:
        assert parse_schedule() is None

    def test_bad_day_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            parse_schedule(days="1,9")

    def test_non_integer_day_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            parse_schedule(days="mon,tue")

    def test_bad_time_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            parse_schedule(time="9am")

    def test_from_file(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "sched.json"
        path.write_text(json.dumps({"days": [0], "time": "10:30", "timezone": "UTC"}))
        result: dict[str, Any] | None = parse_schedule(schedule_file=str(path))
        assert result == {"days": [0], "time": "10:30", "timezone": "UTC"}

    def test_file_with_bad_day_rejected(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "sched.json"
        path.write_text(json.dumps({"days": [7]}))
        with pytest.raises(AuthoringError):
            parse_schedule(schedule_file=str(path))


class TestParseParticipants:
    def test_resolves_users_and_teams(self) -> None:
        client: MagicMock = MagicMock()
        client.list_users.return_value = [{"uuid": "u-1", "full_name": "Jane Doe"}]
        client.list_teams.return_value = [{"uuid": "t-1", "name": "My Team"}]

        result: dict[str, Any] = parse_participants(("Jane Doe",), ("My Team",), client)
        assert result == {"user_uuids": ["u-1"], "team_uuids": ["t-1"]}

    def test_empty_groups_omitted(self) -> None:
        client: MagicMock = MagicMock()
        assert parse_participants((), (), client) == {}
        client.list_users.assert_not_called()


class TestAuthoringDisplay:
    def test_report_channels_table(self) -> None:
        with display.console.capture() as capture:
            display.print_report_channels(
                [{"uuid": "c-1", "name": "#engineering", "platform": "slack"}]
            )
        output: str = capture.get()
        assert "engineering" in output
        assert "slack" in output

    def test_report_channels_empty(self) -> None:
        with display.console.capture() as capture:
            display.print_report_channels([])
        assert "No report channels" in capture.get()

    def test_form_created(self) -> None:
        with display.console.capture() as capture:
            display.print_form_created(
                {
                    "id": "f-1",
                    "name": "Retro",
                    "questions": [{"uuid": "q1", "question": "Well?", "question_type": "text"}],
                }
            )
        output: str = capture.get()
        assert "Retro" in output
        assert "Well?" in output

    def test_checkin_created(self) -> None:
        with display.console.capture() as capture:
            display.print_checkin_created(
                {
                    "id": "fu-1",
                    "name": "Standup",
                    "schedule": {"days": [1, 2], "time": "09:00", "timezone": "UTC"},
                    "questions": [],
                }
            )
        output: str = capture.get()
        assert "Standup" in output
        assert "09:00" in output

    def test_questions_table_empty(self) -> None:
        with display.console.capture() as capture:
            display.print_questions_table([])
        assert "No questions" in capture.get()
