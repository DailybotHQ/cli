"""Regression tests for the CI AI review's fourth pass on PR #85.

Eight findings, all `warning` severity, all real. The theme that unites most of
them is the same one the earlier rounds surfaced from a different angle: a
**contract the CLI advertises but does not keep** — a flag in `--help` the wire
never carries, a `--json` promise broken by a Rich panel, an exit code the
published table does not list, a footer suggesting a flag the command lacks.

Each test here fails against the code as the reviewer saw it.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient, PaginatedResult, TransportError
from dailybot_cli.commands.public_api_helpers import (
    EXIT_NOT_FOUND,
    EXIT_USAGE_ERROR,
    tasks_write_exit_code,
)
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    # Click 8.2+ keeps the two streams apart by default, which is what this whole
    # file is about: several findings are "the right bytes went to the wrong stream".
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


@pytest.fixture
def real_client() -> DailyBotClient:
    return DailyBotClient(api_url="http://t.example.com", token="t", api_key="k")


def _page(
    rows: list[dict[str, Any]] | None = None, *, next_url: str | None = None
) -> PaginatedResult:
    items: list[dict[str, Any]] = rows or []
    total: int = len(items) + 10 if next_url else len(items)
    return PaginatedResult(results=items, count=total, next=next_url, previous=None)


_PREVIEW: dict[str, Any] = {
    "operation": "archive",
    "reversible": True,
    "restore_path": "dailybot task restore <uuid>",
    "consequence": "Archives the task and its 3 subtasks.",
    "affects": {"tasks": 4},
}


class TestPaginationFooterNamesAFlagTheCommandHas:
    """Finding 1: `@paging_options` commands suggested `--all`, which they lack.

    The footer's default hint is "use --all to fetch every page". `paging_options`
    deliberately does not declare `--all`, so following the CLI's own advice was a
    Click usage error — the worst kind of hint.
    """

    @pytest.mark.parametrize(
        ("argv", "door"),
        [
            (["task", "list"], "list_tasks"),
            (["tasks", "search", "-q", "deploy"], "search_tasks"),
            (["tasks", "inbox"], "list_tasks_inbox"),
            (["tasks", "mine"], "list_my_tasks"),
        ],
    )
    def test_footer_does_not_advertise_all(
        self, runner: CliRunner, client: MagicMock, argv: list[str], door: str
    ) -> None:
        getattr(client, door).return_value = _page([{"uuid": "t-1"}], next_url="http://n/2")
        module: str = "tasks" if argv[0] == "tasks" else "task"
        with (
            patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
            patch(f"dailybot_cli.commands.{module}.get_token", return_value="bearer"),
        ):
            result = runner.invoke(cli, argv)
        assert "--all" not in result.stdout
        assert "--page" in result.stdout

    def test_the_suggested_flag_actually_exists(self, runner: CliRunner) -> None:
        # The hint is only worth anything if following it works.
        out: str = runner.invoke(cli, ["task", "list", "--help"]).stdout
        assert "--page" in out and "--page-size" in out


class TestJsonModeKeepsStdoutParseable:
    """Findings 2 and 8: the destructive flow printed Rich to stdout under --json.

    `--dry-run --json` was already correct. The **mutate** path was not: it
    rendered the consequence panel to stdout and then emitted the result JSON, so
    `json.loads(stdout)` raised at column 1. The panel is not dropped — losing the
    record of what was about to happen would trade one defect for another — it
    moves to stderr.
    """

    def _archive(self, runner: CliRunner, client: MagicMock, argv: list[str], module: str) -> Any:
        with (
            patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
            patch(f"dailybot_cli.commands.{module}.get_token", return_value="bearer"),
        ):
            return runner.invoke(cli, argv)

    def test_task_archive_yes_json_emits_only_json_on_stdout(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.archive_task.side_effect = [_PREVIEW, {"uuid": "t-1", "is_archived": True}]
        result = self._archive(
            runner, client, ["task", "archive", "t-1", "--yes", "--json"], "task"
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"uuid": "t-1", "is_archived": True}

    def test_the_consequence_still_reaches_the_operator_on_stderr(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.archive_task.side_effect = [_PREVIEW, {"uuid": "t-1"}]
        result = self._archive(
            runner, client, ["task", "archive", "t-1", "--yes", "--json"], "task"
        )
        assert "Dry run" in result.stderr

    def test_milestone_complete_uses_the_shared_helper(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # It used to carry its own copy of preview/confirm/mutate and drifted.
        client.complete_milestone.side_effect = [_PREVIEW, {"uuid": "m-1", "completed": True}]
        result = self._archive(
            runner,
            client,
            ["project", "milestone-complete", "p-1", "m-1", "--yes", "--json"],
            "project",
        )
        assert json.loads(result.stdout) == {"uuid": "m-1", "completed": True}

    def test_a_failed_preview_still_emits_json(self, runner: CliRunner, client: MagicMock) -> None:
        # Not knowing the blast radius aborts — but an agent parsing stdout on a
        # non-zero exit must not get an empty stream.
        client.archive_task.side_effect = APIError(status_code=404, detail="gone", code="not_found")
        result = self._archive(
            runner, client, ["task", "archive", "t-1", "--yes", "--json"], "task"
        )
        # Exit 5, not 1: the fifth review round showed a flat 1 here made an agent
        # branching "5 → skip, 1 → alert" page on every already-archived object.
        assert result.exit_code == EXIT_NOT_FOUND
        assert json.loads(result.stdout)["status"] == "error"

    def test_dry_run_json_is_unchanged(self, runner: CliRunner, client: MagicMock) -> None:
        client.archive_task.return_value = _PREVIEW
        result = self._archive(
            runner, client, ["task", "archive", "t-1", "--dry-run", "--json"], "task"
        )
        assert json.loads(result.stdout)["affects"] == {"tasks": 4}

    def test_without_json_the_panel_stays_on_stdout(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # The human path must not regress into stderr-only output.
        client.archive_task.side_effect = [_PREVIEW, {"uuid": "t-1"}]
        result = self._archive(runner, client, ["task", "archive", "t-1", "--yes"], "task")
        assert "Dry run" in result.stdout


class TestBulkOperationIsNotMarkup:
    """Finding 3: free-form `--operation` was interpolated into a Rich string.

    `[/bold][red]x` raised MarkupError *before* the HTTP call, and the root safety
    net then told the user the CLI had a bug.
    """

    def test_markup_shaped_operation_reaches_the_api(
        self, runner: CliRunner, client: MagicMock, tmp_path: Any
    ) -> None:
        batch = tmp_path / "b.json"
        batch.write_text('[{"uuid": "t-1"}]')
        client.bulk_tasks.return_value = {"results": [{"uuid": "t-1", "status": "ok"}]}
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(
                cli,
                ["task", "bulk", "--operation", "[/bold][red]x", "-f", str(batch), "--yes"],
            )
        assert "Unexpected error" not in result.stderr
        assert client.bulk_tasks.call_args[1]["operation"] == "[/bold][red]x"

    def test_the_confirmation_prompt_survives_markup(
        self, runner: CliRunner, client: MagicMock, tmp_path: Any
    ) -> None:
        batch = tmp_path / "b.json"
        batch.write_text('[{"uuid": "t-1"}]')
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(
                cli, ["task", "bulk", "--operation", "[bold]x", "-f", str(batch)], input="n\n"
            )
        assert "MarkupError" not in (result.stderr + result.stdout)


class TestTasksWriteExitCodesCoverBadInput:
    """Finding 4: a 400 on a Tasks write fell through to exit 1.

    The read path (`exit_for_api_error`) already returned 2 for a 400, so the same
    refusal produced two different codes depending on which door raised it.
    """

    def test_four_hundred_is_a_usage_error(self) -> None:
        assert tasks_write_exit_code(APIError(status_code=400, detail="bad")) == EXIT_USAGE_ERROR

    def test_too_many_items_exits_two(
        self, runner: CliRunner, client: MagicMock, tmp_path: Any
    ) -> None:
        batch = tmp_path / "b.json"
        batch.write_text('[{"uuid": "t-1"}]')
        client.bulk_tasks.side_effect = APIError(
            status_code=400, detail="too many", code="too_many_items"
        )
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(
                cli, ["task", "bulk", "--operation", "archive", "-f", str(batch), "--yes"]
            )
        assert result.exit_code == EXIT_USAGE_ERROR


class TestDoorsOnlyAdvertiseFiltersTheyCarry:
    """Findings 5 and 6: flags in `--help` that never reached the wire.

    `tasks timeline` dropped `--search` on the way to the client. `tasks mine` and
    `tasks inbox` forwarded it to a door that **silently ignores** unknown
    parameters — so the caller got an unfiltered list and exit 0, which is worse
    than a refusal because nothing signals that the filter did not apply.
    """

    @pytest.mark.parametrize("argv", [["tasks", "timeline"], ["tasks", "mine"], ["tasks", "inbox"]])
    def test_search_is_not_offered(self, runner: CliRunner, argv: list[str]) -> None:
        out: str = runner.invoke(cli, [*argv, "--help"]).stdout
        assert "--search" not in out
        assert "--grep" not in out

    @pytest.mark.parametrize("argv", [["tasks", "timeline"], ["tasks", "mine"], ["tasks", "inbox"]])
    def test_search_is_now_a_usage_error(
        self, runner: CliRunner, client: MagicMock, argv: list[str]
    ) -> None:
        with (
            patch("dailybot_cli.commands.tasks.require_auth", return_value=client),
            patch("dailybot_cli.commands.tasks.get_token", return_value="bearer"),
        ):
            result = runner.invoke(cli, [*argv, "--search", "deploy"])
        assert result.exit_code == EXIT_USAGE_ERROR

    def test_timeline_keeps_the_date_window_it_does_carry(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_tasks_timeline.return_value = _page()
        with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
            runner.invoke(cli, ["tasks", "timeline", "--since", "2026-09-01"])
        assert client.list_tasks_timeline.call_args[1]["date_from"] == "2026-09-01"

    def test_mine_keeps_the_one_filter_the_door_declares(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_my_tasks.return_value = _page()
        with (
            patch("dailybot_cli.commands.tasks.require_auth", return_value=client),
            patch("dailybot_cli.commands.tasks.get_token", return_value="bearer"),
        ):
            runner.invoke(cli, ["tasks", "mine", "--scope", "assigned"])
        assert client.list_my_tasks.call_args[1]["params"] == {"scope": "assigned"}


class TestListReadsAreCoveredByTheTransportNet:
    """Finding 7: `_paginated_get` did a bare `.json()` on a 2xx body.

    `_handle_response` already converted an unreadable success body into a
    `TransportError` (exit 8). Every Tasks *list* read bypasses that helper on the
    success path, so a captive-portal HTML 200 surfaced as a raw JSONDecodeError
    and exit 1 — not the code agents are told to branch on.
    """

    def test_an_html_two_hundred_becomes_a_transport_error(
        self, real_client: DailyBotClient
    ) -> None:
        html: MagicMock = MagicMock(spec=httpx.Response)
        html.status_code = 200
        html.json.side_effect = ValueError("Expecting value")
        html.headers = {}
        html.text = "<html>captive portal</html>"
        with patch("httpx.get", return_value=html), pytest.raises(TransportError):
            real_client.list_tasks()

    def test_a_readable_body_is_untouched(self, real_client: DailyBotClient) -> None:
        ok: MagicMock = MagicMock(spec=httpx.Response)
        ok.status_code = 200
        ok.json.return_value = {"count": 1, "next": None, "previous": None, "results": [{"u": 1}]}
        ok.headers = {}
        with patch("httpx.get", return_value=ok):
            assert real_client.list_tasks().results == [{"u": 1}]
