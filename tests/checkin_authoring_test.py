"""Tests for check-in authoring commands (create/config/archive/questions)."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError
from dailybot_cli.main import cli

CHECKIN_PAYLOAD: dict[str, Any] = {
    "id": "fu-1",
    "name": "Standup",
    "schedule": {"days": [1, 2, 3, 4, 5], "time": "09:00", "timezone": "UTC"},
    "questions": [],
}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _auth() -> Any:
    return patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")


def _client() -> Any:
    return patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")


class TestCheckinCreate:
    def test_create_with_schedule(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.create_checkin.return_value = CHECKIN_PAYLOAD
            client.list_teams.return_value = [{"uuid": "t-1", "name": "Eng"}]
            result = runner.invoke(
                cli,
                [
                    "checkin",
                    "create",
                    "-n",
                    "Standup",
                    "--time",
                    "09:00",
                    "--days",
                    "1,2,3,4,5",
                    "--timezone",
                    "UTC",
                    "--team",
                    "Eng",
                ],
            )
        assert result.exit_code == 0
        schedule = client.create_checkin.call_args[1]["schedule"]
        assert schedule == {"days": [1, 2, 3, 4, 5], "time": "09:00", "timezone": "UTC"}

    def test_create_forwards_config_flags(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.create_checkin.return_value = CHECKIN_PAYLOAD
            client.list_teams.return_value = [{"uuid": "t-1", "name": "Eng"}]
            result = runner.invoke(
                cli,
                [
                    "checkin",
                    "create",
                    "-n",
                    "Standup",
                    "--team",
                    "Eng",
                    "--frequency",
                    "weekly",
                    "--reminders",
                    "2",
                    "--no-future",
                ],
            )
        assert result.exit_code == 0
        cfg = client.create_checkin.call_args[1]["config"]
        assert cfg == {
            "frequency_type": "weekly",
            "reminders_max_count": 2,
            "allow_future_responses": False,
        }

    def test_create_without_participants_is_rejected(self, runner: CliRunner) -> None:
        # Non-interactive create with no --user/--team must error, never create empty.
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            result = runner.invoke(
                cli, ["checkin", "create", "-n", "Standup", "--time", "09:00", "--days", "1"]
            )
            client.create_checkin.assert_not_called()
        assert result.exit_code != 0
        assert "at least one participant" in result.output

    def test_create_resolves_participants(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.create_checkin.return_value = CHECKIN_PAYLOAD
            client.list_users.return_value = [{"uuid": "u-1", "full_name": "Jane Doe"}]
            client.list_teams.return_value = [{"uuid": "t-1", "name": "Eng"}]
            result = runner.invoke(
                cli,
                ["checkin", "create", "-n", "Standup", "--user", "Jane Doe", "--team", "Eng"],
            )
        assert result.exit_code == 0
        participants = client.create_checkin.call_args[1]["participants"]
        assert participants == {"user_uuids": ["u-1"], "team_uuids": ["t-1"]}

    def test_create_bad_time_fails_fast(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            result = runner.invoke(cli, ["checkin", "create", "-n", "Standup", "--time", "9am"])
            cls.return_value.create_checkin.assert_not_called()
        assert result.exit_code != 0
        assert "HH:MM" in result.output


class TestCheckinConfig:
    def test_config_inactive_sends_false(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.update_checkin_config.return_value = CHECKIN_PAYLOAD
            result = runner.invoke(cli, ["checkin", "config", "fu-1", "--inactive"])
        assert result.exit_code == 0
        assert client.update_checkin_config.call_args[1]["is_active"] is False

    def test_config_requires_a_field(self, runner: CliRunner) -> None:
        with _auth(), _client():
            result = runner.invoke(cli, ["checkin", "config", "fu-1"])
        assert result.exit_code != 0
        assert "Nothing to edit" in result.output

    def test_config_schedule_time(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.update_checkin_config.return_value = CHECKIN_PAYLOAD
            result = runner.invoke(cli, ["checkin", "config", "fu-1", "--time", "10:00"])
        assert result.exit_code == 0
        assert client.update_checkin_config.call_args[1]["schedule"] == {"time": "10:00"}

    def test_config_participants_forwarded(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.update_checkin_config.return_value = CHECKIN_PAYLOAD
            client.list_teams.return_value = [{"uuid": "t-1", "name": "Eng"}]
            result = runner.invoke(cli, ["checkin", "config", "fu-1", "--team", "Eng"])
        assert result.exit_code == 0
        assert client.update_checkin_config.call_args[1]["participants"] == {"team_uuids": ["t-1"]}

    def test_config_reminders_forwarded(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.update_checkin_config.return_value = CHECKIN_PAYLOAD
            result = runner.invoke(
                cli,
                ["checkin", "config", "fu-1", "--reminders", "3", "--reminder-interval", "30"],
            )
        assert result.exit_code == 0
        cfg = client.update_checkin_config.call_args[1]["config"]
        assert cfg == {"reminders_max_count": 3, "reminders_frequency_time": 30}

    def test_config_behavior_toggles_forwarded(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.update_checkin_config.return_value = CHECKIN_PAYLOAD
            result = runner.invoke(
                cli, ["checkin", "config", "fu-1", "--no-past", "--privacy", "everyone"]
            )
        assert result.exit_code == 0
        cfg = client.update_checkin_config.call_args[1]["config"]
        assert cfg == {"allow_past_responses": False, "privacy": "everyone"}

    def test_config_ai_and_advanced_flags_forwarded(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.update_checkin_config.return_value = CHECKIN_PAYLOAD
            result = runner.invoke(
                cli,
                [
                    "checkin",
                    "config",
                    "fu-1",
                    "--smart",
                    "--intelligence",
                    "--max-clarifying",
                    "2",
                    "--reminder-tone",
                    "standard",
                    "--frequency-advanced",
                    "custom",
                    "--cron",
                    "0 9 * * 1,3,5",
                ],
            )
        assert result.exit_code == 0
        cfg = client.update_checkin_config.call_args[1]["config"]
        assert cfg == {
            "is_smart_checkin": True,
            "is_intelligence_enabled": True,
            "max_clarifying_questions": 2,
            "reminder_tone": "standard",
            "frequency_advanced": "custom",
            "frequency_cron": "0 9 * * 1,3,5",
        }

    def test_intelligence_dependency_error_is_friendly(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.update_checkin_config.side_effect = APIError(
                status_code=400,
                detail="AI intelligence requires smart mode.",
                code="intelligence_requires_smart_checkin",
            )
            result = runner.invoke(cli, ["checkin", "config", "fu-1", "--intelligence"])
        assert result.exit_code != 0
        assert "--smart" in result.output

    def test_config_invalid_reminder_count_fails_fast(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            result = runner.invoke(cli, ["checkin", "config", "fu-1", "--reminders", "9"])
            cls.return_value.update_checkin_config.assert_not_called()
        assert result.exit_code != 0
        assert "between 0 and 5" in result.output

    def test_unknown_field_error_is_friendly(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.update_checkin_config.side_effect = APIError(
                status_code=400, detail="Unknown field(s): bogus", code="unknown_field"
            )
            result = runner.invoke(cli, ["checkin", "config", "fu-1", "--reminders", "3"])
        assert result.exit_code != 0
        assert "upgrade" in result.output  # maps to the "run dailybot upgrade" hint

    def test_server_zero_participant_error_is_friendly(self, runner: CliRunner) -> None:
        # Server-side backstop (checkin_requires_participant) maps to guidance.
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.list_teams.return_value = [{"uuid": "t-1", "name": "Eng"}]
            client.update_checkin_config.side_effect = APIError(
                status_code=400,
                detail="A check-in must have at least one participant.",
                code="checkin_requires_participant",
            )
            result = runner.invoke(cli, ["checkin", "config", "fu-1", "--team", "Eng"])
        assert result.exit_code != 0
        assert "--user and/or --team" in result.output


class TestCheckinArchive:
    def test_archive_confirmed(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.archive_checkin.return_value = {}
            result = runner.invoke(cli, ["checkin", "archive", "fu-1"], input="y\n")
        assert result.exit_code == 0
        client.archive_checkin.assert_called_once_with("fu-1")

    def test_archive_aborts(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            result = runner.invoke(cli, ["checkin", "archive", "fu-1"], input="n\n")
        assert result.exit_code != 0
        client.archive_checkin.assert_not_called()


class TestCheckinQuestions:
    def test_add(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.add_checkin_question.return_value = {"uuid": "q-new", "question": "Blockers?"}
            result = runner.invoke(
                cli,
                [
                    "checkin",
                    "questions",
                    "add",
                    "fu-1",
                    "--type",
                    "boolean",
                    "--question",
                    "Blockers?",
                    "--ai-short-question",
                ],
            )
        assert result.exit_code == 0
        assert client.add_checkin_question.call_args[0][1]["question_type"] == "boolean"

    def test_add_with_blocker(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.add_checkin_question.return_value = {"uuid": "q-new"}
            result = runner.invoke(
                cli,
                [
                    "checkin",
                    "questions",
                    "add",
                    "fu-1",
                    "--type",
                    "boolean",
                    "--question",
                    "Any blockers?",
                    "--blocker",
                    "--ai-short-question",
                ],
            )
        assert result.exit_code == 0
        assert client.add_checkin_question.call_args[0][1]["is_blocker"] is True

    def test_add_with_short_question_and_variations(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.add_checkin_question.return_value = {"uuid": "q-new"}
            result = runner.invoke(
                cli,
                [
                    "checkin",
                    "questions",
                    "add",
                    "fu-1",
                    "--type",
                    "text",
                    "--question",
                    "What did you do?",
                    "--short-question",
                    "Yesterday",
                    "--variation",
                    "What happened?",
                    "--variation",
                    "What went well?",
                ],
            )
        assert result.exit_code == 0
        payload = client.add_checkin_question.call_args[0][1]
        assert payload["short_question"] == "Yesterday"
        assert payload["variations"] == ["What happened?", "What went well?"]

    def test_add_with_inline_jump_logic(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.add_checkin_question.return_value = {"uuid": "q-new"}
            result = runner.invoke(
                cli,
                [
                    "checkin",
                    "questions",
                    "add",
                    "fu-1",
                    "--type",
                    "boolean",
                    "--question",
                    "Any blockers?",
                    "--jump-if-equals",
                    "No",
                    "--jump-to",
                    "-1",
                    "--ai-short-question",
                ],
            )
        assert result.exit_code == 0
        logic = client.add_checkin_question.call_args[0][1]["logic"]
        rule = logic["rules"]["rules_if"][0]
        assert rule["conditions"][0]["comparison_value"] == "No"
        assert rule["then"] == {"action": "jump_to", "target": -1}

    def test_add_jump_to_without_value_fails_fast(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            result = runner.invoke(
                cli,
                [
                    "checkin",
                    "questions",
                    "add",
                    "fu-1",
                    "--type",
                    "text",
                    "--question",
                    "Q?",
                    "--jump-to",
                    "2",
                    "--ai-short-question",
                ],
            )
            cls.return_value.add_checkin_question.assert_not_called()
        assert result.exit_code != 0
        assert "--jump-if-equals" in result.output

    def test_add_without_short_question_is_rejected(self, runner: CliRunner) -> None:
        # A report title is required unless --ai-short-question opts into AI titling.
        with _auth(), _client() as cls:
            result = runner.invoke(
                cli,
                ["checkin", "questions", "add", "fu-1", "--type", "text", "--question", "Q?"],
            )
            cls.return_value.add_checkin_question.assert_not_called()
        assert result.exit_code != 0
        assert "report title" in result.output

    def test_anonymous_irreversible_error_is_friendly(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.update_checkin_config.side_effect = APIError(
                status_code=400,
                detail="An anonymous check-in cannot be made non-anonymous.",
                code="anonymous_irreversible",
            )
            result = runner.invoke(cli, ["checkin", "config", "fu-1", "--no-anonymous"])
        assert result.exit_code != 0
        assert "non-anonymous" in result.output

    def test_edit_blocker_toggle(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.update_checkin_question.return_value = {"uuid": "q1"}
            result = runner.invoke(cli, ["checkin", "questions", "edit", "fu-1", "q1", "--blocker"])
        assert result.exit_code == 0
        assert client.update_checkin_question.call_args[0][2] == {"is_blocker": True}

    def test_edit(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.update_checkin_question.return_value = {"uuid": "q1"}
            result = runner.invoke(
                cli,
                ["checkin", "questions", "edit", "fu-1", "q1", "--question", "New?"],
            )
        assert result.exit_code == 0
        assert client.update_checkin_question.call_args[0][2] == {"question": "New?"}

    def test_delete_confirmed(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.delete_checkin_question.return_value = {}
            result = runner.invoke(
                cli, ["checkin", "questions", "delete", "fu-1", "q1"], input="y\n"
            )
        assert result.exit_code == 0
        client.delete_checkin_question.assert_called_once_with("fu-1", "q1")

    def test_reorder(self, runner: CliRunner) -> None:
        with _auth(), _client() as cls:
            client: MagicMock = cls.return_value
            client.reorder_checkin_questions.return_value = {"reordered": True}
            result = runner.invoke(cli, ["checkin", "questions", "reorder", "fu-1", "q2", "q1"])
        assert result.exit_code == 0
        assert client.reorder_checkin_questions.call_args[0][1] == ["q2", "q1"]
