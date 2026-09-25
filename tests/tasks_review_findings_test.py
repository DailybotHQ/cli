"""Regression tests for the CI AI review's findings on PR #85.

Thirteen findings, one of them critical. Each test here fails against the code as
it was reviewed. The critical one is first, and the reason it shipped is worth
stating: **the command tests mocked the very client method that was broken**, so a
`TypeError` on every real invocation stayed invisible behind a green suite.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient, PaginatedResult
from dailybot_cli.commands.public_api_helpers import (
    EXIT_NOT_AUTHENTICATED,
    EXIT_NOT_FOUND,
    EXIT_PERMISSION_DENIED,
    tasks_write_exit_code,
)
from dailybot_cli.display import TASKS_TRUSTED_FIELDS
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


@pytest.fixture
def real_client() -> DailyBotClient:
    return DailyBotClient(api_url="http://t.example.com", token="t", api_key="k")


def _ok() -> MagicMock:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = 200
    mock.json.return_value = {"count": 0, "next": None, "previous": None, "results": []}
    mock.headers = {}
    return mock


def _page(rows: list[dict[str, Any]] | None = None) -> PaginatedResult:
    items = rows or []
    return PaginatedResult(results=items, count=len(items), next=None, previous=None)


class TestCriticalListMyTasksReachesTheApi:
    """Finding 1 (critical): every `tasks mine` invocation raised TypeError.

    `list_my_tasks` declared `filters=` *and* `**page`, then called
    `_tasks_list(..., params=filters, **page)`. A caller passing `params=` — which
    every other list door accepts — landed it in `**page` and collided.
    """

    def test_it_accepts_params_like_every_other_list_door(
        self, real_client: DailyBotClient
    ) -> None:
        with patch("httpx.get", return_value=_ok()) as mock_get:
            real_client.list_my_tasks(params={"scope": "assigned"})
        assert mock_get.call_args[1]["params"]["scope"] == "assigned"

    def test_it_works_with_no_arguments(self, real_client: DailyBotClient) -> None:
        with patch("httpx.get", return_value=_ok()):
            real_client.list_my_tasks()

    def test_the_command_reaches_the_client_end_to_end(
        self, runner: CliRunner, real_client: DailyBotClient
    ) -> None:
        # The bug hid behind a MagicMock in the command tests, so this one drives
        # the REAL client with only httpx patched.
        with (
            patch("dailybot_cli.commands.tasks.require_auth", return_value=real_client),
            patch("dailybot_cli.commands.tasks.get_token", return_value="tok"),
            patch("httpx.get", return_value=_ok()),
        ):
            result = runner.invoke(cli, ["tasks", "mine", "--scope", "assigned"])
        assert result.exit_code == 0, result.output


class TestExitCodesMatchTheDocumentedTable:
    """Findings 2 and 3: every refusal collapsed to one code, and --json was ignored."""

    @pytest.mark.parametrize(
        "status,expected",
        [
            (401, EXIT_NOT_AUTHENTICATED),
            (402, EXIT_PERMISSION_DENIED),
            (403, EXIT_PERMISSION_DENIED),
            (404, EXIT_NOT_FOUND),
            (409, EXIT_PERMISSION_DENIED),
            (500, 1),
        ],
    )
    def test_status_maps_to_the_documented_exit(self, status: int, expected: int) -> None:
        assert tasks_write_exit_code(APIError(status, "x", code="c")) == expected

    def test_a_server_error_on_inbox_is_not_reported_as_a_login_problem(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # A 500 exiting 3 sends an agent down the login recovery path for a blip.
        client.list_tasks_inbox.side_effect = APIError(500, "boom", code="server_error")
        with (
            patch("dailybot_cli.commands.tasks.require_auth", return_value=client),
            patch("dailybot_cli.commands.tasks.get_token", return_value="tok"),
        ):
            result = runner.invoke(cli, ["tasks", "inbox"])
        assert result.exit_code != EXIT_NOT_AUTHENTICATED

    def test_a_person_shaped_refusal_still_exits_three(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_tasks_inbox.side_effect = APIError(403, "x", code="insufficient_scope")
        with (
            patch("dailybot_cli.commands.tasks.require_auth", return_value=client),
            patch("dailybot_cli.commands.tasks.get_token", return_value="tok"),
        ):
            result = runner.invoke(cli, ["tasks", "inbox"])
        assert result.exit_code == EXIT_NOT_AUTHENTICATED

    def test_json_mode_emits_a_payload_on_a_refusal(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        import json as _json

        client.list_tasks_inbox.side_effect = APIError(403, "nope", code="insufficient_scope")
        with (
            patch("dailybot_cli.commands.tasks.require_auth", return_value=client),
            patch("dailybot_cli.commands.tasks.get_token", return_value="tok"),
        ):
            result = runner.invoke(cli, ["tasks", "inbox", "--json"])
        body: dict[str, Any] = _json.loads(result.output)
        assert body["code"] == "insufficient_scope"

    def test_a_write_404_is_distinguishable_from_a_generic_failure(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.update_task.side_effect = APIError(404, "gone", code="not_found")
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(cli, ["task", "update", "t-1", "--title", "x"])
        assert result.exit_code == EXIT_NOT_FOUND


class TestAdvertisedFlagsAreHonoured:
    """Findings 4-9: flags shown in --help that were silently discarded."""

    def test_project_list_forwards_search(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_projects.return_value = _page()
        with patch("dailybot_cli.commands.project.require_auth", return_value=client):
            runner.invoke(cli, ["project", "list", "--search", "Apollo"])
        assert client.list_projects.call_args[1]["params"]["search"] == "Apollo"

    def test_goal_list_forwards_date_flags(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_goals.return_value = _page()
        with patch("dailybot_cli.commands.goal.require_auth", return_value=client):
            runner.invoke(cli, ["goal", "list", "--since", "2026-09-01"])
        assert client.list_goals.call_args[1]["params"]["start_date"] == "2026-09-01"

    def test_milestones_forwards_search(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_milestones.return_value = _page()
        with patch("dailybot_cli.commands.project.require_auth", return_value=client):
            runner.invoke(cli, ["project", "milestones", "p-1", "--search", "beta"])
        assert client.list_milestones.call_args[1]["params"]["search"] == "beta"

    def test_task_comments_forwards_search(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_task_comments.return_value = _page()
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            runner.invoke(cli, ["task", "comments", "t-1", "--search", "deploy"])
        assert client.list_task_comments.call_args[1]["params"]["search"] == "deploy"

    def test_include_and_filters_coexist(self, real_client: DailyBotClient) -> None:
        # They used to compete: `include` was hardcoded into `params`.
        with patch("httpx.get", return_value=_ok()) as mock_get:
            real_client.list_goals(include=["progress"], params={"search": "q4"})
        sent: dict[str, Any] = mock_get.call_args[1]["params"]
        assert sent["include"] == "progress"
        assert sent["search"] == "q4"

    def test_task_list_does_not_advertise_filters_the_door_refuses(self, runner: CliRunner) -> None:
        # `/v1/tasks/tasks/` is strict and declares none of the shared text/date
        # filters. The first fix dropped them silently, which still let a caller
        # believe `--search deploy` had filtered; the flags are now simply not
        # offered, so a bad invocation is a usage error instead of a wrong answer.
        out: str = runner.invoke(cli, ["task", "list", "--help"]).output
        for undeclared in ("--search", "--last-week", "--since", "--until"):
            assert undeclared not in out

    def test_task_list_rejects_an_undeclared_filter_as_a_usage_error(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(cli, ["task", "list", "--last-week"])
        assert result.exit_code == 2
        client.list_tasks.assert_not_called()

    def test_tasks_search_does_not_advertise_date_flags_it_drops(self, runner: CliRunner) -> None:
        out: str = runner.invoke(cli, ["tasks", "search", "--help"]).output
        assert "--last-week" not in out
        assert "--since" not in out


class TestCountsRespectsTheInjectionBoundary:
    """Finding 10: `tasks counts` interpolated key and value into markup."""

    def test_a_markup_bucket_name_is_escaped_and_quoted(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_my_task_counts.return_value = {"[bold red]pwned[/]": 1}
        with (
            patch("dailybot_cli.commands.tasks.require_auth", return_value=client),
            patch("dailybot_cli.commands.tasks.get_token", return_value="tok"),
        ):
            result = runner.invoke(cli, ["tasks", "counts"])
        # The literal characters DO appear — that is the point: they are shown as
        # data instead of being interpreted as a style tag. What must be true is
        # that the value went through the presenter, i.e. it is quoted.
        assert '"' in result.output
        assert "pwned" in result.output

    def test_a_trusted_field_name_stays_plain(self) -> None:
        assert "uuid" in TASKS_TRUSTED_FIELDS


class TestRenderersAreShared:
    """Finding 12: four commands built Rich tables inline (AGENTS.md rule 5)."""

    @pytest.mark.parametrize(
        "helper",
        [
            "print_boards_table",
            "print_projects_table",
            "print_goals_table",
            "print_milestones_table",
        ],
    )
    def test_the_helper_exists_in_display(self, helper: str) -> None:
        import dailybot_cli.display as display

        assert hasattr(display, helper)

    @pytest.mark.parametrize("module", ["board", "project", "goal"])
    def test_no_command_module_builds_a_table_itself(self, module: str) -> None:
        import pathlib

        repo: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent
        src: str = (repo / "dailybot_cli" / "commands" / f"{module}.py").read_text()
        assert "Table(title=" not in src, f"{module}.py still builds a Rich table inline"


class TestNoDuplicatedServerCeiling:
    """Finding 13: display.py hardcoded 7 instead of the named constant."""

    def test_the_window_constant_is_imported_not_copied(self) -> None:
        import pathlib

        repo: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent
        src: str = (repo / "dailybot_cli" / "display.py").read_text()
        assert "TASKS_DELTA_MAX_WINDOW_DAYS" in src
        assert 'delta.get("max_window_days", 7)' not in src


class TestDocumentationMatchesTheCode:
    """Finding 11: the credential table listed a command that does not exist."""

    def test_a_documented_participants_remove_exists(self) -> None:
        import pathlib

        from click.testing import CliRunner

        from dailybot_cli.main import cli

        # The finding was a doc naming a command the CLI lacked. PR3 of the Tasks
        # Beta built `task participants remove`, so the guard now runs the other
        # way: whatever the docs name must actually be there.
        repo: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent
        documented: bool = any(
            "participants" in (repo / doc).read_text() and "remove" in (repo / doc).read_text()
            for doc in ("docs/API_REFERENCE.md", "README.md")
        )
        assert documented
        result = CliRunner().invoke(cli, ["task", "participants", "remove", "--help"])
        assert result.exit_code == 0
