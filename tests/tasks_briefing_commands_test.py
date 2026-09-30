"""`dailybot tasks briefing get|set|preview|send-test` (PLAN_004)."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.display import console
from dailybot_cli.main import cli

BRIEFING: dict[str, Any] = {
    "enabled": True,
    "weekdays": [1, 2, 3, 4, 5],
    "time": "08:30",
    "timezone": "UTC",
    "timezone_is_default": True,
    "chat": True,
    "email": False,
    "skip_when_empty": True,
    "effective": True,
    "last_sent_at": None,
}
DOCUMENT: dict[str, Any] = {
    "kind": "personal_daily",
    "header": {"title": "Hi Ana, here is your day", "period_label": "Wednesday, Sep 30, 2026"},
    "sections": [
        {
            "key": "overdue",
            "title": "Overdue",
            "count": 1,
            "empty": False,
            "items": [
                {
                    "type": "task",
                    "uuid": "t1",
                    "key": "ENG-2",
                    "title": "Fix the export timeout",
                    "badges": [],
                }
            ],
        }
    ],
    "empty": False,
}
DRY: dict[str, Any] = {"dry_run": True, "document": DOCUMENT, "sent": False}
SENT: dict[str, Any] = {"dry_run": False, "document": DOCUMENT, "sent": True}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    mock: MagicMock = MagicMock(spec=DailyBotClient)
    mock.get_my_briefing.return_value = BRIEFING
    mock.put_my_briefing.return_value = BRIEFING
    mock.get_my_briefing_preview.return_value = DOCUMENT
    mock.send_my_briefing_test.side_effect = lambda *, dry_run: DRY if dry_run else SENT
    return mock


@pytest.fixture(autouse=True)
def eighty_columns() -> Any:
    previous: int | None = console._width
    console.width = 80
    try:
        yield
    finally:
        console._width = previous


def _invoke(
    runner: CliRunner, client: MagicMock, args: list[str], *, input_text: str | None = None
) -> Any:
    with patch("dailybot_cli.commands.tasks_settings.require_auth", return_value=client):
        return runner.invoke(cli, ["tasks", "briefing", *args], input=input_text)


class TestWiring:
    def test_group_help_and_the_delivery_sentence(self, runner: CliRunner) -> None:
        assert "briefing" in runner.invoke(cli, ["tasks", "--help"]).output
        flat = " ".join(runner.invoke(cli, ["tasks", "briefing", "--help"]).output.split())
        assert "arrives by DM and/or email" in flat
        for sub in ("get", "set", "preview", "send-test"):
            result = runner.invoke(cli, ["tasks", "briefing", sub, "--help"])
            assert result.exit_code == 0 and "Examples" in result.output, sub


class TestGetAndPreview:
    def test_get(self, runner: CliRunner, client: MagicMock) -> None:
        out = _invoke(runner, client, ["get"])
        assert out.exit_code == 0 and "08:30" in out.output and "mon,tue,wed,thu,fri" in out.output
        assert json.loads(_invoke(runner, client, ["get", "--json"]).output) == BRIEFING

    def test_preview(self, runner: CliRunner, client: MagicMock) -> None:
        out = _invoke(runner, client, ["preview"])
        assert "Hi Ana" in out.output and "Fix the export timeout" in out.output
        assert json.loads(_invoke(runner, client, ["preview", "--json"]).output) == DOCUMENT

    def test_agent_or_org_keys_are_told_to_use_a_person(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_my_briefing.side_effect = APIError(400, "no person", code="actor_required")
        result = _invoke(runner, client, ["get"])
        assert result.exit_code == 3 and "personal" in result.output.lower()


class TestSet:
    def test_only_passed_fields_are_sent(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner, client, ["set", "--time", "8:30", "--weekdays", "mon,tue,wed,thu,fri"]
        )
        assert result.exit_code == 0, result.output
        assert client.put_my_briefing.call_args.kwargs == {
            "time": "08:30",
            "weekdays": [1, 2, 3, 4, 5],
        }

    def test_paired_booleans(self, runner: CliRunner, client: MagicMock) -> None:
        _invoke(runner, client, ["set", "--enabled", "--no-chat", "--email", "--send-when-empty"])
        assert client.put_my_briefing.call_args.kwargs == {
            "enabled": True,
            "chat": False,
            "email": True,
            "skip_when_empty": False,
        }
        _invoke(runner, client, ["set", "--disabled", "--skip-when-empty"])
        assert client.put_my_briefing.call_args.kwargs == {
            "enabled": False,
            "skip_when_empty": True,
        }

    def test_the_timezone_is_sent_only_when_passed(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        _invoke(runner, client, ["set", "--time", "09:00"])
        assert "timezone" not in client.put_my_briefing.call_args.kwargs
        _invoke(runner, client, ["set", "--timezone", "America/Bogota"])
        assert client.put_my_briefing.call_args.kwargs == {"timezone": "America/Bogota"}

    @pytest.mark.parametrize(
        "args", [["--weekdays", "funday"], ["--time", "25:00"], ["--timezone", "Mars/Base"]]
    )
    def test_bad_values_are_refused_locally(
        self, runner: CliRunner, client: MagicMock, args: list[str]
    ) -> None:
        assert _invoke(runner, client, ["set", *args]).exit_code == 2
        client.put_my_briefing.assert_not_called()

    def test_nothing_to_change_is_a_usage_error(self, runner: CliRunner, client: MagicMock) -> None:
        assert _invoke(runner, client, ["set"]).exit_code == 2
        client.put_my_briefing.assert_not_called()

    def test_the_answer_is_shown_or_passed_through(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        assert "Updated" in _invoke(runner, client, ["set", "--time", "08:30"]).output
        assert (
            json.loads(_invoke(runner, client, ["set", "--time", "08:30", "--json"]).output)
            == BRIEFING
        )

    def test_server_refusals_name_the_flag(self, runner: CliRunner, client: MagicMock) -> None:
        client.put_my_briefing.side_effect = APIError(
            400, "x", code="invalid_schedule", extra={"parameter": "time"}
        )
        result = _invoke(runner, client, ["set", "--time", "08:30"])
        assert result.exit_code == 2 and "--time" in result.output


class TestSendTest:
    def test_dry_run_previews_and_sends_nothing(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["send-test", "--dry-run"])
        assert (
            result.exit_code == 0
            and "Hi Ana" in result.output
            and "nothing was sent" in result.output.lower()
        )
        assert [c.kwargs["dry_run"] for c in client.send_my_briefing_test.call_args_list] == [True]

    def test_a_real_send_previews_first_then_asks(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        assert _invoke(runner, client, ["send-test"], input_text="y\n").exit_code == 0
        assert [c.kwargs["dry_run"] for c in client.send_my_briefing_test.call_args_list] == [
            True,
            False,
        ]

    def test_declining_sends_nothing(self, runner: CliRunner, client: MagicMock) -> None:
        assert _invoke(runner, client, ["send-test"], input_text="n\n").exit_code == 7
        assert [c.kwargs["dry_run"] for c in client.send_my_briefing_test.call_args_list] == [True]

    def test_yes_and_json(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["send-test", "--yes", "--json"])
        assert json.loads(result.stdout)["sent"] is True
        assert [c.kwargs["dry_run"] for c in client.send_my_briefing_test.call_args_list] == [
            True,
            False,
        ]
