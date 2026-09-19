"""Comprehensive coverage sweep for the Tasks surface (plan task 20).

This file closes the gaps *between* tasks — the interactions no single command
owns — and pins three things the registry names as blind spots: Click flag wiring,
`display.py` rendering asserted only indirectly, and shared-helper changes exercised
through one file.

Everything here is mocked (rule 7). The mocked-httpx tests ARE the contract tests
for every endpoint, which is why request-shape assertions matter as much as
response handling.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import (
    IDEMPOTENCY_KEY_HEADER,
    APIError,
    DailyBotClient,
    PaginatedResult,
)
from dailybot_cli.commands.public_api_helpers import ERROR_CODE_MESSAGES, TASKS_ERROR_CODES
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


# --- The 19 phase-1 capabilities -------------------------------------------
# Each row: capability number, command, the client method it must call.
CAPABILITIES: list[tuple[int, str, list[str], str]] = [
    (1, "tasks status", ["tasks", "status"], "get_tasks_pulse"),
    (2, "tasks changes", ["tasks", "changes", "b-1", "--cursor", "c"], "get_board_delta"),
    (3, "tasks search", ["tasks", "search", "-q", "x"], "search_tasks"),
    (4, "tasks inbox", ["tasks", "inbox"], "list_tasks_inbox"),
    (5, "task list", ["task", "list"], "list_tasks"),
    (6, "task get", ["task", "get", "t-1"], "get_task"),
    (7, "task create", ["task", "create", "--title", "x"], "create_task"),
    (8, "task update", ["task", "update", "t-1", "--title", "y"], "update_task"),
    (9, "task move", ["task", "move", "t-1", "--state", "done"], "move_task"),
    (10, "task assign", ["task", "assign", "t-1", "--to", "u-1"], "update_task"),
    (11, "task comment", ["task", "comment", "t-1", "hi"], "comment_on_task"),
    (12, "task link", ["task", "link", "t-1", "t-2", "--type", "blocks"], "relate_tasks"),
    (13, "task archive", ["task", "archive", "t-1", "--dry-run"], "archive_task"),
    (14, "task bulk", [], "bulk_tasks"),  # exercised in task_commands_test (needs a file)
    (15, "board snapshot", ["board", "snapshot", "b-1"], "get_board_snapshot"),
    (16, "project get", ["project", "get", "p-1"], "get_project"),
    (17, "project update-post", ["project", "update-post", "p-1", "shipped"], "post_project_update"),
    (18, "goal list", ["goal", "list"], "list_goals"),
    (19, "milestone complete", ["project", "milestone-complete", "p-1", "m-1", "--dry-run"],
     "complete_milestone"),
]

_MODULE_FOR: dict[str, str] = {
    "tasks": "tasks", "task": "task", "board": "board", "project": "project", "goal": "goal"
}


def _default_return(method: str) -> Any:
    listy: set[str] = {
        "search_tasks", "list_tasks", "list_tasks_inbox", "list_goals", "list_boards",
        "list_projects", "list_project_updates", "list_milestones", "list_task_comments",
        "list_tasks_activity", "list_tasks_timeline", "list_my_tasks",
    }
    if method in listy:
        return _page([{"uuid": "x-1", "key": "K-1", "title": "t", "name": "n"}])
    if method in {"archive_task", "complete_milestone"}:
        return {"operation": "x", "reversible": True, "consequence": "c",
                "_idempotency_replayed": False}
    return {"uuid": "x-1", "key": "K-1", "title": "t", "name": "n",
            "delta_cursor": "c-2", "_idempotency_replayed": False}


class TestEveryPhaseOneCapabilityIsReachable:
    @pytest.mark.parametrize(
        "num,label,args,method",
        [row for row in CAPABILITIES if row[2]],
        ids=[f"{row[0]:02d}-{row[1]}" for row in CAPABILITIES if row[2]],
    )
    def test_the_command_exists_and_calls_its_door(
        self, runner: CliRunner, client: MagicMock, num: int, label: str,
        args: list[str], method: str,
    ) -> None:
        getattr(client, method).return_value = _default_return(method)
        module: str = _MODULE_FOR[args[0]]
        with (
            patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
            patch(f"dailybot_cli.commands.{module}.get_agent_auth", return_value="bearer",
                  create=True),
        ):
            result = runner.invoke(cli, args)
        assert result.exit_code == 0, f"capability {num} ({label}) failed: {result.output}"
        assert getattr(client, method).called, f"capability {num} did not call {method}"


class TestEveryErrorCodeIsMapped:
    @pytest.mark.parametrize("code", sorted(TASKS_ERROR_CODES))
    def test_the_code_has_an_actionable_message(self, code: str) -> None:
        message: str = ERROR_CODE_MESSAGES[code]
        assert len(message) > 20, f"{code} has no actionable message"
        assert "DailyBot" not in message  # rule 13: legacy spelling


class TestFlagWiringRenders:
    """The registry's named blind spot: only a real render catches broken wiring."""

    @pytest.mark.parametrize("group", ["tasks", "task", "board", "project", "goal"])
    def test_every_subcommand_of_every_group_renders_help(
        self, runner: CliRunner, group: str
    ) -> None:
        subs = list(cli.commands[group].commands)  # type: ignore[attr-defined]
        assert subs, f"{group} has no subcommands"
        for sub in subs:
            result = runner.invoke(cli, [group, sub, "--help"])
            assert result.exit_code == 0, f"{group} {sub} --help failed"

    @pytest.mark.parametrize("group", ["tasks", "task", "board", "project", "goal"])
    def test_no_short_flag_is_declared_twice_anywhere(self, group: str) -> None:
        for sub, command in cli.commands[group].commands.items():  # type: ignore[attr-defined]
            shorts: list[str] = [
                opt for param in command.params for opt in getattr(param, "opts", [])
                if opt.startswith("-") and not opt.startswith("--")
            ]
            assert len(shorts) == len(set(shorts)), f"{group} {sub}: duplicate shorts {shorts}"


# One table, so drift is caught once rather than per-command.
ACCEPTS: list[tuple[str, dict[str, Any]]] = [
    ("create_task", {"title": "x"}),
    ("update_task", {"task_uuid": "t-1", "title": "x"}),
    ("move_task", {"task_uuid": "t-1", "state": "done"}),
    ("archive_task", {"task_uuid": "t-1"}),
    ("restore_task", {"task_uuid": "t-1"}),
    ("comment_on_task", {"task_uuid": "t-1", "body": "b"}),
    ("relate_tasks", {"task_uuid": "t-1", "other": "t-2", "relation": "blocks"}),
    ("batch_task_labels", {"task_uuid": "t-1", "mode": "add", "labels": ["l"]}),
    ("add_task_participant", {"task_uuid": "t-1", "user_uuid": "u-1"}),
    ("bulk_tasks", {"operation": "archive", "items": [{"uuid": "t-1"}]}),
    ("create_board", {"name": "b"}),
    ("create_project", {"name": "p"}),
    ("create_goal", {"name": "g"}),
]
IGNORES: list[tuple[str, dict[str, Any]]] = [
    ("subscribe_task", {"task_uuid": "t-1"}),
    ("post_project_update", {"project_uuid": "p-1", "body": "b"}),
    ("complete_milestone", {"project_uuid": "p-1", "milestone_uuid": "m-1"}),
    ("reopen_milestone", {"project_uuid": "p-1", "milestone_uuid": "m-1"}),
]


class TestIdempotencyPostureIsTableDriven:
    """Posture is a property of the door, taken from IDEMPOTENCY.md."""

    @pytest.mark.parametrize("method,kwargs", ACCEPTS, ids=[m for m, _ in ACCEPTS])
    def test_an_accepting_door_sends_the_header(
        self, method: str, kwargs: dict[str, Any]
    ) -> None:
        client = DailyBotClient(api_url="http://t.example.com", token="t", api_key="k")
        mock: MagicMock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = {}
        mock.headers = {}
        positional: list[Any] = []
        call_kwargs: dict[str, Any] = dict(kwargs)
        for name in ("task_uuid", "project_uuid", "milestone_uuid"):
            if name in call_kwargs:
                positional.append(call_kwargs.pop(name))
        with (
            patch("httpx.post", return_value=mock) as post,
            patch("httpx.patch", return_value=mock) as patch_m,
        ):
            getattr(client, method)(*positional, **call_kwargs)
        used = post if post.called else patch_m
        assert IDEMPOTENCY_KEY_HEADER in used.call_args[1]["headers"], method

    @pytest.mark.parametrize("method,kwargs", IGNORES, ids=[m for m, _ in IGNORES])
    def test_an_ignoring_door_does_not_send_the_header(
        self, method: str, kwargs: dict[str, Any]
    ) -> None:
        client = DailyBotClient(api_url="http://t.example.com", token="t", api_key="k")
        mock: MagicMock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = {}
        mock.headers = {}
        positional: list[Any] = []
        call_kwargs: dict[str, Any] = dict(kwargs)
        for name in ("task_uuid", "project_uuid", "milestone_uuid"):
            if name in call_kwargs:
                positional.append(call_kwargs.pop(name))
        with patch("httpx.post", return_value=mock) as post:
            getattr(client, method)(*positional, **call_kwargs)
        assert IDEMPOTENCY_KEY_HEADER not in post.call_args[1]["headers"], method


# (args, module that owns require_auth, module where get_agent_auth is RESOLVED)
#
# The third column is not redundant: `goal create` reuses
# `project._require_person_for_admin`, so the guard looks `get_agent_auth` up in
# the *project* namespace. Patching `goal.get_agent_auth` silently does nothing —
# the kind of coupling a table like this makes visible.
PERSON_ONLY: list[tuple[list[str], str, str]] = [
    (["tasks", "inbox"], "tasks", "tasks"),
    (["tasks", "mine"], "tasks", "tasks"),
    (["tasks", "counts"], "tasks", "tasks"),
    (["board", "create", "--name", "x"], "board", "board"),
    (["project", "create", "--name", "x"], "project", "project"),
    (["goal", "create", "--name", "x"], "goal", "project"),
]


class TestRoleMatrixIsTableDriven:
    """Fixtures come from the plan's observed matrix; mocked as always (rule 7)."""

    @pytest.mark.parametrize(
        "args,auth_module,guard_module", PERSON_ONLY,
        ids=[f"{a[0]}-{a[1]}" for a, _, _ in PERSON_ONLY],
    )
    def test_an_api_key_is_refused_with_exit_three(
        self, runner: CliRunner, client: MagicMock, args: list[str],
        auth_module: str, guard_module: str,
    ) -> None:
        with (
            patch(f"dailybot_cli.commands.{auth_module}.require_auth", return_value=client),
            patch(f"dailybot_cli.commands.{guard_module}.get_agent_auth", return_value="api_key"),
        ):
            result = runner.invoke(cli, args)
        assert result.exit_code == 3, f"{args} did not refuse an API key"


class TestJsonModeShape:
    @pytest.mark.parametrize(
        "args,module,method",
        [
            (["task", "list", "--json"], "task", "list_tasks"),
            (["board", "list", "--json"], "board", "list_boards"),
            (["goal", "list", "--json"], "goal", "list_goals"),
            (["project", "list", "--json"], "project", "list_projects"),
        ],
    )
    def test_paginated_json_carries_the_envelope(
        self, runner: CliRunner, client: MagicMock, args: list[str], module: str, method: str
    ) -> None:
        getattr(client, method).return_value = _page([{"uuid": "x-1"}])
        with patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client):
            result = runner.invoke(cli, args)
        body: dict[str, Any] = json.loads(result.output)
        for key in ("count", "next", "previous", "results"):
            assert key in body


class TestCrossCommandSequences:
    def test_snapshot_cursor_feeds_changes(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_board_snapshot.return_value = {"delta_cursor": "2026-09-19T13:13:37Z",
                                                  "groups": []}
        client.get_board_delta.return_value = {"changed": [], "delta_cursor": "c-2"}
        with patch("dailybot_cli.commands.board.require_auth", return_value=client):
            snap = runner.invoke(cli, ["board", "snapshot", "b-1", "--json"])
        cursor: str = json.loads(snap.output)["delta_cursor"]
        with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
            delta = runner.invoke(cli, ["tasks", "changes", "b-1", "--cursor", cursor, "--json"])
        assert delta.exit_code == 0
        assert client.get_board_delta.call_args[1]["updated_since"] == cursor

    def test_create_then_comment_then_archive(self, runner: CliRunner, client: MagicMock) -> None:
        client.create_task.return_value = {"uuid": "t-9", "key": "K-9", "title": "x",
                                           "_idempotency_replayed": False}
        client.comment_on_task.return_value = {"uuid": "c-1", "_idempotency_replayed": False}
        client.archive_task.side_effect = [
            {"operation": "task.archive", "reversible": True, "consequence": "c",
             "_idempotency_replayed": False},
            {"_idempotency_replayed": False},
        ]
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            assert runner.invoke(cli, ["task", "create", "--title", "x"]).exit_code == 0
            assert runner.invoke(cli, ["task", "comment", "t-9", "done"]).exit_code == 0
            assert runner.invoke(cli, ["task", "archive", "t-9", "--yes"]).exit_code == 0

    def test_expired_cursor_leads_to_a_resync(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_board_delta.side_effect = APIError(
            400, "expired", code="delta_window_expired", extra={"full_resync_required": True}
        )
        client.get_board_snapshot.return_value = {"delta_cursor": "fresh", "groups": []}
        with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
            result = runner.invoke(cli, ["tasks", "changes", "b-1", "--cursor", "old", "--resync"])
        assert result.exit_code == 0
        client.get_board_snapshot.assert_called_once_with("b-1")


class TestNoTestReachesTheNetwork:
    def test_the_suite_patches_httpx_rather_than_calling_it(self) -> None:
        # Rule 7 is structural here: DailyBotClient only reaches the network through
        # httpx.<method>, and every test patches those. This asserts the property
        # rather than trusting the convention.
        import pathlib

        offenders: list[str] = []
        for path in pathlib.Path("tests").glob("*.py"):
            text: str = path.read_text()
            for line in text.splitlines():
                stripped: str = line.strip()
                if stripped.startswith("#"):
                    continue
                direct_call: bool = any(
                    m in stripped
                    for m in ("httpx.get(", "httpx.post(", "httpx.patch(",
                              "httpx.put(", "httpx.request(")
                )
                mocked: bool = "patch(" in stripped or "side_effect" in stripped
                if direct_call and not mocked:
                    offenders.append(f"{path}: {stripped}")
        assert offenders == [], f"tests appear to call httpx directly: {offenders}"
