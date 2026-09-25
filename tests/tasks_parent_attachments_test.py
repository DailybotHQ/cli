"""Attachments on comments, projects and goals.

The three parents share the task attachment row shape but take multipart only,
so the limit is 5 MiB everywhere and is checked before any request. Reads need
only visibility. Attaching to or deleting from a project or a goal is a
`tasks:admin` door, refused to an API key before any request. On a comment, the
server lets only the comment's author attach.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import ATTACHMENT_MULTIPART_MAX_BYTES, APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    EXIT_PERMISSION_DENIED,
    EXIT_USAGE_ERROR,
)
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"
BASE: str = f"{API_URL}/v1/tasks/"
TASK: str = "ENG-142"
COMMENT: str = "00000000-0000-0000-0000-000000000007"
PROJECT: str = "00000000-0000-0000-0000-000000000002"
GOAL: str = "00000000-0000-0000-0000-000000000003"
ATT: str = "00000000-0000-0000-0000-000000000009"

PARENTS: list[tuple[str, tuple[str, ...], str]] = [
    ("comment", (TASK, COMMENT), f"tasks/{TASK}/comments/{COMMENT}"),
    ("project", (PROJECT,), f"projects/{PROJECT}"),
    ("goal", (GOAL,), f"goals/{GOAL}"),
]


@pytest.fixture
def real() -> DailyBotClient:
    return DailyBotClient(api_url=API_URL, token="test-token")


def _response(payload: Any = None, status: int = 200, content: bytes = b"") -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = {} if payload is None else payload
    mock.headers = {}
    mock.content = content
    return mock


class TestWire:
    @pytest.mark.parametrize(("kind", "ids", "parent"), PARENTS)
    def test_upload_is_one_multipart_post(
        self, real: DailyBotClient, kind: str, ids: tuple[str, ...], parent: str
    ) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": ATT})
        ) as post:
            getattr(real, f"upload_{kind}_attachment")(
                *ids, filename="a.txt", content_type="text/plain", data=b"x", caption="c"
            )
        assert post.call_args.args[0] == f"{BASE}{parent}/attachments/"
        assert post.call_args.kwargs["files"] == {"file": ("a.txt", b"x", "text/plain")}
        assert post.call_args.kwargs["data"] == {"caption": "c"}
        assert "Content-Type" not in post.call_args.kwargs["headers"]

    @pytest.mark.parametrize(("kind", "ids", "parent"), PARENTS)
    def test_list_get_and_delete_reach_the_parent(
        self, real: DailyBotClient, kind: str, ids: tuple[str, ...], parent: str
    ) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response([])) as get:
            getattr(real, f"list_{kind}_attachments")(*ids)
        assert get.call_args.args[0] == f"{BASE}{parent}/attachments/"
        body: MagicMock = MagicMock()
        body.__enter__.return_value = _response()
        body.__enter__.return_value.iter_bytes.return_value = iter([b"bytes"])
        body.__exit__.return_value = False
        with patch("dailybot_cli.api_client.httpx.stream", return_value=body) as stream:
            data: bytes = getattr(real, f"download_{kind}_attachment")(*ids, ATT)
        assert data == b"bytes"
        assert stream.call_args.args == ("GET", f"{BASE}{parent}/attachments/{ATT}/content/")
        with patch(
            "dailybot_cli.api_client.httpx.request", return_value=_response(status=204)
        ) as request:
            getattr(real, f"delete_{kind}_attachment")(*ids, ATT)
        assert request.call_args.args[:2] == ("DELETE", f"{BASE}{parent}/attachments/{ATT}/")

    def test_a_hostile_comment_id_is_refused(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.get") as get, pytest.raises(APIError):
            real.list_comment_attachments(TASK, "../../boards/x")
        get.assert_not_called()


def _invoke(module: str, argv: list[str], client: Any, *, person: bool = True) -> Any:
    with (
        patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
        patch("dailybot_cli.commands.project.get_token", return_value="tok" if person else None),
    ):
        return CliRunner().invoke(cli, argv)


class TestCommands:
    def test_comment_attach_sends_the_file_and_caption(self, tmp_path: Path) -> None:
        source: Path = tmp_path / "trace.txt"
        source.write_bytes(b"trace")
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.upload_comment_attachment.return_value = {"uuid": ATT}
        argv: list[str] = [
            "task",
            "comment-attach",
            TASK,
            COMMENT,
            str(source),
            "--caption",
            "c",
            "--json",
        ]
        result = _invoke("task", argv, client)
        assert result.exit_code == 0, result.output
        args, kwargs = client.upload_comment_attachment.call_args
        assert args == (TASK, COMMENT)
        assert kwargs["data"] == b"trace" and kwargs["caption"] == "c"

    @pytest.mark.parametrize(
        "argv",
        [
            ["task", "comment-attach", TASK, COMMENT],
            ["project", "attach", PROJECT],
            ["goal", "attach", GOAL],
        ],
    )
    def test_over_5_mib_is_refused_before_any_request(
        self, tmp_path: Path, argv: list[str]
    ) -> None:
        big: Path = tmp_path / "big.bin"
        big.write_bytes(b"x" * (ATTACHMENT_MULTIPART_MAX_BYTES + 1))
        client: MagicMock = MagicMock(spec=DailyBotClient)
        result = _invoke(argv[0], [*argv, str(big)], client)
        assert result.exit_code == EXIT_USAGE_ERROR
        assert "5 MiB" in result.output
        assert client.mock_calls == []

    @pytest.mark.parametrize(
        "argv",
        [
            ["project", "attach", PROJECT, __file__],
            ["goal", "attach", GOAL, __file__],
            ["project", "attachment", "delete", PROJECT, ATT, "--yes"],
            ["goal", "attachment", "delete", GOAL, ATT, "--yes"],
        ],
    )
    def test_admin_doors_refuse_a_key(self, argv: list[str]) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        result = _invoke(argv[0], [*argv, "--json"], client, person=False)
        assert result.exit_code == EXIT_PERMISSION_DENIED, result.output
        assert json.loads(result.output)["code"] == "insufficient_scope"
        assert client.mock_calls == []

    @pytest.mark.parametrize(
        ("argv", "method"),
        [
            (["project", "attachments", PROJECT], "list_project_attachments"),
            (["goal", "attachments", GOAL], "list_goal_attachments"),
            (["task", "comment-attachments", TASK, COMMENT], "list_comment_attachments"),
        ],
    )
    def test_reads_work_with_a_key(self, argv: list[str], method: str) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        getattr(client, method).return_value = [{"uuid": ATT, "filename": "a.txt"}]
        result = _invoke(argv[0], [*argv, "--json"], client, person=False)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)[0]["uuid"] == ATT

    def test_a_delete_dry_run_sends_nothing(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        argv: list[str] = [
            "task",
            "comment-attachment",
            "delete",
            TASK,
            COMMENT,
            ATT,
            "--dry-run",
            "--json",
        ]
        result = _invoke("task", argv, client)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["previewed_by"] == "client"
        assert client.mock_calls == []

    def test_the_servers_size_refusal_exits_usage(self, tmp_path: Path) -> None:
        source: Path = tmp_path / "a.txt"
        source.write_bytes(b"x")
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.upload_goal_attachment.side_effect = APIError(
            400,
            "Too large.",
            code="attachment_too_large",
            extra={"max_size_bytes": ATTACHMENT_MULTIPART_MAX_BYTES},
        )
        result = _invoke("goal", ["goal", "attach", GOAL, str(source), "--json"], client)
        assert result.exit_code == EXIT_USAGE_ERROR
        assert json.loads(result.output)["code"] == "attachment_too_large"

    def test_a_downloaded_file_is_never_overwritten_silently(self, tmp_path: Path) -> None:
        existing: Path = tmp_path / "plan.pdf"
        existing.write_bytes(b"mine")
        client: MagicMock = MagicMock(spec=DailyBotClient)
        argv: list[str] = ["project", "attachment", "get", PROJECT, ATT, "-o", str(existing)]
        result = _invoke("project", argv, client)
        assert result.exit_code == EXIT_USAGE_ERROR
        assert existing.read_bytes() == b"mine"
        client.download_project_attachment.assert_not_called()
