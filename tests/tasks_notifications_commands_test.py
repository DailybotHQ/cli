"""`dailybot tasks notifications catalog|get|set` (PLAN_004)."""

import json
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient, PaginatedResult
from dailybot_cli.main import cli

CATALOG: dict[str, Any] = {
    "groups": [
        {"key": "assignments", "title": "Assignments and mentions"},
        {"key": "tasks", "title": "Tasks"},
    ],
    "kinds": [
        {
            "key": "tasks_assigned",
            "scope": "personal",
            "group": "assignments",
            "title": "Assigned to me",
            "supports": ["chat", "email"],
            "default": {"chat": True, "email": False},
            "immediate": True,
        },
        {
            "key": "tasks_commented",
            "scope": "personal",
            "group": "assignments",
            "title": "Comments",
            "supports": ["chat", "email"],
            "default": {"chat": True, "email": False},
            "immediate": False,
        },
        {
            "key": "task.completed",
            "scope": "org",
            "group": "tasks",
            "title": "Card completed",
            "supports": ["chat"],
            "default": {"chat": False, "email": False},
            "immediate": False,
        },
    ],
}
ME: dict[str, Any] = {
    "items": [
        {
            "kind": "tasks_assigned",
            "title": "Assigned to me",
            "supports": ["chat", "email"],
            "default": {"chat": True, "email": False},
            "stored": False,
            "chat": True,
            "email": False,
        }
    ],
    "destination": {"type": "dm", "channel": None},
    "paused_until": None,
}
CHANNELS: list[dict[str, str]] = [
    {"external_id": "C0000000A", "name": "eng", "type": "channel"},
    {"external_id": "C0000000B", "name": "design", "type": "channel"},
]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    mock: MagicMock = MagicMock(spec=DailyBotClient)
    mock.get_notifications_catalog.return_value = CATALOG
    mock.get_my_notifications.return_value = ME
    mock.put_my_notifications.return_value = ME
    mock.search_channels.return_value = PaginatedResult(results=CHANNELS, count=2)
    return mock


def _invoke(runner: CliRunner, client: MagicMock, args: list[str]) -> Any:
    with patch("dailybot_cli.commands.tasks_settings.require_auth", return_value=client):
        return runner.invoke(cli, ["tasks", "notifications", *args])


class TestWiring:
    def test_the_group_is_listed_under_tasks_with_the_beta_notice(self, runner: CliRunner) -> None:
        assert "notifications" in runner.invoke(cli, ["tasks", "--help"]).output
        assert "Beta" in runner.invoke(cli, ["tasks", "notifications", "--help"]).output

    @pytest.mark.parametrize("sub", ["catalog", "get", "set"])
    def test_each_subcommand_renders_its_help(self, runner: CliRunner, sub: str) -> None:
        result = runner.invoke(cli, ["tasks", "notifications", sub, "--help"])
        assert result.exit_code == 0
        assert "Examples" in result.output


class TestCatalogAndGet:
    def test_catalog_renders(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["catalog"])
        assert result.exit_code == 0, result.output
        assert "tasks_assigned" in result.output and "task.completed" in result.output

    def test_catalog_json_is_passed_through(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["catalog", "--json"])
        assert json.loads(result.output) == CATALOG

    def test_get_renders_and_accepts_the_me_flag(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        for args in (["get"], ["get", "--me"]):
            result = _invoke(runner, client, args)
            assert result.exit_code == 0, result.output
            assert "tasks_assigned" in result.output

    def test_get_json_is_passed_through(self, runner: CliRunner, client: MagicMock) -> None:
        assert json.loads(_invoke(runner, client, ["get", "--json"]).output) == ME


class TestSet:
    def test_repeated_and_comma_kinds_get_the_flags(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(
            runner,
            client,
            [
                "set",
                "--me",
                "--kind",
                "tasks_assigned,tasks_commented",
                "--kind",
                "tasks_assigned",
                "--chat",
                "--no-email",
            ],
        )
        assert result.exit_code == 0, result.output
        client.put_my_notifications.assert_called_once()
        kwargs: dict[str, Any] = client.put_my_notifications.call_args.kwargs
        assert kwargs["items"] == [
            {"kind": "tasks_assigned", "chat": True, "email": False},
            {"kind": "tasks_commented", "chat": True, "email": False},
        ]
        assert kwargs.get("destination") is None

    def test_only_the_passed_flag_is_sent(self, runner: CliRunner, client: MagicMock) -> None:
        _invoke(runner, client, ["set", "--kind", "tasks_assigned", "--email"])
        assert client.put_my_notifications.call_args.kwargs["items"] == [
            {"kind": "tasks_assigned", "email": True}
        ]

    def test_the_catalog_is_read_once_per_run(self, runner: CliRunner, client: MagicMock) -> None:
        _invoke(runner, client, ["set", "--kind", "tasks_assigned,tasks_commented", "--chat"])
        assert client.get_notifications_catalog.call_count == 1

    def test_an_unknown_kind_is_refused_locally_listing_the_valid_ones(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["set", "--kind", "nope", "--chat"])
        assert result.exit_code == 2
        assert "tasks_assigned" in result.output and "tasks_commented" in result.output
        client.put_my_notifications.assert_not_called()

    def test_an_org_kind_points_to_routes(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["set", "--kind", "task.completed", "--chat"])
        assert result.exit_code == 2
        assert "routes" in result.output
        client.put_my_notifications.assert_not_called()

    def test_kinds_without_a_channel_flag_are_a_usage_error(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["set", "--kind", "tasks_assigned"])
        assert result.exit_code == 2
        client.put_my_notifications.assert_not_called()

    def test_a_channel_flag_without_kinds_is_a_usage_error(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        assert _invoke(runner, client, ["set", "--chat"]).exit_code == 2
        client.put_my_notifications.assert_not_called()

    def test_nothing_to_change_is_a_usage_error(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["set"])
        assert result.exit_code == 2
        client.put_my_notifications.assert_not_called()

    def test_dm_destination(self, runner: CliRunner, client: MagicMock) -> None:
        _invoke(runner, client, ["set", "--dm"])
        assert client.put_my_notifications.call_args.kwargs == {
            "items": None,
            "destination": {"type": "dm"},
        }

    def test_a_channel_by_name_resolves_to_its_external_id(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        _invoke(runner, client, ["set", "--channel", "Eng"])
        assert client.search_channels.call_args.kwargs["channel_type"] == "channel"
        assert client.put_my_notifications.call_args.kwargs["destination"] == {
            "type": "channel",
            "channel": {"external_id": "C0000000A"},
        }

    def test_an_unknown_channel_is_refused_locally(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["set", "--channel", "nowhere"])
        assert result.exit_code == 2
        assert "tasks channels search" in result.output
        client.put_my_notifications.assert_not_called()

    def test_dm_and_channel_together_are_a_usage_error(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        assert _invoke(runner, client, ["set", "--dm", "--channel", "eng"]).exit_code == 2

    def test_kinds_and_destination_can_be_set_together(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        _invoke(runner, client, ["set", "--kind", "tasks_assigned", "--chat", "--dm"])
        kwargs: dict[str, Any] = client.put_my_notifications.call_args.kwargs
        assert kwargs["items"] and kwargs["destination"] == {"type": "dm"}

    def test_json_passes_the_answer_through_and_human_mode_confirms(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        assert (
            json.loads(
                _invoke(
                    runner, client, ["set", "--kind", "tasks_assigned", "--chat", "--json"]
                ).output
            )
            == ME
        )
        human = _invoke(runner, client, ["set", "--kind", "tasks_assigned", "--chat"])
        assert "Updated" in human.output and "tasks_assigned" in human.output


class TestRefusals:
    ACTOR: ClassVar[APIError] = APIError(400, "no person", code="actor_required")

    def test_an_agent_or_org_key_is_told_to_log_in_or_use_a_personal_key(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_my_notifications.side_effect = self.ACTOR
        result = _invoke(runner, client, ["get"])
        assert result.exit_code == 3
        assert "personal" in result.output.lower()

    def test_a_server_refusal_keeps_its_code_and_extra_under_json(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.put_my_notifications.side_effect = APIError(
            400, "bad", code="channel_not_found", extra={"parameter": "channel"}
        )
        result = _invoke(runner, client, ["set", "--dm", "--json"])
        assert result.exit_code == 2
        envelope: dict[str, Any] = json.loads(result.stdout)
        assert envelope["code"] == "channel_not_found" and envelope["extra"] == {
            "parameter": "channel"
        }

    def test_a_transport_error_is_exit_8(self, runner: CliRunner, client: MagicMock) -> None:
        from dailybot_cli.api_client import TransportError

        client.get_notifications_catalog.side_effect = TransportError("could not reach")
        assert _invoke(runner, client, ["catalog"]).exit_code == 8
