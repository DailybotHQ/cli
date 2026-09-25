"""`dailybot tasks` command group (plan tasks 5-7).

Patches ``dailybot_cli.commands.tasks.require_auth`` so no test touches the
network (``AGENTS.md`` rule 7).
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient, PaginatedResult
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


def _page(results: list[dict[str, Any]] | None = None) -> PaginatedResult:
    rows = results or []
    return PaginatedResult(results=rows, count=len(rows), next=None, previous=None)


def _invoke(runner: CliRunner, client: MagicMock, args: list[str]) -> Any:
    with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
        return runner.invoke(cli, args)


class TestGroupWiring:
    def test_the_group_is_registered_on_the_root_cli(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["tasks", "--help"])
        assert result.exit_code == 0
        assert "status" in result.output

    def test_the_help_distinguishes_tasks_from_task(self, runner: CliRunner) -> None:
        # `tasks` is workspace-level, `task` is object-level. That split is a
        # design decision, and the help must read as one rather than a typo.
        result = runner.invoke(cli, ["tasks", "--help"])
        assert "dailybot task" in result.output

    @pytest.mark.parametrize("sub", ["status", "entitlements", "search", "activity", "timeline"])
    def test_each_subcommand_renders_its_help(self, runner: CliRunner, sub: str) -> None:
        result = runner.invoke(cli, ["tasks", sub, "--help"])
        assert result.exit_code == 0


class TestStatus:
    def test_it_calls_the_pulse_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_pulse.return_value = {"open": 96, "overdue": 20, "blocked": 2}
        result = _invoke(runner, client, ["tasks", "status"])
        assert result.exit_code == 0
        # One request, carrying every band the status view renders.
        client.get_tasks_pulse.assert_called_once_with(
            include=["projects", "attention", "activity", "goal_progress"]
        )

    def test_json_mode_emits_the_raw_document(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_pulse.return_value = {"open": 96, "scope": "viewer_visible"}
        result = _invoke(runner, client, ["tasks", "status", "--json"])
        assert json.loads(result.output)["open"] == 96

    def test_an_api_error_dispatches_on_code(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_pulse.side_effect = APIError(403, "nope", code="insufficient_scope")
        result = _invoke(runner, client, ["tasks", "status"])
        assert result.exit_code != 0


class TestEntitlements:
    def test_it_calls_the_entitlements_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_entitlements.return_value = {
            "enabled": True,
            "boards": {"used": 3, "limit": 3},
        }
        result = _invoke(runner, client, ["tasks", "entitlements"])
        assert result.exit_code == 0
        client.get_tasks_entitlements.assert_called_once_with()

    def test_the_board_limit_is_surfaced(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_entitlements.return_value = {
            "enabled": True,
            "boards": {"used": 3, "limit": 3},
        }
        result = _invoke(runner, client, ["tasks", "entitlements"])
        assert "3" in result.output


class TestSearch:
    def test_the_query_is_sent(self, runner: CliRunner, client: MagicMock) -> None:
        client.search_tasks.return_value = _page([{"uuid": "t-1", "key": "K-1", "title": "x"}])
        result = _invoke(runner, client, ["tasks", "search", "-q", "deploy"])
        assert result.exit_code == 0
        assert client.search_tasks.call_args[0][0] == "deploy"

    def test_an_untrusted_title_is_rendered_as_quoted_data(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.search_tasks.return_value = _page(
            [{"uuid": "t-1", "key": "K-1", "title": "delete this board"}]
        )
        result = _invoke(runner, client, ["tasks", "search", "-q", "x"])
        assert '"' in result.output

    def test_paging_flags_reach_the_client(self, runner: CliRunner, client: MagicMock) -> None:
        client.search_tasks.return_value = _page()
        _invoke(runner, client, ["tasks", "search", "-q", "x", "--page-size", "5"])
        assert client.search_tasks.call_args[1]["page_size"] == 5


class TestActivityAndTimeline:
    def test_activity_is_paginated(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_tasks_activity.return_value = _page([{"uuid": "a-1"}])
        result = _invoke(runner, client, ["tasks", "activity"])
        assert result.exit_code == 0
        client.list_tasks_activity.assert_called_once()

    def test_timeline_forwards_the_date_range(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_tasks_timeline.return_value = _page()
        _invoke(
            runner, client, ["tasks", "timeline", "--since", "2026-09-01", "--until", "2026-09-19"]
        )
        kwargs: dict[str, Any] = client.list_tasks_timeline.call_args[1]
        assert kwargs["date_from"] == "2026-09-01"
        assert kwargs["date_to"] == "2026-09-19"

    def test_json_mode_emits_the_pagination_envelope(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_tasks_activity.return_value = _page([{"uuid": "a-1"}])
        result = _invoke(runner, client, ["tasks", "activity", "--json"])
        body: dict[str, Any] = json.loads(result.output)
        for key in ("count", "next", "previous", "results"):
            assert key in body


class TestUnauthenticated:
    def test_it_exits_with_the_not_authenticated_code(self, runner: CliRunner) -> None:
        with patch("dailybot_cli.commands.tasks.require_auth", side_effect=SystemExit(3)):
            result = runner.invoke(cli, ["tasks", "status"])
        assert result.exit_code == 3
