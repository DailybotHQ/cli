"""Timeline milestones and projects, and the project/milestone filters (PLAN_004)."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import DailyBotClient, PaginatedResult
from dailybot_cli.display import console
from dailybot_cli.main import cli

PROJECT_A: str = "00000000-0000-0000-0000-0000000000a1"
PROJECT_B: str = "00000000-0000-0000-0000-0000000000a2"
MILESTONE: str = "00000000-0000-0000-0000-0000000000f1"
LEAD: dict[str, Any] = {"uuid": "00000000-0000-0000-0000-0000000000c1", "name": "Ana Ruiz"}

DOC: dict[str, Any] = {
    "window": {"from": "2026-10-01", "to": "2026-12-31"},
    "bands": [],
    "rows": [
        {
            "uuid": "t1",
            "key": "ENG-3",
            "title": "Draft the pricing page",
            "state": "In progress",
            "start_date": "2026-10-01",
            "due_date": "2026-10-09",
            "is_blocked": False,
            "is_overdue": False,
            "project": {"uuid": PROJECT_A, "name": "Platform"},
            "board": {"uuid": "b1", "key": "ENG"},
        }
    ],
    "dependencies": [],
    "unscheduled": 0,
    "truncated": False,
    "milestones": [
        {
            "uuid": MILESTONE,
            "name": "Public beta",
            "date": "2026-10-04",
            "completed_at": None,
            "is_completed": False,
            "is_overdue": True,
            "project": {"uuid": PROJECT_A, "name": "Platform"},
            "task_count": 4,
            "done_count": 1,
        },
        {
            "uuid": "m2",
            "name": "GA",
            "date": "2026-12-15",
            "completed_at": "2026-12-14T10:00:00Z",
            "is_completed": True,
            "is_overdue": False,
            "project": {"uuid": PROJECT_A, "name": "Platform"},
            "task_count": 10,
            "done_count": 10,
        },
    ],
    "projects": [
        {
            "uuid": PROJECT_A,
            "name": "Platform",
            "start_date": "2026-09-20",
            "target_date": "2026-10-20",
            "health": "at_risk",
            "lead": LEAD,
            "progress": {"done": 1, "total": 4},
        },
        {
            "uuid": PROJECT_B,
            "name": "Web",
            "start_date": "2026-10-01",
            "target_date": "2026-12-01",
            "health": "on_track",
            "lead": None,
            "progress": {"done": 0, "total": 0},
        },
    ],
    "milestones_truncated": False,
    "projects_truncated": False,
}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    mock: MagicMock = MagicMock(spec=DailyBotClient)
    mock.get_tasks_timeline.return_value = DOC
    mock.list_tasks.return_value = PaginatedResult(results=[], count=0)
    return mock


@pytest.fixture(autouse=True)
def eighty_columns() -> Any:
    previous: int | None = console._width
    console.width = 80
    try:
        yield
    finally:
        console._width = previous


def _timeline(runner: CliRunner, client: MagicMock, *args: str) -> Any:
    with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
        return runner.invoke(cli, ["tasks", "timeline", *args])


def _flat(result: Any) -> str:
    return " ".join(result.output.split())


class TestRendering:
    def test_milestones_show_date_name_project_progress_and_flags(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        flat = _flat(_timeline(runner, client))
        for text in (
            "Milestones",
            "2026-10-04",
            "Public beta",
            "Platform",
            "1/4",
            "overdue",
            "GA",
            "10/10",
            "done",
        ):
            assert text in flat

    def test_projects_show_lead_health_target_and_progress(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        flat = _flat(_timeline(runner, client))
        for text in (
            "Projects",
            "Platform",
            "Ana Ruiz",
            "at_risk",
            "2026-10-20",
            "on_track",
            "Web",
        ):
            assert text in flat

    def test_a_project_without_a_lead_or_work_does_not_crash(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _timeline(runner, client)
        assert result.exit_code == 0 and result.exception is None

    def test_truncation_of_each_section_says_to_narrow_the_window(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_tasks_timeline.return_value = {**DOC, "milestones_truncated": True}
        assert (
            "milestone" in _flat(_timeline(runner, client)).lower()
            and "narrow" in _flat(_timeline(runner, client)).lower()
        )
        client.get_tasks_timeline.return_value = {**DOC, "projects_truncated": True}
        flat = _flat(_timeline(runner, client)).lower()
        assert "project" in flat and "narrow" in flat

    def test_an_older_server_without_the_new_keys_still_renders(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        old = {
            k: v
            for k, v in DOC.items()
            if k not in ("milestones", "projects", "milestones_truncated", "projects_truncated")
        }
        client.get_tasks_timeline.return_value = old
        result = _timeline(runner, client)
        assert result.exit_code == 0 and "Draft the" in _flat(result)

    def test_names_are_data_not_markup(self, runner: CliRunner, client: MagicMock) -> None:
        hostile = {
            **DOC,
            "milestones": [
                {**DOC["milestones"][0], "name": "[/dim][bold red]x", "project": {"name": "[/]"}}
            ],
            "projects": [{**DOC["projects"][0], "name": "[/dim][red]p", "lead": {"name": "[/]"}}],
        }
        client.get_tasks_timeline.return_value = hostile
        result = _timeline(runner, client)
        assert result.exit_code == 0 and result.exception is None

    def test_json_is_the_document_untouched(self, runner: CliRunner, client: MagicMock) -> None:
        assert json.loads(_timeline(runner, client, "--json").output) == DOC

    def test_the_help_points_milestones_at_the_timeline_now(self, runner: CliRunner) -> None:
        flat = " ".join(runner.invoke(cli, ["tasks", "timeline", "--help"]).output.split())
        assert "--project" in flat and "--milestone" in flat
        assert "not part of this view" not in flat


class TestFilters:
    def test_repeatable_project_and_milestone_reach_the_client(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        _timeline(
            runner, client, "--project", PROJECT_A, "--project", PROJECT_B, "--milestone", MILESTONE
        )
        kwargs: dict[str, Any] = client.get_tasks_timeline.call_args.kwargs
        assert kwargs["projects"] == [PROJECT_A, PROJECT_B] and kwargs["milestones"] == [MILESTONE]

    def test_no_filters_sends_none(self, runner: CliRunner, client: MagicMock) -> None:
        _timeline(runner, client)
        kwargs: dict[str, Any] = client.get_tasks_timeline.call_args.kwargs
        assert not kwargs.get("projects") and not kwargs.get("milestones")

    @pytest.mark.parametrize("flag", ["--project", "--milestone"])
    def test_a_bad_uuid_is_refused_locally(
        self, runner: CliRunner, client: MagicMock, flag: str
    ) -> None:
        assert _timeline(runner, client, flag, "nope").exit_code == 2
        client.get_tasks_timeline.assert_not_called()

    def test_task_list_takes_a_repeatable_milestone_filter(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(
                cli,
                [
                    "task",
                    "list",
                    "--milestone",
                    MILESTONE,
                    "--milestone",
                    "00000000-0000-0000-0000-0000000000f2",
                ],
            )
        assert result.exit_code == 0, result.output
        assert client.list_tasks.call_args.kwargs["filters"]["milestone"] == [
            MILESTONE,
            "00000000-0000-0000-0000-0000000000f2",
        ]

    def test_task_list_refuses_a_bad_milestone_locally(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            assert runner.invoke(cli, ["task", "list", "--milestone", "x"]).exit_code == 2
        client.list_tasks.assert_not_called()
