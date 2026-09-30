"""Milestone attachments and project updates: detail, edit, delete, attachments.

Every HTTP call is mocked (``AGENTS.md`` rule 7).
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import (
    ATTACHMENT_RENAME_FIELD,
    TASKS_AGENT_NAME_HEADER,
    APIError,
    DailyBotClient,
)
from dailybot_cli.main import cli

API: str = "http://test-api.example.com"
P: str = "00000000-0000-0000-0000-000000000002"
M: str = "00000000-0000-0000-0000-000000000031"
U: str = "00000000-0000-0000-0000-000000000041"
A: str = "00000000-0000-0000-0000-000000000051"


def _response(payload: Any = None, status: int = 200) -> MagicMock:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = {} if payload is None else payload
    mock.headers = {}
    return mock


def _client(agent: str | None = None) -> DailyBotClient:
    return DailyBotClient(api_url=API, token="t", agent_name=agent)


class TestWire:
    def test_milestone_attachment_paths(self) -> None:
        with patch("httpx.get", return_value=_response({"results": []})) as get:
            _client().list_milestone_attachments(P, M)
        assert get.call_args.args[0] == f"{API}/v1/plan/projects/{P}/milestones/{M}/attachments/"

    def test_milestone_upload_is_multipart_and_stamped(self) -> None:
        with patch("httpx.post", return_value=_response({"uuid": A}, 201)) as post:
            _client("Claude Code").upload_milestone_attachment(
                P, M, filename="spec.pdf", content_type="application/pdf", data=b"x"
            )
        assert post.call_args.args[0].endswith(f"/projects/{P}/milestones/{M}/attachments/")
        assert "files" in post.call_args.kwargs
        assert post.call_args.kwargs["headers"][TASKS_AGENT_NAME_HEADER] == "Claude Code"

    def test_rename_sends_filename(self) -> None:
        with patch("httpx.patch", return_value=_response({"uuid": A})) as patch_call:
            _client().rename_update_attachment(P, U, A, filename="chart.png")
        assert patch_call.call_args.args[0].endswith(f"/projects/{P}/updates/{U}/attachments/{A}/")
        assert patch_call.call_args.kwargs["json"] == {ATTACHMENT_RENAME_FIELD: "chart.png"}
        assert ATTACHMENT_RENAME_FIELD == "filename"

    def test_update_detail_edit_delete(self) -> None:
        with patch("httpx.get", return_value=_response({"uuid": U})) as get:
            _client().get_project_update(P, U)
        assert get.call_args.args[0] == f"{API}/v1/plan/projects/{P}/updates/{U}/"
        with patch("httpx.patch", return_value=_response({"uuid": U})) as patch_call:
            _client("Claude Code").edit_project_update(P, U, health="at_risk")
        body: dict[str, Any] = patch_call.call_args.kwargs["json"]
        assert body == {"health": "at_risk", "agent_name": "Claude Code"}
        with patch("httpx.request", return_value=_response(status=204)) as req:
            _client().delete_project_update(P, U)
        assert req.call_args.args[:2] == ("DELETE", f"{API}/v1/plan/projects/{P}/updates/{U}/")


def _invoke(argv: list[str], client: MagicMock) -> Any:
    with patch("dailybot_cli.commands.project.require_auth", return_value=client):
        return CliRunner().invoke(cli, argv)


class TestMilestoneRestore:
    def test_restore_posts_to_the_restore_door(self) -> None:
        with patch("httpx.post", return_value=_response({"uuid": M, "is_archived": False})) as post:
            _client().restore_milestone(P, M)
        assert post.call_args.args[0] == f"{API}/v1/plan/projects/{P}/milestones/{M}/restore/"


class TestCommands:
    def test_update_edit_needs_a_field(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        result = _invoke(["project", "update-edit", P, U], client)
        assert result.exit_code == 2
        client.edit_project_update.assert_not_called()

    def test_update_edit_by_a_non_author_names_the_rule(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.edit_project_update.side_effect = APIError(403, "no", code="update_not_author")
        result = _invoke(["project", "update-edit", P, U, "new", "--json"], client)
        assert result.exit_code == 4
        assert "Only the person who posted" in json.loads(result.output)["message"]

    def test_rename_refuses_an_empty_or_long_name_locally(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        for name in ("   ", "x" * 256):
            result = _invoke(["project", "update-attachment", "rename", P, U, A, name], client)
            assert result.exit_code == 2
        client.rename_update_attachment.assert_not_called()

    def test_delete_dry_run_sends_nothing(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        result = _invoke(["project", "update-delete", P, U, "--dry-run"], client)
        assert result.exit_code == 0
        client.delete_project_update.assert_not_called()

    def test_delete_success_says_the_update_was_deleted(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        result = _invoke(["project", "update-delete", P, U, "--yes"], client)
        assert result.exit_code == 0, result.output
        client.delete_project_update.assert_called_once_with(P, U)
        assert "Project update deleted." in result.output
        assert "Attachment" not in result.output
        result = _invoke(["project", "update-delete", P, U, "--yes", "--json"], client)
        assert json.loads(result.output) == {"deleted": True, "project": P, "update": U}

    def test_milestone_attach_uploads(self, tmp_path: Path) -> None:
        f: Path = tmp_path / "spec.txt"
        f.write_text("x")
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.upload_milestone_attachment.return_value = {"uuid": A, "filename": "spec.txt"}
        result = _invoke(["project", "milestone-attach", P, M, str(f), "--json"], client)
        assert result.exit_code == 0, result.output
        assert client.upload_milestone_attachment.call_args.args == (P, M)


class TestFileCountFallback:
    def test_feed_rows_with_only_a_count_still_show_files(self) -> None:
        from dailybot_cli.display import console, print_project_updates

        with console.capture() as cap:
            print_project_updates([{"uuid": U, "body": "x", "attachment_count": 2}])
        assert "2 file(s)" in cap.get()


class TestRendering:
    @pytest.mark.parametrize("argv", [["project", "updates", P], ["project", "update-get", P, U]])
    def test_person_via_agent_health_edited_files(self, argv: list[str]) -> None:
        row: dict[str, Any] = {
            "uuid": U,
            "created_by": {"name": "Jane Doe"},
            "executed_by_agent": {"name": "Claude Code"},
            "health": "on_track",
            "edited_at": "2026-09-29T18:00:00Z",
            "attachments": [{"uuid": A}],
            "body": "Shipped the fix",
            "created_at": "2026-09-29T17:00:00Z",
        }
        client: MagicMock = MagicMock(spec=DailyBotClient)
        from dailybot_cli.api_client import PaginatedResult

        client.list_project_updates.return_value = PaginatedResult(results=[row], count=1)
        client.get_project_update.return_value = row
        result = _invoke(argv, client)
        flat: str = " ".join(result.output.split())
        assert '"Jane Doe" via "Claude Code"' in flat
        assert "on_track" in flat and "edited" in flat and "1 file(s)" in flat
