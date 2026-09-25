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


class TestBoardMemberAddTakesATeam:
    """Contract 2576eceb4: board member add takes exactly one of user_uuid / team_uuid."""

    TEAM: str = "00000000-0000-0000-0000-000000000011"
    USER: str = "00000000-0000-0000-0000-000000000004"

    def _run(self, argv: list[str]) -> tuple[Any, MagicMock]:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.add_board_member.return_value = {"subject_type": "team"}
        with (
            patch("dailybot_cli.commands.board.require_auth", return_value=client),
            patch("dailybot_cli.commands.board.get_token", return_value="tok"),
        ):
            result = CliRunner().invoke(cli, ["board", "member", "add", BOARD, *argv, "--json"])
        return result, client

    def test_a_team_is_sent_as_team_uuid(self) -> None:
        result, client = self._run(["--team", self.TEAM])
        assert result.exit_code == 0, result.output
        assert client.add_board_member.call_args.kwargs["team_uuid"] == self.TEAM
        assert client.add_board_member.call_args.args[1] is None

    def test_a_user_still_works_positionally(self) -> None:
        result, client = self._run([self.USER])
        assert result.exit_code == 0, result.output
        assert client.add_board_member.call_args.args[1] == self.USER

    @pytest.mark.parametrize("argv", [[], ["u-1", "--team", "t-1"]])
    def test_exactly_one_is_required(self, argv: list[str]) -> None:
        result, client = self._run(argv)
        assert result.exit_code == 2
        client.add_board_member.assert_not_called()

    def test_the_wire_body_carries_only_the_team(self) -> None:
        real: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": "m"})
        ) as post:
            real.add_board_member(BOARD, None, team_uuid=self.TEAM)
        assert post.call_args.kwargs["json"] == {"team_uuid": self.TEAM}


class TestConfirmPromptIsNeutralized:
    def test_the_prompt_text_carries_no_control_characters(self) -> None:
        import click as _click

        from dailybot_cli.commands._destructive import confirm_without_preview

        with patch.object(_click, "confirm", return_value=True) as confirm:
            confirm_without_preview(f"delete comment ENG-1{CLEAR}‮", assume_yes=False, dry_run=False)
        prompt: str = confirm.call_args.args[0]
        assert "\x1b" not in prompt and "‮" not in prompt


class TestViewSavePreconditionExits:
    @pytest.mark.parametrize(("status", "exit_code"), [(412, 4), (428, 2)])
    def test_if_match_refusals_have_documented_exits(self, status: int, exit_code: int) -> None:
        from dailybot_cli.commands.public_api_helpers import tasks_write_exit_code

        assert tasks_write_exit_code(APIError(status, "x", code="precondition_failed")) == exit_code


class TestRawUploadContentType:
    def test_a_raw_body_never_keeps_the_json_content_type(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response()) as put:
            client._request("PUT", f"{API_URL}/v1/tasks/x/", content=b"\x00\x01")
        headers: dict[str, str] = dict(put.call_args.kwargs["headers"])
        assert headers.get("Content-Type") != "application/json"


class TestApiDownloadAsksForIdentity:
    def test_the_api_stream_requests_an_uncompressed_body(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        with patch(
            "dailybot_cli.api_client.httpx.stream", return_value=_stream(chunks=[b"x"])
        ) as stream:
            client.download_attachment("ENG-1", ATT)
        assert dict(stream.call_args.kwargs["headers"]).get("Accept-Encoding") == "identity"


class TestBoardPinsResolveKeys:
    def test_unstar_by_board_key_finds_the_pin_by_uuid(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.get_board.return_value = {"uuid": BOARD, "key": "ENG"}
        client.list_favorites.return_value = [
            {"uuid": "f-1", "target_type": "board", "target_uuid": BOARD}
        ]
        with (
            patch("dailybot_cli.commands.board.require_auth", return_value=client),
            patch("dailybot_cli.commands._favorites.get_token", return_value="tok"),
        ):
            result = CliRunner().invoke(cli, ["board", "unstar", "ENG", "--json"])
        assert result.exit_code == 0, result.output
        client.delete_favorite.assert_called_once_with("f-1")

    def test_star_by_board_key_sends_the_uuid(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.get_board.return_value = {"uuid": BOARD, "key": "ENG"}
        client.add_favorite.return_value = {"uuid": "f-1", "rank": 1}
        with (
            patch("dailybot_cli.commands.board.require_auth", return_value=client),
            patch("dailybot_cli.commands._favorites.get_token", return_value="tok"),
        ):
            result = CliRunner().invoke(cli, ["board", "star", "ENG", "--json"])
        assert result.exit_code == 0, result.output
        assert client.add_favorite.call_args.kwargs["target_uuid"] == BOARD

    def test_a_uuid_is_not_resolved(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.add_favorite.return_value = {"uuid": "f-1", "rank": 1}
        with (
            patch("dailybot_cli.commands.board.require_auth", return_value=client),
            patch("dailybot_cli.commands._favorites.get_token", return_value="tok"),
        ):
            CliRunner().invoke(cli, ["board", "star", BOARD, "--json"])
        client.get_board.assert_not_called()


class TestRetryKeepsTheRawContentType:
    def test_the_alt_credential_retry_does_not_reintroduce_json(self) -> None:
        client: DailyBotClient = DailyBotClient(
            api_url=API_URL, token="test-token", api_key="test-key"
        )
        with patch(
            "dailybot_cli.api_client.httpx.put",
            side_effect=[_response(status=401), _response()],
        ) as put:
            client._request("PUT", f"{API_URL}/v1/tasks/x/", content=b"\x00\x01")
        assert put.call_count == 2
        for call in put.call_args_list:
            assert dict(call.kwargs["headers"]).get("Content-Type") != "application/json"


class TestRound3:
    """AI review round 3 on 248c200."""

    def test_a_path_prefixed_api_still_treats_tasks_doors_as_tasks(self) -> None:
        client: DailyBotClient = DailyBotClient(
            api_url="https://gw.example.com/gateway", token="test-token", api_key="test-key"
        )
        with (
            patch(
                "dailybot_cli.api_client.httpx.post",
                return_value=_response({"code": "permission_denied"}, status=403),
            ) as post,
            pytest.raises(APIError),
        ):
            client.restore_task("ENG-1")
        assert post.call_count == 1

    def test_a_same_origin_upload_accepts_an_empty_2xx(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        empty: Any = _response(status=200)
        empty.json.side_effect = ValueError("no body")
        empty.text = ""
        presign: dict[str, Any] = {
            "upload_url": f"{API_URL}/v1/tasks/tasks/ENG-1/attachments/{ATT}/content/",
            "method": "PUT",
        }
        with patch("dailybot_cli.api_client.httpx.put", return_value=empty):
            assert client.upload_attachment_bytes(presign, b"x") == {}

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("DELETE", f"/v1/tasks/tasks/ENG-1/attachments/{ATT}/content/"),
            ("PUT", "/v1/tasks/boards/b-1/archive/"),
            ("POST", "/v1/cli/logout/"),
        ],
    )
    def test_a_same_origin_upload_target_is_allowlisted(self, method: str, path: str) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        presign: dict[str, Any] = {"upload_url": f"{API_URL}{path}", "method": method}
        with (
            patch("dailybot_cli.api_client.httpx.request") as request,
            patch("dailybot_cli.api_client.httpx.put") as put,
            patch("dailybot_cli.api_client.httpx.post") as post,
            pytest.raises(APIError) as caught,
        ):
            client.upload_attachment_bytes(presign, b"x")
        assert caught.value.code == "attachment_upload_target_refused"
        for mock in (request, put, post):
            mock.assert_not_called()

    def test_the_api_download_has_a_wall_clock_deadline(self) -> None:
        from dailybot_cli.api_client import ATTACHMENT_DOWNLOAD_DEADLINE_SECS, TransportError

        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        clock: list[float] = [0.0]

        def tick() -> float:
            clock[0] += ATTACHMENT_DOWNLOAD_DEADLINE_SECS
            return clock[0]

        with (
            patch(
                "dailybot_cli.api_client.httpx.stream",
                return_value=_stream(chunks=[b"a", b"b", b"c"]),
            ),
            patch("dailybot_cli.api_client.time.monotonic", side_effect=tick),
            pytest.raises(TransportError),
        ):
            client.download_attachment("ENG-1", ATT)

    def test_force_never_writes_through_a_symlink(self, tmp_path: Any) -> None:
        from dailybot_cli.commands._attachments import write_download

        victim: Any = tmp_path / "victim.txt"
        victim.write_text("keep me")
        link: Any = tmp_path / "out.bin"
        link.symlink_to(victim)
        with (
            patch("dailybot_cli.commands._attachments.os.O_NOFOLLOW", 0, create=True),
            pytest.raises((SystemExit, Exception)),
        ):
            write_download(link, b"evil", force=True, json_mode=True)
        assert victim.read_text() == "keep me"

    def test_replies_are_grouped_under_their_root(self) -> None:
        from rich.console import Console

        from dailybot_cli import display

        buffer: Console = Console(record=True, width=200, color_system=None)
        comments: list[dict[str, Any]] = [
            {"uuid": "c-1", "author": {"full_name": "A"}, "body": "root one"},
            {"uuid": "c-2", "author": {"full_name": "B"}, "body": "root two"},
            {
                "uuid": "c-3",
                "author": {"full_name": "C"},
                "body": "reply to one",
                "parent_comment": "c-1",
            },
        ]
        with patch.object(display, "console", buffer):
            display.print_task_comments(comments)
        text: str = buffer.export_text()
        assert text.index("root one") < text.index("reply to one") < text.index("root two")


class TestRound4:
    def test_a_same_origin_upload_redirect_is_refused(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        presign: dict[str, Any] = {
            "upload_url": f"{API_URL}/v1/tasks/tasks/ENG-1/attachments/{ATT}/content/",
            "method": "PUT",
        }
        moved: Any = _response({}, status=302, headers={"Location": "https://elsewhere.example/"})
        with (
            patch("dailybot_cli.api_client.httpx.put", return_value=moved),
            pytest.raises(APIError) as caught,
        ):
            client.upload_attachment_bytes(presign, b"x")
        assert caught.value.code == "attachment_upload_redirected"


class TestBoardCreateRequirements:
    """The merged contract: POST boards/ needs name, project and key."""

    PROJECT: str = "00000000-0000-0000-0000-000000000002"

    def _run(self, argv: list[str]) -> tuple[Any, MagicMock]:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.create_board.return_value = {"uuid": BOARD, "key": "DSN", "name": "Design"}
        with (
            patch("dailybot_cli.commands.board.require_auth", return_value=client),
            patch("dailybot_cli.commands.board.get_token", return_value="tok"),
        ):
            result = CliRunner().invoke(cli, ["board", "create", *argv, "--json"])
        return result, client

    def test_name_project_and_key_are_sent(self) -> None:
        result, client = self._run(["-n", "Design", "--project", self.PROJECT, "--key", "DSN"])
        assert result.exit_code == 0, result.output
        kwargs: dict[str, Any] = client.create_board.call_args.kwargs
        assert (kwargs["name"], kwargs["project"], kwargs["key"]) == (
            "Design",
            self.PROJECT,
            "DSN",
        )

    @pytest.mark.parametrize(
        "argv", [["-n", "Design", "--key", "DSN"], ["-n", "Design", "--project", PROJECT]]
    )
    def test_a_missing_requirement_is_refused_locally(self, argv: list[str]) -> None:
        result, client = self._run(argv)
        assert result.exit_code == 2
        client.create_board.assert_not_called()

    def test_the_wire_body(self) -> None:
        real: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": BOARD})
        ) as post:
            real.create_board(name="Design", project=self.PROJECT, key="DSN")
        body: dict[str, Any] = post.call_args.kwargs["json"]
        assert body == {"name": "Design", "project": self.PROJECT, "key": "DSN"}
