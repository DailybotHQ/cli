"""Tests for check-in authoring commands (create/config/archive/questions)."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

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
                ],
            )
        assert result.exit_code == 0
        assert client.add_checkin_question.call_args[0][1]["is_blocker"] is True

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
