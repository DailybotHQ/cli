"""`dailybot plan tasks reports list|get|create|update|delete|preview|send-test|runs` (PLAN_004)."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient, PaginatedResult
from dailybot_cli.display import console
from dailybot_cli.main import cli

REPORT_ID: str = "00000000-0000-0000-0000-0000000000b1"
USER_ID: str = "00000000-0000-0000-0000-0000000000c1"
BOARD_ID: str = "00000000-0000-0000-0000-0000000000d1"
CHANNEL: dict[str, str] = {"external_id": "C0000000A", "name": "eng", "type": "channel"}
USER: dict[str, Any] = {"uuid": USER_ID, "name": "Ana Ruiz"}
REPORT: dict[str, Any] = {
    "uuid": REPORT_ID,
    "name": "Week End",
    "kind": "week_end",
    "enabled": True,
    "weekdays": [5],
    "time": "09:00",
    "timezone": "America/Bogota",
    "channel": CHANNEL,
    "email_recipients": [USER],
    "scope": {"type": "all", "uuids": []},
    "last_run": None,
}
DOCUMENT: dict[str, Any] = {
    "kind": "week_end",
    "header": {"title": "Week in review", "period_label": "Week of Sep 28"},
    "sections": [
        {
            "key": "done",
            "title": "Completed this week",
            "count": 1,
            "empty": False,
            "items": [
                {
                    "type": "task",
                    "uuid": "t1",
                    "key": "ENG-4",
                    "title": "Rotate the API keys",
                    "badges": [],
                }
            ],
        }
    ],
    "empty": False,
}
DRY: dict[str, Any] = {
    "dry_run": True,
    "document": DOCUMENT,
    "channel": CHANNEL,
    "email_recipients": [USER],
    "sent": False,
}
SENT: dict[str, Any] = {
    **DRY,
    "dry_run": False,
    "sent": True,
    "run": {"uuid": "r1", "status": "sent"},
}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    mock: MagicMock = MagicMock(spec=DailyBotClient)
    mock.search_channels.return_value = PaginatedResult(results=[CHANNEL], count=1)
    mock.list_users.return_value = [
        {"uuid": USER_ID, "full_name": "Ana Ruiz"},
        {"uuid": "00000000-0000-0000-0000-0000000000c2", "full_name": "Bo Chen"},
    ]
    mock.list_reports.return_value = PaginatedResult(
        results=[REPORT], count=1, extra={"viewer": {"can_manage": True}}
    )
    mock.get_report.return_value = REPORT
    mock.create_report.return_value = {**REPORT, "_idempotency_key": "key-1"}
    mock.update_report.return_value = REPORT
    mock.delete_report.return_value = {}
    mock.get_report_preview.return_value = DOCUMENT
    mock.send_report_test.side_effect = lambda _u, *, dry_run: DRY if dry_run else SENT
    mock.list_report_runs.return_value = PaginatedResult(
        results=[
            {
                "uuid": "r1",
                "period_key": "2026-W40",
                "status": "sent",
                "error": None,
                "is_test": True,
                "email_count": 1,
                "channel_message_id": "bm-1",
                "sent_at": "2026-09-30T10:38:31Z",
            }
        ],
        count=1,
    )
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
        return runner.invoke(cli, ["plan", "tasks", "reports", *args], input=input_text)


def _create(runner: CliRunner, client: MagicMock, *extra: str) -> Any:
    return _invoke(runner, client, ["create", "--name", "Week End", *extra])


class TestWiring:
    def test_group_and_help(self, runner: CliRunner) -> None:
        assert "reports" in runner.invoke(cli, ["plan", "tasks", "--help"]).output
        for sub in ("list", "get", "create", "update", "delete", "preview", "send-test", "runs"):
            result = runner.invoke(cli, ["plan", "tasks", "reports", sub, "--help"])
            assert result.exit_code == 0 and "Examples" in result.output, sub


class TestReads:
    def test_list_get_preview_runs(self, runner: CliRunner, client: MagicMock) -> None:
        assert REPORT_ID in _invoke(runner, client, ["list"]).output
        assert json.loads(_invoke(runner, client, ["list", "--json"]).output)["viewer"] == {
            "can_manage": True
        }
        assert REPORT_ID in _invoke(runner, client, ["get", REPORT_ID]).output
        assert "2026-W40" in _invoke(runner, client, ["runs", REPORT_ID]).output
        out = _invoke(runner, client, ["preview", REPORT_ID])
        assert "Week in review" in out.output and "Rotate the API keys" in out.output
        assert (
            json.loads(_invoke(runner, client, ["preview", REPORT_ID, "--json"]).output) == DOCUMENT
        )

    def test_a_reference_that_is_not_a_uuid_is_refused_locally(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        for sub in ("get", "preview", "runs", "delete", "send-test"):
            assert _invoke(runner, client, [sub, "Week End"]).exit_code == 2, sub


class TestCreateSchedule:
    def test_a_full_create(self, runner: CliRunner, client: MagicMock) -> None:
        result = _create(
            runner,
            client,
            "--kind",
            "week_end",
            "--weekdays",
            "fri",
            "--time",
            "9:30",
            "--timezone",
            "America/Bogota",
            "--channel",
            "eng",
            "--email-to",
            "Ana Ruiz",
        )
        assert result.exit_code == 0, result.output
        kwargs: dict[str, Any] = client.create_report.call_args.kwargs
        assert (
            kwargs["kind"] == "week_end" and kwargs["weekdays"] == [5] and kwargs["time"] == "09:30"
        )
        assert kwargs["timezone"] == "America/Bogota"
        assert kwargs["channel"] == {"external_id": "C0000000A"}
        assert kwargs["email_recipients"] == [USER_ID]
        assert "key-1" in result.output

    def test_defaults_by_kind(self, runner: CliRunner, client: MagicMock) -> None:
        for kind, days in (("daily", [1, 2, 3, 4, 5]), ("week_start", [1]), ("week_end", [5])):
            _create(runner, client, "--kind", kind, "--channel", "eng")
            kwargs: dict[str, Any] = client.create_report.call_args.kwargs
            assert kwargs["weekdays"] == days and kwargs["time"] == "09:00", kind

    def test_the_timezone_is_sent_only_when_passed(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        _create(runner, client, "--kind", "daily", "--channel", "eng")
        assert client.create_report.call_args.kwargs.get("timezone") is None

    @pytest.mark.parametrize(
        "args",
        [
            ["--kind", "week_end", "--weekdays", "thu,fri", "--channel", "eng"],
            ["--kind", "week_start", "--weekdays", "mon,tue", "--channel", "eng"],
        ],
    )
    def test_a_weekly_kind_with_two_weekdays_is_refused_locally(
        self, runner: CliRunner, client: MagicMock, args: list[str]
    ) -> None:
        result = _create(runner, client, *args)
        assert result.exit_code == 2 and "exactly one weekday" in result.output
        client.create_report.assert_not_called()

    @pytest.mark.parametrize(
        "args",
        [
            ["--kind", "daily", "--channel", "eng", "--weekdays", "funday"],
            ["--kind", "daily", "--channel", "eng", "--time", "25:00"],
            ["--kind", "daily", "--channel", "eng", "--time", "9am"],
            ["--kind", "daily", "--channel", "eng", "--timezone", "Mars/Base"],
            ["--kind", "monthly", "--channel", "eng"],
        ],
    )
    def test_bad_values_are_refused_locally(
        self, runner: CliRunner, client: MagicMock, args: list[str]
    ) -> None:
        assert _create(runner, client, *args).exit_code == 2
        client.create_report.assert_not_called()

    def test_a_report_needs_a_channel_or_a_recipient(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _create(runner, client, "--kind", "daily")
        assert (
            result.exit_code == 2 and "channel" in result.output and "--email-to" in result.output
        )
        client.create_report.assert_not_called()

    def test_email_only_is_fine(self, runner: CliRunner, client: MagicMock) -> None:
        assert _create(runner, client, "--kind", "daily", "--email-to", USER_ID).exit_code == 0
        assert client.create_report.call_args.kwargs["channel"] is None

    def test_recipients_resolve_by_name_uuid_and_repeat(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        _create(
            runner,
            client,
            "--kind",
            "daily",
            "--email-to",
            "ana ruiz",
            "--email-to",
            "Bo Chen",
            "--email-to",
            USER_ID,
        )
        assert client.create_report.call_args.kwargs["email_recipients"] == [
            USER_ID,
            "00000000-0000-0000-0000-0000000000c2",
        ]

    def test_an_unknown_recipient_is_refused_locally(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _create(runner, client, "--kind", "daily", "--email-to", "Nobody Here")
        assert result.exit_code == 2
        client.create_report.assert_not_called()

    def test_scope_disabled_and_the_key(self, runner: CliRunner, client: MagicMock) -> None:
        _create(
            runner,
            client,
            "--kind",
            "daily",
            "--channel",
            "eng",
            "--board",
            BOARD_ID,
            "--disabled",
            "--idempotency-key",
            "mine",
        )
        kwargs: dict[str, Any] = client.create_report.call_args.kwargs
        assert (
            kwargs["scope"] == {"type": "boards", "uuids": [BOARD_ID]}
            and kwargs["enabled"] is False
            and kwargs["idempotency_key"] == "mine"
        )

    def test_server_refusals_render_with_their_extra(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.create_report.side_effect = APIError(
            400, "x", code="report_schedules_limit_reached", extra={"limit": 10}
        )
        result = _create(runner, client, "--kind", "daily", "--channel", "eng")
        assert result.exit_code == 2 and "10" in result.output
        client.create_report.side_effect = APIError(
            400, "x", code="invalid_schedule", extra={"parameter": "time"}
        )
        assert "--time" in _create(runner, client, "--kind", "daily", "--channel", "eng").output


class TestUpdate:
    def test_only_passed_fields_are_sent(self, runner: CliRunner, client: MagicMock) -> None:
        _invoke(runner, client, ["update", REPORT_ID, "--time", "10:15"])
        assert client.update_report.call_args.kwargs == {"time": "10:15"}

    def test_no_channel_clears_it_when_recipients_remain(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        _invoke(runner, client, ["update", REPORT_ID, "--no-channel"])
        assert client.update_report.call_args.kwargs == {"clear_channel": True}

    def test_no_email_to_clears_recipients_when_a_channel_remains(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        _invoke(runner, client, ["update", REPORT_ID, "--no-email-to"])
        assert client.update_report.call_args.kwargs == {"clear_email_recipients": True}

    def test_clearing_the_last_destination_is_refused_locally(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_report.return_value = {**REPORT, "email_recipients": []}
        result = _invoke(runner, client, ["update", REPORT_ID, "--no-channel"])
        assert result.exit_code == 2 and "--email-to" in result.output
        client.update_report.assert_not_called()
        client.get_report.return_value = {**REPORT, "channel": None}
        assert _invoke(runner, client, ["update", REPORT_ID, "--no-email-to"]).exit_code == 2

    def test_no_channel_with_a_new_recipient_needs_no_read(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        _invoke(runner, client, ["update", REPORT_ID, "--no-channel", "--email-to", USER_ID])
        client.get_report.assert_not_called()
        assert client.update_report.call_args.kwargs == {
            "clear_channel": True,
            "email_recipients": [USER_ID],
        }

    def test_contradictory_flags_are_usage_errors(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        assert (
            _invoke(
                runner, client, ["update", REPORT_ID, "--channel", "eng", "--no-channel"]
            ).exit_code
            == 2
        )
        assert (
            _invoke(
                runner, client, ["update", REPORT_ID, "--email-to", USER_ID, "--no-email-to"]
            ).exit_code
            == 2
        )
        client.update_report.assert_not_called()

    def test_a_weekly_report_cannot_get_two_weekdays(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["update", REPORT_ID, "--weekdays", "thu,fri"])
        assert result.exit_code == 2 and "exactly one weekday" in result.output
        client.update_report.assert_not_called()

    def test_weekdays_update_passes_for_a_daily_report(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_report.return_value = {**REPORT, "kind": "daily", "weekdays": [1, 2, 3, 4, 5]}
        _invoke(runner, client, ["update", REPORT_ID, "--weekdays", "mon,wed"])
        assert client.update_report.call_args.kwargs == {"weekdays": [1, 3]}

    def test_clear_scope_enabled_and_name(self, runner: CliRunner, client: MagicMock) -> None:
        _invoke(
            runner, client, ["update", REPORT_ID, "--clear-scope", "--disabled", "--name", "New"]
        )
        assert client.update_report.call_args.kwargs == {
            "scope": {"type": "all", "uuids": []},
            "enabled": False,
            "name": "New",
        }

    def test_nothing_to_update_is_a_usage_error(self, runner: CliRunner, client: MagicMock) -> None:
        assert _invoke(runner, client, ["update", REPORT_ID]).exit_code == 2


class TestDeleteAndSend:
    def test_delete_follows_the_same_safety_rules_as_routes(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        assert "Dry run" in _invoke(runner, client, ["delete", REPORT_ID, "--dry-run"]).output
        client.delete_report.assert_not_called()
        assert _invoke(runner, client, ["delete", REPORT_ID], input_text="n\n").exit_code == 7
        assert _invoke(runner, client, ["delete", REPORT_ID, "--yes"]).exit_code == 0
        client.delete_report.assert_called_once_with(REPORT_ID)

    def test_send_test_dry_run_renders_the_document_and_the_recipients(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["send-test", REPORT_ID, "--dry-run"])
        assert (
            result.exit_code == 0
            and "Week in review" in result.output
            and "Ana Ruiz" in result.output
            and "nothing was sent" in result.output.lower()
        )
        assert [c.kwargs["dry_run"] for c in client.send_report_test.call_args_list] == [True]

    def test_a_real_send_previews_then_asks(self, runner: CliRunner, client: MagicMock) -> None:
        assert _invoke(runner, client, ["send-test", REPORT_ID], input_text="y\n").exit_code == 0
        assert [c.kwargs["dry_run"] for c in client.send_report_test.call_args_list] == [
            True,
            False,
        ]

    def test_declining_sends_nothing(self, runner: CliRunner, client: MagicMock) -> None:
        assert _invoke(runner, client, ["send-test", REPORT_ID], input_text="n\n").exit_code == 7
        assert [c.kwargs["dry_run"] for c in client.send_report_test.call_args_list] == [True]

    def test_yes_still_previews_and_json_emits_one_document(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["send-test", REPORT_ID, "--yes", "--json"])
        assert json.loads(result.stdout)["sent"] is True
        assert [c.kwargs["dry_run"] for c in client.send_report_test.call_args_list] == [
            True,
            False,
        ]
