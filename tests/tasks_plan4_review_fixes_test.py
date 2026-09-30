"""PLAN_004 local AI review: outbound confirmation fidelity, reports update, channel resolution, recipients."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import DailyBotClient, PaginatedResult
from dailybot_cli.commands._channels import resolve_channel
from dailybot_cli.commands._schedule import IANA_TZ, TIME_OF_DAY
from dailybot_cli.display import console, print_send_test_preview
from dailybot_cli.main import cli

ROUTE_ID: str = "00000000-0000-0000-0000-0000000000a1"
REPORT_ID: str = "00000000-0000-0000-0000-0000000000b1"
USER_ID: str = "00000000-0000-0000-0000-0000000000c1"
CHANNEL: dict[str, str] = {"external_id": "C0000000A", "name": "eng", "type": "channel"}
LONG_TEXT: str = "Dailybot Plan test message: " + "word " * 60 + "THE-END"


@pytest.fixture(autouse=True)
def wide() -> Any:
    previous: int | None = console._width
    console.width = 100
    try:
        yield
    finally:
        console._width = previous


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    mock: MagicMock = MagicMock(spec=DailyBotClient)
    mock.search_channels.return_value = PaginatedResult(results=[CHANNEL], count=1)
    mock.list_users.return_value = [{"uuid": USER_ID, "full_name": "Ana Ruiz"}]
    dry: dict[str, Any] = {"dry_run": True, "channel": CHANNEL, "text": LONG_TEXT, "sent": False}
    sent: dict[str, Any] = {"dry_run": False, "channel": CHANNEL, "text": LONG_TEXT, "sent": True}
    mock.send_route_test.side_effect = lambda _u, *, dry_run: dry if dry_run else sent
    mock.get_report.return_value = {
        "uuid": REPORT_ID,
        "kind": "daily",
        "channel": CHANNEL,
        "email_recipients": [{"uuid": USER_ID}],
    }
    mock.update_report.return_value = {"uuid": REPORT_ID}
    return mock


def _invoke(
    runner: CliRunner, client: MagicMock, args: list[str], *, input_text: str | None = None
) -> Any:
    with patch("dailybot_cli.commands.tasks_settings.require_auth", return_value=client):
        return runner.invoke(cli, ["plan", "tasks", *args], input=input_text)


class TestTheWholeMessageIsShownBeforeConfirming:
    def test_a_long_message_is_not_cut_at_the_cell_limit(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        out = _invoke(runner, client, ["routes", "send-test", ROUTE_ID, "--dry-run"])
        assert "THE-END" in " ".join(out.output.split())

    def test_a_long_narrative_is_not_cut(self, capsys: pytest.CaptureFixture[str]) -> None:
        from dailybot_cli.display import print_report_document

        print_report_document(
            {
                "header": {"title": "T"},
                "narrative": LONG_TEXT,
                "sections": [{"title": "S", "count": 1, "items": [{"title": "x"}]}],
            }
        )
        assert "THE-END" in " ".join(capsys.readouterr().out.split())

    def test_under_json_the_preview_goes_to_stderr_and_stdout_stays_one_document(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["routes", "send-test", ROUTE_ID, "--yes", "--json"])
        assert json.loads(result.stdout)["sent"] is True
        assert "THE-END" in " ".join(result.stderr.split())

    def test_under_json_without_yes_the_preview_is_shown_before_the_prompt(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(
            runner, client, ["routes", "send-test", ROUTE_ID, "--json"], input_text="n\n"
        )
        assert result.exit_code == 7
        assert "THE-END" in " ".join(result.stderr.split())

    def test_the_consent_sentence_quotes_the_channel_name_as_data(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.send_route_test.side_effect = lambda _u, *, dry_run: {
            "dry_run": dry_run,
            "sent": not dry_run,
            "text": "t",
            "channel": {"external_id": "C1", "name": "x (C9) and nobody", "type": "channel"},
        }
        out = _invoke(runner, client, ["routes", "send-test", ROUTE_ID], input_text="n\n")
        assert '"x (C9) and nobody"' in out.output

    def test_a_preview_naming_no_destination_does_not_claim_it_goes_to_you(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.send_route_test.side_effect = lambda _u, *, dry_run: {
            "dry_run": dry_run,
            "sent": not dry_run,
            "text": "t",
        }
        out = _invoke(runner, client, ["routes", "send-test", ROUTE_ID], input_text="n\n")
        assert "to you" not in out.output

    def test_a_real_send_the_api_does_not_confirm_exits_1_and_says_so(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.send_route_test.side_effect = lambda _u, *, dry_run: {
            "dry_run": dry_run,
            "sent": False,
            "channel": CHANNEL,
            "text": "t",
        }
        result = _invoke(runner, client, ["routes", "send-test", ROUTE_ID, "--yes"])
        assert result.exit_code == 1
        assert "did not confirm" in " ".join(result.output.split())


class TestReportsUpdateNeverLeavesNoDestination:
    def test_clearing_both_at_once_is_refused_locally(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(
            runner, client, ["reports", "update", REPORT_ID, "--no-channel", "--no-email-to"]
        )
        assert result.exit_code == 2
        client.update_report.assert_not_called()


class TestChannelResolution:
    def test_a_name_is_searched_server_side(self) -> None:
        client: MagicMock = MagicMock()
        client.search_channels.return_value = PaginatedResult(results=[CHANNEL], count=1)
        assert resolve_channel(client, "eng")["external_id"] == "C0000000A"
        assert client.search_channels.call_args_list[0].kwargs["search"] == "eng"

    def test_an_external_id_is_found_even_when_the_search_does_not_match_names(self) -> None:
        client: MagicMock = MagicMock()
        client.search_channels.side_effect = [
            PaginatedResult(results=[], count=0),
            PaginatedResult(results=[CHANNEL], count=1),
        ]
        assert resolve_channel(client, "C0000000A")["name"] == "eng"
        assert client.search_channels.call_count == 2

    def test_a_name_that_matches_nothing_does_not_scan_everything(self) -> None:
        client: MagicMock = MagicMock()
        client.search_channels.return_value = PaginatedResult(results=[], count=0)
        with pytest.raises(click.UsageError):
            resolve_channel(client, "no such channel")
        assert client.search_channels.call_count == 1


class TestRecipientErrors:
    def test_a_name_with_control_characters_is_neutralized_in_the_error(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_users.return_value = [
            {"uuid": USER_ID, "full_name": "Ana\x1b]0;pwned\x07 Ruiz"},
            {"uuid": "00000000-0000-0000-0000-0000000000c2", "full_name": "Ana Bo"},
        ]
        result = _invoke(
            runner,
            client,
            ["reports", "create", "--name", "x", "--kind", "daily", "--email-to", "ana"],
        )
        assert result.exit_code == 2
        assert "\x1b" not in result.output and "\x07" not in result.output


class TestSmallerFindings:
    def test_non_ascii_digits_are_not_a_time(self) -> None:
        with pytest.raises(click.BadParameter):
            TIME_OF_DAY.convert("09:٣٠", None, None)

    def test_a_blank_kind_list_is_a_usage_error(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_notifications_catalog.return_value = {"kinds": []}
        result = _invoke(
            runner, client, ["routes", "create", "--name", "x", "--channel", "eng", "--kind", ","]
        )
        assert result.exit_code == 2
        client.create_notification_route.assert_not_called()

    def test_the_zone_database_is_probed_once(self) -> None:
        from dailybot_cli.commands import _schedule

        _schedule._zone_database_present.cache_clear()
        with patch(
            "dailybot_cli.commands._schedule.available_timezones", return_value={"UTC"}
        ) as listing:
            IANA_TZ.convert("UTC", None, None)
            IANA_TZ.convert("UTC", None, None)
        assert listing.call_count == 1


class TestPullRequestReviewRound1:
    """The AI review of PR 122: dead command paths, dry-run copy, recipient lookups, channel scan."""

    def test_a_live_send_that_was_not_confirmed_is_not_called_a_dry_run(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_send_test_preview({"sent": False})
        assert "Dry run" not in capsys.readouterr().out

    def test_a_dry_run_still_says_nothing_was_sent(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_send_test_preview({"dry_run": True, "sent": False})
        assert "Dry run: nothing was sent." in capsys.readouterr().out

    def test_remediation_paths_name_commands_that_exist(self) -> None:
        from dailybot_cli.commands.tasks_settings import validate_kinds

        catalog: dict[str, Any] = {"kinds": [{"key": "task.completed", "scope": "org"}]}
        with pytest.raises(click.UsageError) as raised:
            validate_kinds(catalog, ["task.completed"], scope="personal")
        assert "`dailybot plan tasks routes`" in raised.value.message

    def test_recipients_are_looked_up_with_email_and_inactive_people(self) -> None:
        from dailybot_cli.commands.tasks_settings import _recipients

        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.list_users.return_value = [
            {"uuid": "00000000-0000-0000-0000-0000000000a1", "full_name": "Ana", "is_active": False}
        ]
        with pytest.raises(click.UsageError, match="inactive"):
            _recipients(client, ("Ana",))
        client.list_users.assert_called_once_with(include_email=True, include_inactive=True)

    def test_the_channel_id_scan_has_no_client_side_ceiling(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.search_channels.return_value = PaginatedResult(results=[], count=0)
        with pytest.raises(click.UsageError):
            resolve_channel(client, "C0123456789")
        for call in client.search_channels.call_args_list:
            assert "limit" not in call.kwargs


class TestPullRequestReviewRound3:
    def test_the_enabled_badge_is_visible_on_route_and_report_cards(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from dailybot_cli.display import print_notification_routes, print_reports

        print_notification_routes(
            PaginatedResult(
                results=[{"name": "eng", "enabled": True, "uuid": "u", "kinds": [], "scope": {}}],
                count=1,
                extra={"viewer": {"can_manage": True}},
            )
        )
        print_reports(
            PaginatedResult(
                results=[{"name": "digest", "enabled": False, "uuid": "u", "kind": "k"}], count=1
            )
        )
        out: str = " ".join(capsys.readouterr().out.split())
        assert "[on]" in out and "[off]" in out

    def test_a_window_with_only_milestones_is_not_called_empty(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from dailybot_cli.display import print_timeline

        print_timeline(
            {"bands": [], "rows": [], "milestones": [{"name": "Beta", "uuid": "m"}], "projects": []}
        )
        out: str = capsys.readouterr().out
        assert "Nothing dated" not in out and "Beta" in out

    def test_a_channel_name_with_markup_is_escaped_once(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from dailybot_cli.display import print_my_notifications

        print_my_notifications(
            {
                "items": [],
                "destination": {
                    "type": "channel",
                    "channel": {"external_id": "C1", "name": "[bold]eng", "type": "channel"},
                },
            }
        )
        out: str = capsys.readouterr().out
        assert "[bold]eng" in out and "\\" not in out

    def test_a_numeric_platform_id_round_trips_through_the_scan(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        row: dict[str, str] = {
            "external_id": "123456789012345678",
            "name": "eng",
            "type": "channel",
        }
        client.search_channels.side_effect = [
            PaginatedResult(results=[], count=0),
            PaginatedResult(results=[row], count=1),
        ]
        assert resolve_channel(client, "123456789012345678")["external_id"] == "123456789012345678"


class TestPullRequestReviewRound4:
    def test_a_sort_name_is_case_insensitive(self) -> None:
        from dailybot_cli.commands._sorting import normalize_sort

        assert normalize_sort("Priority") == "priority"
        assert normalize_sort("-DUE_DATE") == "-due_date"

    def test_report_recipients_show_the_inactive_marker(self) -> None:
        from dailybot_cli.display import _people_text

        text: str = _people_text(
            [{"name": "Ana", "is_active": False}, {"name": "Bo", "is_active": True}]
        )
        assert '"Ana" (inactive)' in text and '"Bo" (inactive)' not in text

    def test_a_hostile_channel_id_is_neutralized_in_the_error(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.search_channels.return_value = PaginatedResult(
            results=[
                {"external_id": "C1\x1b[31mX", "name": "eng", "type": "channel"},
                {"external_id": "C2", "name": "eng", "type": "channel"},
            ],
            count=2,
        )
        with pytest.raises(click.UsageError) as raised:
            resolve_channel(client, "eng")
        assert "\x1b" not in raised.value.message

    def test_the_readme_has_no_bare_top_level_command_fragments(self) -> None:
        import pathlib
        import re

        readme: str = (pathlib.Path(__file__).resolve().parent.parent / "README.md").read_text(
            encoding="utf-8"
        )
        bare: re.Pattern[str] = re.compile(r"· `(task|tasks|board|project|goal) ")
        assert not bare.findall(readme)
