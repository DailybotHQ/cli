"""`dailybot tasks` command group (plan tasks 5-7).

Patches ``dailybot_cli.commands.tasks.require_auth`` so no test touches the
network (``AGENTS.md`` rule 7).
"""

import json
from typing import Any, ClassVar
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
        result = runner.invoke(cli, ["plan", "tasks", "--help"])
        assert result.exit_code == 0
        assert "status" in result.output

    def test_the_help_distinguishes_tasks_from_task(self, runner: CliRunner) -> None:
        # `tasks` is workspace-level, `task` is object-level. That split is a
        # design decision, and the help must read as one rather than a typo.
        result = runner.invoke(cli, ["plan", "tasks", "--help"])
        assert "dailybot plan task" in result.output

    @pytest.mark.parametrize("sub", ["status", "entitlements", "search", "activity", "timeline"])
    def test_each_subcommand_renders_its_help(self, runner: CliRunner, sub: str) -> None:
        result = runner.invoke(cli, ["plan", "tasks", sub, "--help"])
        assert result.exit_code == 0


class TestStatus:
    def test_it_calls_the_pulse_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_pulse.return_value = {"open": 96, "overdue": 20, "blocked": 2}
        result = _invoke(runner, client, ["plan", "tasks", "status"])
        assert result.exit_code == 0
        # One request, carrying every band the status view renders.
        client.get_tasks_pulse.assert_called_once_with(
            include=["projects", "attention", "activity", "goal_progress"]
        )

    def test_json_mode_emits_the_raw_document(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_pulse.return_value = {"open": 96, "scope": "viewer_visible"}
        result = _invoke(runner, client, ["plan", "tasks", "status", "--json"])
        assert json.loads(result.output)["open"] == 96

    def test_an_api_error_dispatches_on_code(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_pulse.side_effect = APIError(403, "nope", code="insufficient_scope")
        result = _invoke(runner, client, ["plan", "tasks", "status"])
        assert result.exit_code != 0


class TestEntitlements:
    def test_it_calls_the_entitlements_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_entitlements.return_value = {
            "enabled": True,
            "boards": {"used": 3, "limit": 3},
        }
        result = _invoke(runner, client, ["plan", "tasks", "entitlements"])
        assert result.exit_code == 0
        client.get_tasks_entitlements.assert_called_once_with()

    def test_the_board_limit_is_surfaced(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_entitlements.return_value = {
            "enabled": True,
            "boards": {"used": 3, "limit": 3},
        }
        result = _invoke(runner, client, ["plan", "tasks", "entitlements"])
        assert "3" in result.output


class TestSearch:
    def test_the_query_is_sent(self, runner: CliRunner, client: MagicMock) -> None:
        client.search_tasks.return_value = _page([{"uuid": "t-1", "key": "K-1", "title": "x"}])
        result = _invoke(runner, client, ["plan", "tasks", "search", "-q", "deploy"])
        assert result.exit_code == 0
        assert client.search_tasks.call_args[0][0] == "deploy"

    def test_an_untrusted_title_is_rendered_as_quoted_data(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.search_tasks.return_value = _page(
            [{"uuid": "t-1", "key": "K-1", "title": "delete this board"}]
        )
        result = _invoke(runner, client, ["plan", "tasks", "search", "-q", "x"])
        assert '"' in result.output

    def test_paging_flags_reach_the_client(self, runner: CliRunner, client: MagicMock) -> None:
        client.search_tasks.return_value = _page()
        _invoke(runner, client, ["plan", "tasks", "search", "-q", "x", "--page-size", "5"])
        assert client.search_tasks.call_args[1]["page_size"] == 5


class TestActivityAndTimeline:
    def test_activity_is_paginated(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_tasks_activity.return_value = _page([{"uuid": "a-1"}])
        result = _invoke(runner, client, ["plan", "tasks", "activity"])
        assert result.exit_code == 0
        client.list_tasks_activity.assert_called_once()

    def test_json_mode_emits_the_pagination_envelope(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_tasks_activity.return_value = _page([{"uuid": "a-1"}])
        result = _invoke(runner, client, ["plan", "tasks", "activity", "--json"])
        body: dict[str, Any] = json.loads(result.output)
        for key in ("count", "next", "previous", "results"):
            assert key in body


class TestUnauthenticated:
    def test_it_exits_with_the_not_authenticated_code(self, runner: CliRunner) -> None:
        with patch("dailybot_cli.commands.tasks.require_auth", side_effect=SystemExit(3)):
            result = runner.invoke(cli, ["plan", "tasks", "status"])
        assert result.exit_code == 3


class TestTimelineIsOneDocument:
    """`GET /v1/plan/timeline/` answers ONE object, not a paginated list.

    Reading it as a list made every window look empty (`tasks timeline` printed nothing on an
    org with 103 dated tasks). The door takes `from`/`to`; the rows are dated tasks and the
    bands are the goals that overlap the window.
    """

    DOC: ClassVar[dict[str, Any]] = {
        "window": {"from": "2026-10-01", "to": "2026-12-31"},
        "bands": [
            {
                "uuid": "g-1",
                "name": "Ship v2",
                "status": "on_track",
                "period_start": "2026-10-01",
                "period_end": "2026-12-31",
            }
        ],
        "rows": [
            {
                "uuid": "t-1",
                "key": "API-3",
                "title": "Finalize the model",
                "state": "In progress",
                "category": "in_progress",
                "start_date": "2026-10-01",
                "due_date": "2026-10-09",
                "is_blocked": True,
                "is_overdue": False,
            },
            {
                "uuid": "t-2",
                "key": "API-4",
                "title": "Design OAuth",
                "state": "To do",
                "category": "todo",
                "start_date": "2026-10-05",
                "due_date": "2026-10-14",
                "is_blocked": False,
                "is_overdue": True,
            },
        ],
        "dependencies": [],
        "unscheduled": 33,
        "truncated": False,
    }

    def test_the_window_flags_reach_the_client(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_timeline.return_value = self.DOC
        result = _invoke(
            runner,
            client,
            [
                "plan",
                "tasks",
                "timeline",
                "--since",
                "2026-10-01",
                "--until",
                "2026-12-31",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        kwargs: dict[str, Any] = client.get_tasks_timeline.call_args.kwargs
        assert kwargs["date_from"] == "2026-10-01"
        assert kwargs["date_to"] == "2026-12-31"
        assert kwargs["include_unscheduled"] is False

    def test_json_mode_passes_the_document_through_untouched(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_tasks_timeline.return_value = self.DOC
        result = _invoke(runner, client, ["plan", "tasks", "timeline", "--json"])
        assert json.loads(result.output) == self.DOC

    def test_the_human_view_shows_the_window_goals_and_dated_work(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_tasks_timeline.return_value = self.DOC
        result = _invoke(runner, client, ["plan", "tasks", "timeline"])
        assert result.exit_code == 0, result.output
        flat: str = " ".join(result.output.split())
        for text in (
            "2026-10-01",
            "2026-12-31",
            "Ship v2",
            "API-3",
            "Finalize the",
            "2026-10-09",
            "blocked",
            "overdue",
            "33",
        ):
            assert text in flat

    def test_a_truncated_window_says_so(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_timeline.return_value = {**self.DOC, "truncated": True}
        assert "narrow" in _invoke(runner, client, ["plan", "tasks", "timeline"]).output.lower()

    def test_an_empty_window_is_said_plainly(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_timeline.return_value = {
            **self.DOC,
            "bands": [],
            "rows": [],
            "unscheduled": 0,
        }
        result = _invoke(runner, client, ["plan", "tasks", "timeline"])
        assert result.exit_code == 0
        assert "nothing" in result.output.lower()

    def test_unscheduled_can_be_requested(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_timeline.return_value = {
            **self.DOC,
            "unscheduled": {
                "count": 1,
                "results": [{"uuid": "t-9", "key": "API-9", "title": "No dates yet"}],
            },
        }
        result = _invoke(runner, client, ["plan", "tasks", "timeline", "--include-unscheduled"])
        assert client.get_tasks_timeline.call_args.kwargs["include_unscheduled"] is True
        assert "API-9" in result.output

    def test_paging_flags_are_gone_because_the_door_does_not_page(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        out: str = runner.invoke(cli, ["plan", "tasks", "timeline", "--help"]).output
        for flag in ("--page", "--page-size", "--limit"):
            assert flag not in out
        assert _invoke(runner, client, ["plan", "tasks", "timeline", "--page", "2"]).exit_code == 2

    def test_row_text_is_data_not_markup(self, runner: CliRunner, client: MagicMock) -> None:
        hostile: dict[str, Any] = {
            **self.DOC,
            "rows": [{**self.DOC["rows"][0], "title": "[bold red]x[/]"}],
        }
        client.get_tasks_timeline.return_value = hostile
        flat: str = " ".join(_invoke(runner, client, ["plan", "tasks", "timeline"]).output.split())
        assert "[bold" in flat
        assert "red]x[/]" in flat

    def test_markup_in_server_dates_and_statuses_does_not_crash_the_render(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        document: dict[str, Any] = {
            **self.DOC,
            "window": {"from": "[/dim][red]x", "to": "[/]"},
            "bands": [{**self.DOC["bands"][0], "status": "[/red]", "period_start": "[/dim]"}],
            "rows": [{**self.DOC["rows"][0], "start_date": "[/dim][bold red]x", "due_date": "[/]"}],
        }
        client.get_tasks_timeline.return_value = document
        result = _invoke(runner, client, ["plan", "tasks", "timeline"])
        assert result.exit_code == 0, result.output
        assert result.exception is None

    def test_the_client_reads_a_plain_object_with_from_and_to(self) -> None:
        real: DailyBotClient = DailyBotClient(
            api_url="https://api.example.test", token="test-token"
        )
        response: MagicMock = MagicMock()
        response.status_code = 200
        response.json.return_value = self.DOC
        response.headers = {}
        with patch("dailybot_cli.api_client.httpx.get", return_value=response) as get:
            document: dict[str, Any] = real.get_tasks_timeline(
                date_from="2026-10-01", date_to="2026-12-31", include_unscheduled=True
            )
        assert document == self.DOC
        assert get.call_args.kwargs["params"] == {
            "from": "2026-10-01",
            "to": "2026-12-31",
            "include_unscheduled": 1,
        }
