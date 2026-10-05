"""T5 x-cli-command leaves: client wire + Click wiring for Plan agent-first parity.

Contract source: local GET /v1/plan/schema/ (x-cli-command annotations).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import DailyBotClient
from dailybot_cli.main import cli

API: str = "https://api.example.test"
BOARD: str = "11111111-1111-1111-1111-111111111111"
PROJECT: str = "22222222-2222-2222-2222-222222222222"
USER: str = "33333333-3333-3333-3333-333333333333"
LABEL: str = "44444444-4444-4444-4444-444444444444"
SIBLING: str = "55555555-5555-5555-5555-555555555555"


def _client() -> DailyBotClient:
    return DailyBotClient(api_url=API, api_key="test-key")


def _ok(payload: Any = None, *, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload if payload is not None else {},
        headers=headers or {},
        request=httpx.Request("GET", API),
    )


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def auth_client() -> MagicMock:
    client = MagicMock(spec=DailyBotClient)
    with (
        patch("dailybot_cli.commands.public_api_helpers.require_auth", return_value=client),
        patch("dailybot_cli.commands.board.require_auth", return_value=client),
        patch("dailybot_cli.commands.project.require_auth", return_value=client),
        patch("dailybot_cli.commands.tasks.require_auth", return_value=client),
        patch("dailybot_cli.commands.plan_label.require_auth", return_value=client),
        patch("dailybot_cli.commands.plan_views.require_auth", return_value=client),
    ):
        yield client


class TestClientWire:
    def test_reorder_board_posts_before_and_project(self) -> None:
        c = _client()
        with patch.object(c, "_request", return_value=_ok({"uuid": BOARD, "position": 2})) as req:
            c.reorder_board(BOARD, before=SIBLING, project=PROJECT)
        assert req.call_args.args[0] == "POST"
        assert req.call_args.args[1] == f"{API}/v1/plan/boards/{BOARD}/reorder/"
        assert req.call_args.kwargs["json"] == {"before": SIBLING, "project": PROJECT}

    def test_board_move_preview_query(self) -> None:
        c = _client()
        with patch.object(c, "_request", return_value=_ok({"tasks_count": 3})) as req:
            c.board_move_preview(BOARD, project=PROJECT)
        assert req.call_args.args[0] == "GET"
        assert req.call_args.args[1] == f"{API}/v1/plan/boards/{BOARD}/move-preview/"
        assert req.call_args.kwargs["params"] == {"project": PROJECT}

    def test_create_board_view_idempotent(self) -> None:
        c = _client()
        with patch.object(c, "_request", return_value=_ok({"name": "Mine"}, status=201)) as req:
            c.create_board_view(BOARD, name="Mine", filters={}, idempotency_key="k1")
        assert req.call_args.args[0] == "POST"
        assert req.call_args.args[1] == f"{API}/v1/plan/boards/{BOARD}/views/"
        assert req.call_args.kwargs["json"]["name"] == "Mine"
        assert req.call_args.kwargs["extra_headers"]["Idempotency-Key"] == "k1"

    def test_workspace_views_get_and_put_if_match(self) -> None:
        c = _client()
        with patch.object(
            c,
            "_request",
            return_value=_ok({"results": []}, headers={"ETag": '"abc"'}),
        ) as req:
            _data, etag = c.list_workspace_views_with_etag()
        assert etag == '"abc"'
        assert req.call_args.args[1] == f"{API}/v1/plan/views/workspace/"
        with patch.object(c, "_request", return_value=_ok([])) as req2:
            c.save_workspace_views([{"name": "A", "filters": {}}], if_match='"abc"')
        assert req2.call_args.args[0] == "PUT"
        assert req2.call_args.kwargs["extra_headers"]["If-Match"] == '"abc"'

    def test_get_tasks_board(self) -> None:
        c = _client()
        with patch.object(c, "_request", return_value=_ok({"groups": []})) as req:
            c.get_tasks_board(filters={"group_by": "state", "owner": ["me"]})
        assert req.call_args.args[1] == f"{API}/v1/plan/tasks/board/"
        assert req.call_args.kwargs["params"]["group_by"] == "state"

    def test_update_board_member_empty_patch(self) -> None:
        c = _client()
        with patch.object(c, "_request", return_value=_ok({"user_uuid": USER})) as req:
            c.update_board_member(BOARD, USER)
        assert req.call_args.args[0] == "PATCH"
        assert req.call_args.args[1] == f"{API}/v1/plan/boards/{BOARD}/members/{USER}/"
        assert req.call_args.kwargs["json"] == {}

    def test_plan_labels_list_create(self) -> None:
        c = _client()
        with patch.object(
            c,
            "_request",
            return_value=_ok({"count": 0, "next": None, "previous": None, "results": []}),
        ) as req:
            c.list_plan_labels(search="bug", include_archived=True)
        assert "/v1/plan/labels/" in req.call_args.args[1]
        assert req.call_args.kwargs["params"]["search"] == "bug"
        with patch.object(c, "_request", return_value=_ok({"name": "bug"}, status=201)) as req2:
            c.create_plan_label(name="bug", color="#ef4444")
        assert req2.call_args.args[0] == "POST"
        assert req2.call_args.kwargs["json"]["name"] == "bug"

    def test_reorder_project_and_create_project_view(self) -> None:
        c = _client()
        with patch.object(c, "_request", return_value=_ok({"uuid": PROJECT})) as req:
            c.reorder_project(PROJECT, after=SIBLING)
        assert req.call_args.args[1] == f"{API}/v1/plan/projects/{PROJECT}/reorder/"
        assert req.call_args.kwargs["json"] == {"after": SIBLING}
        with patch.object(c, "_request", return_value=_ok({"name": "V"}, status=201)) as req2:
            c.create_project_view(PROJECT, name="V", idempotency_key="p1")
        assert req2.call_args.args[1] == f"{API}/v1/plan/projects/{PROJECT}/views/"
        assert req2.call_args.kwargs["extra_headers"]["Idempotency-Key"] == "p1"

    def test_update_project_member(self) -> None:
        c = _client()
        with patch.object(c, "_request", return_value=_ok({"user_uuid": USER})) as req:
            c.update_project_member(PROJECT, USER)
        assert req.call_args.args[0] == "PATCH"
        assert f"/projects/{PROJECT}/members/{USER}/" in req.call_args.args[1]


class TestCommandWiring:
    def test_board_reorder_json(self, runner: CliRunner, auth_client: MagicMock) -> None:
        auth_client.reorder_board.return_value = {"uuid": BOARD, "position": 1}
        result = runner.invoke(
            cli,
            ["plan", "board", "reorder", BOARD, "--after", SIBLING, "--json"],
        )
        assert result.exit_code == 0, result.output
        auth_client.reorder_board.assert_called_once()
        assert '"position"' in result.output

    def test_board_move_preview(self, runner: CliRunner, auth_client: MagicMock) -> None:
        auth_client.board_move_preview.return_value = {"tasks_count": 2}
        result = runner.invoke(
            cli,
            ["plan", "board", "move-preview", BOARD, "--project", PROJECT, "--json"],
        )
        assert result.exit_code == 0, result.output
        auth_client.board_move_preview.assert_called_once_with(BOARD, project=PROJECT)

    def test_board_view_create(self, runner: CliRunner, auth_client: MagicMock) -> None:
        auth_client.create_board_view.return_value = {"name": "Mine", "uuid": "v1"}
        result = runner.invoke(
            cli,
            ["plan", "board", "view", "create", BOARD, "-n", "Mine", "--json"],
        )
        assert result.exit_code == 0, result.output
        auth_client.create_board_view.assert_called_once()

    def test_board_member_update(self, runner: CliRunner, auth_client: MagicMock) -> None:
        auth_client.update_board_member.return_value = {"user_uuid": USER}
        result = runner.invoke(
            cli,
            ["plan", "board", "member", "update", BOARD, USER, "--json"],
        )
        assert result.exit_code == 0, result.output

    def test_project_reorder_and_member_update(
        self, runner: CliRunner, auth_client: MagicMock
    ) -> None:
        auth_client.reorder_project.return_value = {"uuid": PROJECT}
        r1 = runner.invoke(cli, ["plan", "project", "reorder", PROJECT, "--before", SIBLING, "--json"])
        assert r1.exit_code == 0, r1.output
        auth_client.update_project_member.return_value = {"user_uuid": USER}
        r2 = runner.invoke(
            cli, ["plan", "project", "member", "update", PROJECT, USER, "--json"]
        )
        assert r2.exit_code == 0, r2.output

    def test_project_view_create(self, runner: CliRunner, auth_client: MagicMock) -> None:
        auth_client.create_project_view.return_value = {"name": "P"}
        result = runner.invoke(
            cli, ["plan", "project", "view", "create", PROJECT, "-n", "P", "--json"]
        )
        assert result.exit_code == 0, result.output

    def test_views_workspace_and_save(self, runner: CliRunner, auth_client: MagicMock) -> None:
        auth_client.list_workspace_views_with_etag.return_value = (
            {"results": [{"name": "A"}]},
            '"e1"',
        )
        r1 = runner.invoke(cli, ["plan", "views", "workspace", "--json"])
        assert r1.exit_code == 0, r1.output
        auth_client.save_workspace_views.return_value = [{"name": "A"}]
        with runner.isolated_filesystem():
            with open("v.json", "w", encoding="utf-8") as fh:
                fh.write('[{"name": "A", "filters": {}}]')
            r2 = runner.invoke(
                cli,
                ["plan", "views", "workspace", "save", "-f", "v.json", "--if-match", '"e1"', "--json"],
            )
        assert r2.exit_code == 0, r2.output
        auth_client.save_workspace_views.assert_called_once()

    def test_label_crud(self, runner: CliRunner, auth_client: MagicMock) -> None:
        from dailybot_cli.api_client import PaginatedResult

        auth_client.list_plan_labels.return_value = PaginatedResult(
            count=1, next=None, previous=None, results=[{"name": "bug", "uuid": LABEL}]
        )
        r1 = runner.invoke(cli, ["plan", "label", "list", "--json"])
        assert r1.exit_code == 0, r1.output
        auth_client.create_plan_label.return_value = {"name": "bug", "uuid": LABEL}
        r2 = runner.invoke(cli, ["plan", "label", "create", "-n", "bug", "--json"])
        assert r2.exit_code == 0, r2.output
        auth_client.update_tasks_label.return_value = {"name": "bug", "is_archived": True}
        r3 = runner.invoke(cli, ["plan", "label", "update", LABEL, "--archive", "--json"])
        assert r3.exit_code == 0, r3.output
        auth_client.delete_tasks_label.return_value = None
        r4 = runner.invoke(cli, ["plan", "label", "delete", LABEL, "--yes", "--json"])
        assert r4.exit_code == 0, r4.output

    def test_tasks_board(self, runner: CliRunner, auth_client: MagicMock) -> None:
        auth_client.get_tasks_board.return_value = {"groups": [], "total": 0}
        result = runner.invoke(
            cli, ["plan", "tasks", "board", "--group-by", "state", "--owner", "me", "--json"]
        )
        assert result.exit_code == 0, result.output
        auth_client.get_tasks_board.assert_called_once()

    def test_task_brief_still_present(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["plan", "task", "brief", "--help"])
        assert result.exit_code == 0
        assert "brief" in result.output.lower()
