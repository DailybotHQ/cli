"""`dailybot plan tasks routes list|get|create|update|delete|send-test|deliveries` (PLAN_004)."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient, PaginatedResult
from dailybot_cli.display import console
from dailybot_cli.main import cli

ROUTE_ID: str = "00000000-0000-0000-0000-0000000000a1"
BOARD_ID: str = "00000000-0000-0000-0000-0000000000d1"
PROJECT_ID: str = "00000000-0000-0000-0000-0000000000e1"
CHANNEL: dict[str, str] = {"external_id": "C0000000A", "name": "eng", "type": "channel"}
ROUTE: dict[str, Any] = {
    "uuid": ROUTE_ID,
    "name": "Completions",
    "enabled": True,
    "channel": CHANNEL,
    "kinds": ["task.completed", "project.health_changed"],
    "scope": {"type": "all", "uuids": []},
}
CATALOG: dict[str, Any] = {
    "groups": [],
    "kinds": [
        {"key": "task.completed", "scope": "org"},
        {"key": "project.health_changed", "scope": "org"},
        {"key": "task.created", "scope": "org"},
        {"key": "tasks_assigned", "scope": "personal"},
    ],
}
DRY_RUN: dict[str, Any] = {
    "dry_run": True,
    "channel": CHANNEL,
    "sent": False,
    "text": "Dailybot Plan test message for this channel route.",
}
SENT: dict[str, Any] = {
    "dry_run": False,
    "channel": CHANNEL,
    "sent": True,
    "text": "Dailybot Plan test message",
}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    mock: MagicMock = MagicMock(spec=DailyBotClient)
    mock.get_notifications_catalog.return_value = CATALOG
    mock.search_channels.return_value = PaginatedResult(results=[CHANNEL], count=1)
    mock.list_notification_routes.return_value = PaginatedResult(
        results=[ROUTE], count=1, extra={"viewer": {"can_manage": True}}
    )
    mock.get_notification_route.return_value = ROUTE
    mock.create_notification_route.return_value = {
        **ROUTE,
        "_idempotency_key": "key-1",
        "_idempotency_replayed": False,
    }
    mock.update_notification_route.return_value = ROUTE
    mock.delete_notification_route.return_value = {}
    mock.send_route_test.side_effect = lambda _uuid, *, dry_run: DRY_RUN if dry_run else SENT
    mock.list_route_deliveries.return_value = PaginatedResult(
        results=[
            {
                "uuid": "d1",
                "kind": "task.completed",
                "status": "sent",
                "error": None,
                "created_at": "2026-09-30T10:00:00Z",
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
        return runner.invoke(cli, ["plan", "tasks", "routes", *args], input=input_text)


class TestWiring:
    def test_group_and_help(self, runner: CliRunner) -> None:
        assert "routes" in runner.invoke(cli, ["plan", "tasks", "--help"]).output
        for sub in ("list", "get", "create", "update", "delete", "send-test", "deliveries"):
            result = runner.invoke(cli, ["plan", "tasks", "routes", sub, "--help"])
            assert result.exit_code == 0 and "Examples" in result.output, sub


class TestReads:
    def test_list_shows_cards_and_passes_the_viewer_through_in_json(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        out = _invoke(runner, client, ["list"])
        assert out.exit_code == 0 and ROUTE_ID in out.output and "task.completed" in out.output
        body: dict[str, Any] = json.loads(_invoke(runner, client, ["list", "--json"]).output)
        assert body["viewer"] == {"can_manage": True} and body["results"][0]["uuid"] == ROUTE_ID

    def test_get(self, runner: CliRunner, client: MagicMock) -> None:
        assert ROUTE_ID in _invoke(runner, client, ["get", ROUTE_ID]).output
        assert (
            json.loads(_invoke(runner, client, ["get", ROUTE_ID, "--json"]).output)["uuid"]
            == ROUTE_ID
        )

    def test_a_route_reference_that_is_not_a_uuid_is_refused_locally(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        assert _invoke(runner, client, ["get", "Completions"]).exit_code == 2
        client.get_notification_route.assert_not_called()

    def test_deliveries(self, runner: CliRunner, client: MagicMock) -> None:
        out = _invoke(runner, client, ["deliveries", ROUTE_ID])
        assert out.exit_code == 0 and "sent" in out.output
        client.list_route_deliveries.assert_called_once()


class TestCreate:
    def test_sends_name_resolved_channel_and_validated_kinds_with_the_key_printed(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(
            runner,
            client,
            [
                "create",
                "--name",
                "Completions",
                "--channel",
                "eng",
                "--kind",
                "task.completed,project.health_changed",
            ],
        )
        assert result.exit_code == 0, result.output
        kwargs: dict[str, Any] = client.create_notification_route.call_args.kwargs
        assert kwargs["name"] == "Completions"
        assert kwargs["channel"] == {"external_id": "C0000000A"}
        assert kwargs["kinds"] == ["task.completed", "project.health_changed"]
        assert kwargs.get("scope") is None and kwargs.get("enabled") is None
        assert "key-1" in result.output

    def test_a_personal_or_unknown_kind_is_refused_locally(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        for kind in ("tasks_assigned", "nope"):
            result = _invoke(
                runner, client, ["create", "--name", "x", "--channel", "eng", "--kind", kind]
            )
            assert result.exit_code == 2
        assert "org" in result.output or "Valid" in result.output
        client.create_notification_route.assert_not_called()

    def test_name_channel_and_kind_are_required(self, runner: CliRunner, client: MagicMock) -> None:
        for args in (
            ["create", "--channel", "eng", "--kind", "task.created"],
            ["create", "--name", "x", "--kind", "task.created"],
            ["create", "--name", "x", "--channel", "eng"],
        ):
            assert _invoke(runner, client, args).exit_code == 2
        client.create_notification_route.assert_not_called()

    def test_scope_boards_and_projects_build_the_scope_object(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        _invoke(
            runner,
            client,
            [
                "create",
                "--name",
                "x",
                "--channel",
                "eng",
                "--kind",
                "task.created",
                "--board",
                BOARD_ID,
            ],
        )
        assert client.create_notification_route.call_args.kwargs["scope"] == {
            "type": "boards",
            "uuids": [BOARD_ID],
        }
        _invoke(
            runner,
            client,
            [
                "create",
                "--name",
                "x",
                "--channel",
                "eng",
                "--kind",
                "task.created",
                "--project",
                PROJECT_ID,
            ],
        )
        assert client.create_notification_route.call_args.kwargs["scope"] == {
            "type": "projects",
            "uuids": [PROJECT_ID],
        }

    def test_boards_and_projects_together_are_a_usage_error(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(
            runner,
            client,
            [
                "create",
                "--name",
                "x",
                "--channel",
                "eng",
                "--kind",
                "task.created",
                "--board",
                BOARD_ID,
                "--project",
                PROJECT_ID,
            ],
        )
        assert result.exit_code == 2

    def test_a_bad_scope_uuid_is_refused_locally(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        assert (
            _invoke(
                runner,
                client,
                [
                    "create",
                    "--name",
                    "x",
                    "--channel",
                    "eng",
                    "--kind",
                    "task.created",
                    "--board",
                    "not-a-uuid",
                ],
            ).exit_code
            == 2
        )

    def test_disabled_and_a_given_key(self, runner: CliRunner, client: MagicMock) -> None:
        _invoke(
            runner,
            client,
            [
                "create",
                "--name",
                "x",
                "--channel",
                "eng",
                "--kind",
                "task.created",
                "--disabled",
                "--idempotency-key",
                "mine",
            ],
        )
        kwargs: dict[str, Any] = client.create_notification_route.call_args.kwargs
        assert kwargs["enabled"] is False and kwargs["idempotency_key"] == "mine"

    def test_an_unknown_channel_is_refused_locally_with_a_hint(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(
            runner,
            client,
            ["create", "--name", "x", "--channel", "nowhere", "--kind", "task.created"],
        )
        assert result.exit_code == 2 and "tasks channels search" in result.output
        client.create_notification_route.assert_not_called()

    def test_server_refusals_render_with_their_extra(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.create_notification_route.side_effect = APIError(
            400, "x", code="notification_routes_limit_reached", extra={"limit": 10}
        )
        result = _invoke(
            runner, client, ["create", "--name", "x", "--channel", "eng", "--kind", "task.created"]
        )
        assert result.exit_code == 2 and "10" in result.output
        client.create_notification_route.side_effect = APIError(
            403, "x", code="insufficient_scope", extra={"required_scope": "tasks:admin"}
        )
        assert (
            _invoke(
                runner,
                client,
                ["create", "--name", "x", "--channel", "eng", "--kind", "task.created"],
            ).exit_code
            == 4
        )

    def test_json_passes_the_route_through(self, runner: CliRunner, client: MagicMock) -> None:
        body = json.loads(
            _invoke(
                runner,
                client,
                ["create", "--name", "x", "--channel", "eng", "--kind", "task.created", "--json"],
            ).output
        )
        assert body["uuid"] == ROUTE_ID and body["_idempotency_key"] == "key-1"


class TestUpdate:
    def test_only_passed_fields_are_sent(self, runner: CliRunner, client: MagicMock) -> None:
        _invoke(runner, client, ["update", ROUTE_ID, "--name", "Renamed"])
        assert client.update_notification_route.call_args.kwargs == {"name": "Renamed"}

    def test_kinds_replace_and_enabled_toggles(self, runner: CliRunner, client: MagicMock) -> None:
        _invoke(runner, client, ["update", ROUTE_ID, "--kind", "task.created", "--disabled"])
        assert client.update_notification_route.call_args.kwargs == {
            "kinds": ["task.created"],
            "enabled": False,
        }

    def test_channel_is_resolved(self, runner: CliRunner, client: MagicMock) -> None:
        _invoke(runner, client, ["update", ROUTE_ID, "--channel", "eng"])
        assert client.update_notification_route.call_args.kwargs == {
            "channel": {"external_id": "C0000000A"}
        }

    def test_clear_scope_resets_to_all(self, runner: CliRunner, client: MagicMock) -> None:
        _invoke(runner, client, ["update", ROUTE_ID, "--clear-scope"])
        assert client.update_notification_route.call_args.kwargs == {
            "scope": {"type": "all", "uuids": []}
        }

    def test_clear_scope_with_a_scope_flag_is_a_usage_error(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        assert (
            _invoke(
                runner, client, ["update", ROUTE_ID, "--clear-scope", "--board", BOARD_ID]
            ).exit_code
            == 2
        )

    def test_nothing_to_update_is_a_usage_error(self, runner: CliRunner, client: MagicMock) -> None:
        assert _invoke(runner, client, ["update", ROUTE_ID]).exit_code == 2
        client.update_notification_route.assert_not_called()


class TestDelete:
    def test_dry_run_sends_nothing(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["delete", ROUTE_ID, "--dry-run"])
        assert result.exit_code == 0 and "Dry run" in result.output
        client.delete_notification_route.assert_not_called()

    def test_without_yes_a_decline_aborts_with_exit_7(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["delete", ROUTE_ID], input_text="n\n")
        assert result.exit_code == 7
        client.delete_notification_route.assert_not_called()

    def test_yes_deletes(self, runner: CliRunner, client: MagicMock) -> None:
        assert _invoke(runner, client, ["delete", ROUTE_ID, "--yes"]).exit_code == 0
        client.delete_notification_route.assert_called_once_with(ROUTE_ID)


class TestSendTest:
    def test_dry_run_shows_the_preview_and_never_sends(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["send-test", ROUTE_ID, "--dry-run"])
        assert (
            result.exit_code == 0
            and "eng" in result.output
            and "nothing was sent" in result.output.lower()
        )
        assert [c.kwargs["dry_run"] for c in client.send_route_test.call_args_list] == [True]

    def test_a_real_send_previews_first_then_asks(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["send-test", ROUTE_ID], input_text="y\n")
        assert result.exit_code == 0, result.output
        assert [c.kwargs["dry_run"] for c in client.send_route_test.call_args_list] == [True, False]
        assert "eng" in result.output and "Sent" in result.output

    def test_declining_sends_nothing_and_exits_7(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["send-test", ROUTE_ID], input_text="n\n")
        assert result.exit_code == 7
        assert [c.kwargs["dry_run"] for c in client.send_route_test.call_args_list] == [True]

    def test_yes_still_previews_first(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["send-test", ROUTE_ID, "--yes"])
        assert result.exit_code == 0
        assert [c.kwargs["dry_run"] for c in client.send_route_test.call_args_list] == [True, False]

    def test_json_dry_run_is_the_preview_document(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        body = json.loads(
            _invoke(runner, client, ["send-test", ROUTE_ID, "--dry-run", "--json"]).output
        )
        assert body["dry_run"] is True and body["sent"] is False

    def test_json_real_send_emits_one_document(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["send-test", ROUTE_ID, "--yes", "--json"])
        assert json.loads(result.stdout)["sent"] is True

    def test_a_preview_that_fails_aborts_before_any_send(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.send_route_test.side_effect = APIError(400, "x", code="platform_not_connected")
        result = _invoke(runner, client, ["send-test", ROUTE_ID, "--yes"])
        assert result.exit_code == 2 and "chat platform" in result.output
        assert [c.kwargs["dry_run"] for c in client.send_route_test.call_args_list] == [True]

    def test_a_server_that_does_not_honour_dry_run_stops_everything(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.send_route_test.side_effect = lambda _u, *, dry_run: SENT
        result = _invoke(runner, client, ["send-test", ROUTE_ID, "--yes"])
        assert result.exit_code == 1
        assert client.send_route_test.call_count == 1
