"""Attachments on boards: the same row shape and doors as projects, plus rename."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import DailyBotClient
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"
BASE: str = f"{API_URL}/v1/plan/"
BOARD: str = "00000000-0000-0000-0000-000000000004"
ATT: str = "00000000-0000-0000-0000-000000000009"
PARENT: str = f"boards/{BOARD}"


def _response(payload: Any = None, status: int = 200) -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = {} if payload is None else payload
    mock.headers = {}
    mock.content = b""
    return mock


@pytest.fixture
def real() -> DailyBotClient:
    return DailyBotClient(api_url=API_URL, token="test-token")


class TestWire:
    def test_upload_is_one_multipart_post(self, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": ATT})
        ) as post:
            real.upload_board_attachment(
                BOARD, filename="a.txt", content_type="text/plain", data=b"x", caption="c"
            )
        assert post.call_args.args[0] == f"{BASE}{PARENT}/attachments/"
        assert post.call_args.kwargs["files"] == {"file": ("a.txt", b"x", "text/plain")}

    def test_list_delete_and_rename_reach_the_board(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response([])) as get:
            real.list_board_attachments(BOARD)
        assert get.call_args.args[0] == f"{BASE}{PARENT}/attachments/"
        with patch(
            "dailybot_cli.api_client.httpx.request", return_value=_response(status=204)
        ) as request:
            real.delete_board_attachment(BOARD, ATT)
        assert request.call_args.args[:2] == ("DELETE", f"{BASE}{PARENT}/attachments/{ATT}/")
        with patch(
            "dailybot_cli.api_client.httpx.patch", return_value=_response({"uuid": ATT})
        ) as patched:
            real.rename_board_attachment(BOARD, ATT, filename="b.txt")
        assert patched.call_args.args[0] == f"{BASE}{PARENT}/attachments/{ATT}/"
        assert patched.call_args.kwargs["json"] == {"filename": "b.txt"}

    def test_download_streams_the_content_door(self, real: DailyBotClient) -> None:
        body: MagicMock = MagicMock()
        body.__enter__.return_value = _response()
        body.__enter__.return_value.iter_bytes.return_value = iter([b"bytes"])
        body.__exit__.return_value = False
        with patch("dailybot_cli.api_client.httpx.stream", return_value=body) as stream:
            assert real.download_board_attachment(BOARD, ATT) == b"bytes"
        assert stream.call_args.args == ("GET", f"{BASE}{PARENT}/attachments/{ATT}/content/")


def _invoke(argv: list[str], client: Any) -> Any:
    with (
        patch("dailybot_cli.commands.board.require_auth", return_value=client),
        patch("dailybot_cli.commands.board.get_person_token", return_value="tok", create=True),
    ):
        return CliRunner().invoke(cli, ["plan", "board", *argv])


class TestCommands:
    def test_attach_sends_the_file_and_caption(self, tmp_path: Path) -> None:
        source: Path = tmp_path / "spec.txt"
        source.write_bytes(b"spec")
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.upload_board_attachment.return_value = {"uuid": ATT}
        result = _invoke(["attach", BOARD, str(source), "--caption", "c", "--json"], client)
        assert result.exit_code == 0, result.output
        args, kwargs = client.upload_board_attachment.call_args
        assert args == (BOARD,) and kwargs["data"] == b"spec" and kwargs["caption"] == "c"

    def test_attachments_lists(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.list_board_attachments.return_value = []
        result = _invoke(["attachments", BOARD, "--json"], client)
        assert result.exit_code == 0, result.output
        client.list_board_attachments.assert_called_once_with(BOARD)

    def test_get_downloads_and_never_overwrites(self, tmp_path: Path) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.download_board_attachment.return_value = b"data"
        out: Path = tmp_path / "out.bin"
        assert _invoke(["attachment", "get", BOARD, ATT, "-o", str(out)], client).exit_code == 0
        assert out.read_bytes() == b"data"
        assert _invoke(["attachment", "get", BOARD, ATT, "-o", str(out)], client).exit_code != 0

    def test_rename_sends_the_new_name(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.rename_board_attachment.return_value = {"uuid": ATT, "filename": "b.txt"}
        result = _invoke(["attachment", "rename", BOARD, ATT, "b.txt", "--json"], client)
        assert result.exit_code == 0, result.output
        client.rename_board_attachment.assert_called_once_with(BOARD, ATT, filename="b.txt")

    def test_delete_previews_then_needs_consent(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        result = _invoke(["attachment", "delete", BOARD, ATT, "--dry-run"], client)
        assert result.exit_code == 0, result.output
        client.delete_board_attachment.assert_not_called()
        client.delete_board_attachment.return_value = None
        assert _invoke(["attachment", "delete", BOARD, ATT, "--yes"], client).exit_code == 0
        client.delete_board_attachment.assert_called_once_with(BOARD, ATT)
