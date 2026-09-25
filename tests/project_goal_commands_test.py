"""`dailybot project` and `dailybot goal` (plan tasks 10, 15, 16).

The three-state roll-up rendering is the point of this file. AD-01 was a real
server-side defect where list and detail disagreed for the same goal; the fix was
to OMIT an uncomputed field. A client that renders absence as `0` reintroduces the
defect at the presentation layer.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import DailyBotClient, PaginatedResult
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


def _page(rows: list[dict[str, Any]] | None = None) -> PaginatedResult:
    items = rows or []
    return PaginatedResult(results=items, count=len(items), next=None, previous=None)


def _invoke(runner: CliRunner, client: MagicMock, args: list[str], module: str = "project") -> Any:
    with patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client):
        return runner.invoke(cli, args)


class TestProjectReads:
    def test_list_calls_the_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_projects.return_value = _page([{"uuid": "p-1", "name": "Apollo"}])
        assert _invoke(runner, client, ["project", "list"]).exit_code == 0
        client.list_projects.assert_called_once()

    def test_get_calls_the_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_project.return_value = {"uuid": "p-1", "name": "Apollo"}
        assert _invoke(runner, client, ["project", "get", "p-1"]).exit_code == 0
        client.get_project.assert_called_once()

    def test_updates_uses_the_batched_digest(self, runner: CliRunner, client: MagicMock) -> None:
        # The batched door exists precisely to replace one request per project.
        client.list_project_updates.return_value = _page([{"uuid": "u-1", "body": "shipped"}])
        assert _invoke(runner, client, ["project", "updates"]).exit_code == 0
        client.list_project_updates.assert_called_once()
        client.get_project.assert_not_called()


class TestGoalReads:
    def test_list_calls_the_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_goals.return_value = _page([{"uuid": "g-1", "name": "Q4"}])
        assert _invoke(runner, client, ["goal", "list"], module="goal").exit_code == 0
        client.list_goals.assert_called_once()

    def test_get_calls_the_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_goal.return_value = {"uuid": "g-1", "name": "Q4"}
        assert _invoke(runner, client, ["goal", "get", "g-1"], module="goal").exit_code == 0


class TestIncludesAreOptIn:
    def test_no_include_is_sent_by_default(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_goals.return_value = _page()
        _invoke(runner, client, ["goal", "list"], module="goal")
        assert client.list_goals.call_args[1]["include"] is None

    def test_include_is_forwarded_when_asked(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_goals.return_value = _page()
        _invoke(
            runner,
            client,
            ["goal", "list", "--include", "progress", "--include", "projects"],
            module="goal",
        )
        assert set(client.list_goals.call_args[1]["include"]) == {"progress", "projects"}


class TestAbsentNullZeroAreThreeAnswers:
    """AD-01 — the whole reason includes are opt-in."""

    def test_an_absent_rollup_renders_as_not_requested(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_goals.return_value = _page([{"uuid": "g-1", "name": "Q4"}])
        out: str = _invoke(runner, client, ["goal", "list"], module="goal").output
        assert "not requested" in out.lower()

    def test_a_null_rollup_renders_as_nothing_to_measure(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # null is legitimately different: the goal has nothing to measure yet.
        client.list_goals.return_value = _page([{"uuid": "g-1", "name": "Q4", "progress": None}])
        out: str = _invoke(
            runner, client, ["goal", "list", "--include", "progress"], module="goal"
        ).output
        assert "nothing to measure" in out.lower()

    def test_a_zero_rollup_renders_as_the_real_value(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # Zero is a REAL value here: a goal genuinely can have no projects.
        client.list_goals.return_value = _page(
            [{"uuid": "g-1", "name": "Q4", "progress": 0, "project_count": 0}]
        )
        out: str = _invoke(
            runner, client, ["goal", "list", "--include", "progress"], module="goal"
        ).output
        assert "0" in out
        assert "not requested" not in out.lower()

    def test_absence_is_never_defaulted_to_zero_in_json(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_goals.return_value = _page([{"uuid": "g-1", "name": "Q4"}])
        result = _invoke(runner, client, ["goal", "list", "--json"], module="goal")
        row: dict[str, Any] = json.loads(result.output)["results"][0]
        assert "progress" not in row
        assert "project_count" not in row


class TestUntrustedRendering:
    def test_project_names_render_as_quoted_data(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_projects.return_value = _page([{"uuid": "p-1", "name": "rm -rf everything"}])
        assert '"' in _invoke(runner, client, ["project", "list"]).output


class TestNoCreateHintThatCannotBeHonoured:
    def test_a_read_command_does_not_suggest_creating(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # Container creates need tasks:admin, which no API key can hold.
        client.list_projects.return_value = _page()
        out: str = _invoke(runner, client, ["project", "list"]).output
        assert "project create" not in out


class TestHelp:
    @pytest.mark.parametrize(
        "args",
        [
            ["project", "list"],
            ["project", "get"],
            ["project", "updates"],
            ["goal", "list"],
            ["goal", "get"],
        ],
    )
    def test_help_renders(self, runner: CliRunner, args: list[str]) -> None:
        assert runner.invoke(cli, [*args, "--help"]).exit_code == 0


# ---------------------------------------------------------------------------
# Project updates and milestones (plan task 15)
# ---------------------------------------------------------------------------


class TestProjectUpdatePost:
    def test_it_posts_the_body(self, runner: CliRunner, client: MagicMock) -> None:
        client.post_project_update.return_value = {"uuid": "u-1", "_idempotency_replayed": False}
        result = _invoke(runner, client, ["project", "update-post", "p-1", "shipped the thing"])
        assert result.exit_code == 0
        assert client.post_project_update.call_args[1]["body"] == "shipped the thing"

    def test_the_body_can_come_from_stdin(self, runner: CliRunner, client: MagicMock) -> None:
        client.post_project_update.return_value = {"uuid": "u-1", "_idempotency_replayed": False}
        with patch("dailybot_cli.commands.project.require_auth", return_value=client):
            result = runner.invoke(
                cli, ["project", "update-post", "p-1", "-"], input="a long update\n"
            )
        assert result.exit_code == 0
        assert "a long update" in client.post_project_update.call_args[1]["body"]

    def test_the_idempotency_key_flag_is_offered(self, runner: CliRunner) -> None:
        # The door honours Idempotency-Key since API R4, so the flag is real now.
        assert (
            "--idempotency-key" in runner.invoke(cli, ["project", "update-post", "--help"]).output
        )

    def test_no_web_url_is_printed_after_posting(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.post_project_update.return_value = {"uuid": "u-1", "_idempotency_replayed": False}
        result = _invoke(runner, client, ["project", "update-post", "p-1", "done"])
        for invented in ("http://", "https://", "app.dailybot.com"):
            assert invented not in result.output


class TestMilestoneList:
    def test_it_scopes_to_a_project_when_given(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_milestones.return_value = _page([{"uuid": "m-1", "name": "Beta"}])
        result = _invoke(runner, client, ["project", "milestones", "p-1"])
        assert result.exit_code == 0
        assert client.list_milestones.call_args[0][0] == "p-1"


class TestMilestoneComplete:
    def test_dry_run_mutates_nothing(self, runner: CliRunner, client: MagicMock) -> None:
        client.complete_milestone.return_value = {
            "operation": "milestone.complete",
            "dry_run": True,
            "reversible": True,
            "consequence": "Marks the milestone complete. Open tasks stay open.",
            "_idempotency_replayed": False,
        }
        result = _invoke(
            runner, client, ["project", "milestone-complete", "p-1", "m-1", "--dry-run"]
        )
        assert result.exit_code == 0
        assert client.complete_milestone.call_count == 1
        assert client.complete_milestone.call_args[1]["dry_run"] is True

    def test_the_success_message_says_open_tasks_stay_open(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # The thing a user will otherwise assume wrongly.
        client.complete_milestone.side_effect = [
            {
                "consequence": "x",
                "reversible": True,
                "operation": "milestone.complete",
                "_idempotency_replayed": False,
            },
            {"uuid": "m-1", "_idempotency_replayed": False},
        ]
        result = _invoke(runner, client, ["project", "milestone-complete", "p-1", "m-1", "--yes"])
        assert result.exit_code == 0
        assert "open tasks" in result.output.lower()

    def test_help_says_open_tasks_stay_open(self, runner: CliRunner) -> None:
        out: str = runner.invoke(cli, ["project", "milestone-complete", "--help"]).output.lower()
        assert "open tasks" in out


class TestMilestoneReopen:
    def test_it_calls_the_reopen_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.reopen_milestone.return_value = {"uuid": "m-1", "_idempotency_replayed": False}
        result = _invoke(runner, client, ["project", "milestone-reopen", "p-1", "m-1"])
        assert result.exit_code == 0
        client.reopen_milestone.assert_called_once_with("p-1", "m-1", idempotency_key=None)
