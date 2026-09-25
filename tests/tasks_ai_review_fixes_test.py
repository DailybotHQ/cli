"""Fixes from the AI review of the Tasks PR (round 1).

Each class pins one finding: a bulk dry run the server did not honour, hostile
ETags, the default-port origin comparison, a same-origin download that must
stream under the cap, server text that reached the terminal through `escape()`
alone, and the saved-view refusal that talked about pins.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import ATTACHMENT_MAX_SIZE_BYTES, APIError, DailyBotClient
from dailybot_cli.main import cli

API_URL: str = "https://api.example.com"
BOARD: str = "00000000-0000-0000-0000-000000000001"
PROJECT: str = "00000000-0000-0000-0000-000000000002"
ATT: str = "00000000-0000-0000-0000-000000000009"
CLEAR: str = "\x1b[2J"


def _response(payload: Any = None, status: int = 200, headers: dict[str, str] | None = None) -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = {} if payload is None else payload
    mock.headers = headers or {}
    return mock


def _stream(status: int = 200, headers: dict[str, str] | None = None, chunks: Any = None) -> Any:
    response: MagicMock = MagicMock(spec=httpx.Response)
    response.status_code = status
    response.headers = headers or {}
    response.iter_bytes.return_value = iter(chunks if chunks is not None else [])
    response.read.return_value = b"{}"
    response.json.return_value = {}
    manager: MagicMock = MagicMock()
    manager.__enter__.return_value = response
    manager.__exit__.return_value = False
    return manager


class TestBulkDryRunMustBeAPreview:
    def test_a_bulk_answer_without_dry_run_true_is_not_shown_as_a_preview(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.bulk_tasks.return_value = {"succeeded": 1, "failed": 0, "results": []}
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = CliRunner().invoke(
                cli,
                ["task", "bulk", "--operation", "archive", "-f", "-", "--dry-run", "--json"],
                input='[{"task": "ENG-1"}]',
            )
        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["code"] == "preview_not_honoured"


class TestEtagGrammar:
    @pytest.mark.parametrize("etag", ['"abc"', 'W/"v-2"', '""'])
    def test_a_valid_etag_passes(self, etag: str) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        with patch(
            "dailybot_cli.api_client.httpx.get", return_value=_response([], headers={"ETag": etag})
        ):
            _data, got = client.list_board_views_with_etag(BOARD)
        assert got == etag

    @pytest.mark.parametrize("etag", [f'"a{CLEAR}"', '"a"\n"b"', "unquoted", '"a‮"'])
    def test_a_hostile_server_etag_is_refused(self, etag: str) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                return_value=_response([], headers={"ETag": etag}),
            ),
            pytest.raises(APIError) as caught,
        ):
            client.list_board_views_with_etag(BOARD)
        assert caught.value.code == "invalid_etag"

    def test_a_hostile_if_match_is_refused_before_the_request(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        with (
            patch("dailybot_cli.api_client.httpx.put") as put,
            pytest.raises(APIError) as caught,
        ):
            client.save_project_views(PROJECT, [], if_match='"x"\r\nX-Evil: 1')
        assert caught.value.code == "invalid_etag"
        put.assert_not_called()


class TestDefaultPortsAreTheSameOrigin:
    @pytest.mark.parametrize(
        ("api", "url"),
        [
            ("https://api.example.com", "https://api.example.com:443/v1/x"),
            ("https://api.example.com:443", "https://api.example.com/v1/x"),
            ("http://localhost", "http://localhost:80/v1/x"),
        ],
    )
    def test_explicit_default_port_matches(self, api: str, url: str) -> None:
        assert DailyBotClient(api_url=api, token="t")._is_api_origin(url)

    def test_a_different_port_is_still_foreign(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url="https://api.example.com", token="t")
        assert not client._is_api_origin("https://api.example.com:8443/v1/x")


class TestSameOriginDownloadStreams:
    def test_the_cap_holds_while_streaming_from_the_api(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        produced: list[int] = []

        def endless() -> Any:
            while True:
                produced.append(1)
                yield b"x" * (1024 * 1024)

        body: Any = _stream()
        body.__enter__.return_value.iter_bytes.return_value = endless()
        with (
            patch("dailybot_cli.api_client.httpx.stream", return_value=body) as stream,
            pytest.raises(APIError) as caught,
        ):
            client.download_attachment("ENG-1", ATT)
        assert caught.value.code == "attachment_too_large"
        assert len(produced) <= ATTACHMENT_MAX_SIZE_BYTES // (1024 * 1024) + 1
        sent: dict[str, str] = dict(stream.call_args.kwargs["headers"])
        assert sent.get("Authorization") == "Bearer test-token"

    def test_a_small_file_arrives_whole(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        with patch(
            "dailybot_cli.api_client.httpx.stream", return_value=_stream(chunks=[b"ab", b"c"])
        ):
            assert client.download_attachment("ENG-1", ATT) == b"abc"

    def test_an_api_refusal_surfaces_its_code(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        refused: Any = _stream(status=404)
        refused.__enter__.return_value.json.return_value = {"code": "not_found", "detail": "No."}
        with (
            patch("dailybot_cli.api_client.httpx.stream", return_value=refused),
            pytest.raises(APIError) as caught,
        ):
            client.download_attachment("ENG-1", ATT)
        assert caught.value.status_code == 404


class TestServerTextInActivityFeeds:
    def test_activity_timestamps_are_neutralized(self) -> None:
        from dailybot_cli.api_client import PaginatedResult

        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.list_tasks_activity.return_value = PaginatedResult(
            results=[{"created_at": f"2026-09-25{CLEAR}", "summary": "moved"}],
            count=1,
            next=None,
            previous=None,
        )
        with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
            result = CliRunner().invoke(cli, ["tasks", "activity"])
        assert result.exit_code == 0, result.output
        assert "\x1b" not in result.output


class TestSavedViewRefusalSaysViews:
    @pytest.mark.parametrize("sub", [["get"], ["update", "--name", "x"], ["delete", "--yes"]])
    def test_the_message_is_about_saved_views(self, sub: list[str]) -> None:
        with (
            patch("dailybot_cli.commands._favorites.get_token", return_value=None),
            patch("dailybot_cli.commands.tasks.get_token", return_value=None),
        ):
            result = CliRunner().invoke(cli, ["tasks", "view", sub[0], ATT, *sub[1:]])
        assert result.exit_code == 3
        text: str = " ".join(result.output.split()).lower()
        assert "saved view" in text
        assert "pins" not in text
