"""Regression tests for the CI AI review's sixth pass on PR #85.

Ten findings, and the same lesson as round 5 arriving from a new direction: the
`--json` promise — one parseable document on stdout on every path — had been kept
at the *server-refusal* boundary and dropped at the *client-refusal* one. Four
copies of the same pre-flight refused a bare API key with prose on stderr and an
empty stdout, so a caller that parses stdout on any non-zero exit read a
credential problem as a crash.

The rest: one Tasks family emitting two incompatible error envelopes, a goal-only
`--include` value offered on projects, a help example Click itself rejects, and a
message that told a signed-in member to sign in again.
"""

import json
from contextlib import nullcontext as _nullcontext
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient, PaginatedResult
from dailybot_cli.commands.project import GOAL_INCLUDE_VALUES, PROJECT_INCLUDE_VALUES
from dailybot_cli.commands.public_api_helpers import (
    EXIT_NOT_AUTHENTICATED,
    EXIT_NOT_FOUND,
    EXIT_PERMISSION_DENIED,
    resolve_error_message,
)
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


def _empty() -> PaginatedResult:
    return PaginatedResult(results=[], count=0, next=None, previous=None)


class TestPreflightRefusalsHonourJson:
    """Findings 1-4: four copies of the same pre-flight ignored `--json`.

    `exit_for_tasks_error` promises a parseable document on every refusal path.
    The client-side pre-flight bypassed it entirely — `dailybot board create --json`
    under a key-only session exited 3 with **empty stdout**.
    """

    @pytest.mark.parametrize(
        ("argv", "module", "expected_exit"),
        [
            (["tasks", "inbox", "--json"], "tasks", EXIT_NOT_AUTHENTICATED),
            (["tasks", "mine", "--json"], "tasks", EXIT_NOT_AUTHENTICATED),
            (["tasks", "counts", "--json"], "tasks", EXIT_NOT_AUTHENTICATED),
            (["board", "create", "--name", "b", "--json"], "board", EXIT_PERMISSION_DENIED),
            (["project", "create", "--name", "p", "--json"], "project", EXIT_PERMISSION_DENIED),
            # `goal create` reuses project's helper, so the token lookup resolves in
            # project's namespace — patching goal's would silently do nothing.
            (
                [
                    "goal",
                    "create",
                    "--name",
                    "g",
                    "--period-start",
                    "2026-10-01",
                    "--period-end",
                    "2026-12-31",
                    "--json",
                ],
                "project",
                EXIT_PERMISSION_DENIED,
            ),
            (
                ["task", "participants", "add", "t-1", "--user", "u-1", "--json"],
                "task",
                EXIT_NOT_AUTHENTICATED,
            ),
        ],
    )
    def test_stdout_carries_the_error_envelope(
        self, runner: CliRunner, argv: list[str], module: str, expected_exit: int
    ) -> None:
        with patch(f"dailybot_cli.commands.{module}.get_token", return_value=None):
            result = runner.invoke(cli, argv)
        assert result.exit_code == expected_exit
        body: Any = json.loads(result.stdout)
        assert body["status"] == "error"
        assert body["message"]

    def test_the_code_matches_what_the_server_would_say(self, runner: CliRunner) -> None:
        # A caller branching on `code` must not have to know whether the request
        # was spent client-side or refused by the server.
        with patch("dailybot_cli.commands.tasks.get_token", return_value=None):
            person = json.loads(runner.invoke(cli, ["tasks", "inbox", "--json"]).stdout)
        with patch("dailybot_cli.commands.board.get_token", return_value=None):
            admin = json.loads(
                runner.invoke(cli, ["board", "create", "--name", "b", "--json"]).stdout
            )
        assert person["code"] == "actor_required"
        assert admin["code"] == "insufficient_scope"

    def test_without_json_the_prose_still_goes_to_stderr(self, runner: CliRunner) -> None:
        with patch("dailybot_cli.commands.tasks.get_token", return_value=None):
            result = runner.invoke(cli, ["tasks", "inbox"])
        assert result.stdout == ""
        assert "dailybot login" in result.stderr


class TestTheMissingCursorBranchHonoursJson:
    """Finding 5: one branch of `tasks changes` was left behind.

    Its siblings — `delta_window_expired` and every API error — already emitted
    JSON. The "snapshot carried no cursor" branch printed to stderr and exited 1
    with nothing on stdout.
    """

    def test_it_emits_an_envelope(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_board_snapshot.return_value = {"board": {"uuid": "b-1"}}
        with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
            result = runner.invoke(cli, ["tasks", "changes", "b-1", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["code"] == "delta_cursor_absent"

    def test_it_still_reads_as_prose_without_json(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_board_snapshot.return_value = {"board": {"uuid": "b-1"}}
        with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
            result = runner.invoke(cli, ["tasks", "changes", "b-1"])
        assert "delta_cursor" in result.stderr


class TestOneErrorEnvelopeForTheWholeFamily:
    """Finding 10: Tasks reads and writes emitted incompatible shapes.

    `exit_for_api_error` produces `{"error", "status": <int>, "code", ...}`;
    `exit_for_tasks_error` produces `{"status": "error", "code", "detail",
    "message"}`. An agent doing `body["status"] == "error"` worked on one door and
    broke on the next — and the inverse broke the other way.
    """

    @pytest.mark.parametrize(
        ("argv", "module", "door"),
        [
            (["board", "list", "--json"], "board", "list_boards"),
            (["board", "get", "b-1", "--json"], "board", "get_board"),
            (["task", "list", "--json"], "task", "list_tasks"),
            (["task", "get", "t-1", "--json"], "task", "get_task"),
            (["project", "list", "--json"], "project", "list_projects"),
            (["goal", "list", "--json"], "goal", "list_goals"),
            (["tasks", "status", "--json"], "tasks", "get_tasks_pulse"),
            (["tasks", "search", "-q", "x", "--json"], "tasks", "search_tasks"),
        ],
    )
    def test_every_door_uses_the_same_shape(
        self, runner: CliRunner, client: MagicMock, argv: list[str], module: str, door: str
    ) -> None:
        getattr(client, door).side_effect = APIError(
            status_code=404, detail="gone", code="not_found"
        )
        # goal.py reuses project's pre-flight and imports no `get_token` of its own.
        token_patch: Any = (
            _nullcontext()
            if module == "goal"
            else patch(f"dailybot_cli.commands.{module}.get_token", return_value="b")
        )
        with (
            patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
            token_patch,
        ):
            result = runner.invoke(cli, argv)
        body: Any = json.loads(result.stdout)
        assert body["status"] == "error", argv
        assert body["code"] == "not_found"
        assert result.exit_code == EXIT_NOT_FOUND


class TestIncludeValuesAreShapedPerObject:
    """Finding 8: `projects` is a goal-shaped selector offered on projects.

    Sharing one Choice let `project list --include projects` past Click and onto
    the wire, where it is either rejected or silently ignored.
    """

    def test_projects_only_offers_progress(self) -> None:
        assert PROJECT_INCLUDE_VALUES == ("progress",)
        assert "projects" in GOAL_INCLUDE_VALUES

    def test_project_list_rejects_the_goal_selector(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        with patch("dailybot_cli.commands.project.require_auth", return_value=client):
            result = runner.invoke(cli, ["project", "list", "--include", "projects"])
        assert result.exit_code == 2
        client.list_projects.assert_not_called()

    def test_goal_list_still_accepts_it(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_goals.return_value = _empty()
        with patch("dailybot_cli.commands.goal.require_auth", return_value=client):
            result = runner.invoke(cli, ["goal", "list", "--include", "projects"])
        assert result.exit_code == 0


class TestHelpExamplesAreValidInvocations:
    """Findings 6-7: the documented `--include progress,projects` is a usage error.

    `--include` is `multiple=True` over a `click.Choice`, so a comma-joined value
    is rejected before any HTTP call. Copying the example was guaranteed to fail.
    """

    def test_the_comma_form_is_rejected(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["goal", "list", "--include", "progress,projects"])
        assert result.exit_code == 2

    def test_the_documented_form_is_accepted(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_goals.return_value = _empty()
        with patch("dailybot_cli.commands.goal.require_auth", return_value=client):
            result = runner.invoke(
                cli, ["goal", "list", "--include", "progress", "--include", "projects"]
            )
        assert result.exit_code == 0

    def test_the_group_help_shows_the_repeatable_form(self, runner: CliRunner) -> None:
        out: str = runner.invoke(cli, ["goal", "--help"]).stdout
        assert "progress,projects" not in out


class TestAdminScopeMessageDiagnosesTheRightThing:
    """Finding 9: a signed-in member was told an API key can never hold the scope.

    True of a key; not true of them. The fix for a member is a role, and telling
    them to `dailybot login` sends them round in a circle.
    """

    def _refusal(self) -> APIError:
        return APIError(
            status_code=403,
            detail="nope",
            code="insufficient_scope",
            extra={"required_scope": "tasks:admin"},
        )

    def test_a_signed_in_member_is_told_to_ask_an_admin(self) -> None:
        with patch("dailybot_cli.commands.public_api_helpers.get_token", return_value="bearer"):
            message: str = resolve_error_message(self._refusal())
        assert "role limit" in message
        assert "can never hold" not in message

    def test_a_key_only_session_keeps_the_credential_diagnosis(self) -> None:
        with patch("dailybot_cli.commands.public_api_helpers.get_token", return_value=None):
            message: str = resolve_error_message(self._refusal())
        assert "can never hold" in message
        assert "dailybot login" in message

    def test_other_scopes_are_unaffected(self) -> None:
        exc = APIError(
            status_code=403,
            detail="nope",
            code="insufficient_scope",
            extra={"required_scope": "tasks:write"},
        )
        with patch("dailybot_cli.commands.public_api_helpers.get_token", return_value="bearer"):
            assert "tasks:write" in resolve_error_message(exc)
