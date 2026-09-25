"""Task attachments: attach, list, get, delete.

The upload is three calls — presign, send the bytes to the returned target,
confirm — hidden behind one command. The target may be object storage on a
foreign host, so the security properties are pinned here:

* Dailybot credentials (`Authorization`, `X-API-KEY`) are never sent to a host
  other than the configured API origin; only the presign's own headers go there;
* the upload never follows a redirect (a 3xx is an error, and nothing is re-sent);
* a foreign target must be https unless the API itself is plain http (local dev);
* the size cap is enforced before any request, and `-o` never overwrites silently.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import (
    ATTACHMENT_DOWNLOAD_DEADLINE_SECS,
    ATTACHMENT_MAX_SIZE_BYTES,
    ATTACHMENT_MULTIPART_MAX_BYTES,
    APIError,
    DailyBotClient,
    TransportError,
)
from dailybot_cli.commands.public_api_helpers import (
    ERROR_CODE_MESSAGES,
    EXIT_NOT_FOUND,
    EXIT_USAGE_ERROR,
    TASKS_ERROR_CODES,
)
from dailybot_cli.main import cli

API_URL: str = "https://api.example.com"
BASE: str = f"{API_URL}/v1/tasks/tasks/"
TASK: str = "ENG-142"
ATT: str = "a-1"
STORAGE_URL: str = "https://storage.example-bucket.com/uploads/a-1?sig=abc"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def real() -> DailyBotClient:
    return DailyBotClient(api_url=API_URL, token="test-token", api_key="test-key")


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


def _response(
    payload: Any = None,
    status: int = 200,
    headers: dict[str, str] | None = None,
    content: bytes = b"",
) -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = {} if payload is None else payload
    mock.headers = headers or {}
    mock.content = content
    return mock


def _stream(
    status: int = 200,
    headers: dict[str, str] | None = None,
    chunks: list[bytes] | None = None,
) -> Any:
    """A context manager standing in for `httpx.stream(...)` on the storage hop."""
    response: MagicMock = MagicMock(spec=httpx.Response)
    response.status_code = status
    response.headers = headers or {}
    response.iter_bytes.return_value = iter(chunks if chunks is not None else [])
    manager: MagicMock = MagicMock()
    manager.__enter__.return_value = response
    manager.__exit__.return_value = False
    return manager


def _presign(upload_url: str = STORAGE_URL) -> dict[str, Any]:
    return {
        "upload_url": upload_url,
        "method": "PUT",
        "headers": {"Content-Type": "text/plain"},
        "expires_in": 300,
        "attachment": {"uuid": ATT, "status": "pending"},
    }


def _invoke(runner: CliRunner, client: Any, args: list[str]) -> Any:
    with patch("dailybot_cli.commands.task.require_auth", return_value=client):
        return runner.invoke(cli, args)


# ---------------------------------------------------------------------------
# Transport security
# ---------------------------------------------------------------------------


class TestUploadNeverLeaksCredentials:
    def test_a_foreign_target_gets_only_the_presign_headers(self, real: DailyBotClient) -> None:
        with (
            patch("dailybot_cli.api_client.httpx.request", return_value=_response()) as request,
            patch("dailybot_cli.api_client.httpx.put") as put,
        ):
            real.upload_attachment_bytes(_presign(), b"hello")
        put.assert_not_called()
        call: Any = request.call_args
        assert call.args[:2] == ("PUT", STORAGE_URL)
        assert call.kwargs["headers"] == {"Content-Type": "text/plain"}
        assert call.kwargs["content"] == b"hello"
        assert call.kwargs["follow_redirects"] is False
        sent: str = json.dumps(call.kwargs["headers"]).lower()
        assert "authorization" not in sent and "x-api-key" not in sent

    def test_a_redirect_is_refused_and_nothing_is_resent(self, real: DailyBotClient) -> None:
        redirect: Any = _response(status=302, headers={"Location": "https://evil.example.com/"})
        with (
            patch("dailybot_cli.api_client.httpx.request", return_value=redirect) as request,
            pytest.raises(APIError) as caught,
        ):
            real.upload_attachment_bytes(_presign(), b"hello")
        assert caught.value.code == "attachment_upload_redirected"
        assert request.call_count == 1

    def test_a_plain_http_foreign_target_is_refused_before_sending(
        self, real: DailyBotClient
    ) -> None:
        with (
            patch("dailybot_cli.api_client.httpx.request") as request,
            pytest.raises(APIError) as caught,
        ):
            real.upload_attachment_bytes(_presign("http://storage.example.com/x"), b"x")
        assert caught.value.code == "attachment_upload_target_refused"
        request.assert_not_called()

    def test_plain_http_is_allowed_when_the_api_itself_is_local_http(self) -> None:
        local: DailyBotClient = DailyBotClient(api_url="http://localhost:8000", token="t")
        with patch("dailybot_cli.api_client.httpx.request", return_value=_response()) as request:
            local.upload_attachment_bytes(_presign("http://localhost:9000/bucket/x"), b"x")
        assert request.call_count == 1

    def test_the_same_origin_fallback_is_authenticated(self, real: DailyBotClient) -> None:
        fallback: str = f"{BASE}{TASK}/attachments/{ATT}/content/"
        with (
            patch("dailybot_cli.api_client.httpx.put", return_value=_response({})) as put,
            patch("dailybot_cli.api_client.httpx.request") as request,
        ):
            real.upload_attachment_bytes(_presign(fallback), b"hello")
        request.assert_not_called()
        headers: dict[str, str] = put.call_args.kwargs["headers"]
        assert "Authorization" in headers or "X-API-KEY" in headers
        assert headers["Content-Type"] == "text/plain"
        assert put.call_args.kwargs["content"] == b"hello"

    def test_a_relative_target_is_the_api_origin(self, real: DailyBotClient) -> None:
        relative: str = f"/v1/tasks/tasks/{TASK}/attachments/{ATT}/content/"
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response({})) as put:
            real.upload_attachment_bytes(_presign(relative), b"x")
        assert put.call_args.args[0] == f"{API_URL}{relative}"

    def test_a_lookalike_host_is_foreign(self, real: DailyBotClient) -> None:
        lookalike: str = "https://api.example.com.evil.example/x"
        with (
            patch("dailybot_cli.api_client.httpx.request", return_value=_response()) as request,
            patch("dailybot_cli.api_client.httpx.put") as put,
        ):
            real.upload_attachment_bytes(_presign(lookalike), b"x")
        put.assert_not_called()
        assert "Authorization" not in request.call_args.kwargs["headers"]


class TestDownload:
    def test_a_direct_answer_returns_the_bytes(self, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.get", return_value=_response(content=b"data")
        ) as get:
            data: bytes = real.download_attachment(TASK, ATT)
        assert data == b"data"
        assert get.call_args.args[0] == f"{BASE}{TASK}/attachments/{ATT}/content/"

    def test_a_redirect_to_storage_is_followed_once_without_credentials(
        self, real: DailyBotClient
    ) -> None:
        first: Any = _response(status=302, headers={"Location": STORAGE_URL})
        second: Any = _stream(chunks=[b"from ", b"storage"])
        with (
            patch("dailybot_cli.api_client.httpx.get", return_value=first),
            patch("dailybot_cli.api_client.httpx.stream", return_value=second) as stream,
        ):
            data: bytes = real.download_attachment(TASK, ATT)
        assert data == b"from storage"
        storage_call: Any = stream.call_args
        assert storage_call.args == ("GET", STORAGE_URL)
        sent: dict[str, str] = dict(storage_call.kwargs.get("headers") or {})
        assert "Authorization" not in sent and "X-API-KEY" not in sent
        assert sent.get("Accept-Encoding") == "identity"
        assert storage_call.kwargs["follow_redirects"] is False

    def test_a_second_redirect_is_refused(self, real: DailyBotClient) -> None:
        first: Any = _response(status=302, headers={"Location": STORAGE_URL})
        second: Any = _stream(status=302, headers={"Location": "https://elsewhere.example/"})
        with (
            patch("dailybot_cli.api_client.httpx.get", return_value=first),
            patch("dailybot_cli.api_client.httpx.stream", return_value=second),
            pytest.raises(APIError) as caught,
        ):
            real.download_attachment(TASK, ATT)
        assert caught.value.code == "attachment_download_redirected"


class TestWire:
    def test_presign(self, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response(_presign(), 201)
        ) as post:
            real.presign_attachment(TASK, filename="a.txt", content_type="text/plain", size=5)
        assert post.call_args.args[0] == f"{BASE}{TASK}/attachments/presign/"
        assert post.call_args.kwargs["json"] == {
            "filename": "a.txt",
            "content_type": "text/plain",
            "size": 5,
        }

    def test_confirm(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({})) as post:
            real.confirm_attachment(TASK, ATT)
        assert post.call_args.args[0] == f"{BASE}{TASK}/attachments/{ATT}/confirm/"

    def test_multipart_sends_the_file_and_caption_without_a_json_content_type(
        self, real: DailyBotClient
    ) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({}, 201)) as post:
            real.upload_attachment_multipart(
                TASK, filename="a.txt", content_type="text/plain", data=b"x", caption="notes"
            )
        kwargs: dict[str, Any] = post.call_args.kwargs
        assert post.call_args.args[0] == f"{BASE}{TASK}/attachments/"
        assert kwargs["files"] == {"file": ("a.txt", b"x", "text/plain")}
        assert kwargs["data"] == {"caption": "notes"}
        assert "Content-Type" not in kwargs["headers"]

    def test_list_and_delete(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response([])) as get:
            real.list_task_attachments(TASK)
        assert get.call_args.args[0] == f"{BASE}{TASK}/attachments/"
        with patch(
            "dailybot_cli.api_client.httpx.request", return_value=_response(status=204)
        ) as request:
            real.delete_task_attachment(TASK, ATT)
        assert request.call_args.args[:2] == ("DELETE", f"{BASE}{TASK}/attachments/{ATT}/")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


class TestAttach:
    def test_the_three_calls_run_in_order(
        self, runner: CliRunner, client: MagicMock, tmp_path: Path
    ) -> None:
        path: Path = tmp_path / "notes.txt"
        path.write_bytes(b"hello")
        client.presign_attachment.return_value = _presign()
        client.upload_attachment_bytes.return_value = {}
        client.confirm_attachment.return_value = {"uuid": ATT, "status": "ready"}
        result = _invoke(runner, client, ["task", "attach", TASK, str(path), "--json"])
        assert result.exit_code == 0, result.output
        assert client.presign_attachment.call_args.kwargs == {
            "filename": "notes.txt",
            "content_type": "text/plain",
            "size": 5,
        }
        assert client.upload_attachment_bytes.call_args.args == (_presign(), b"hello")
        assert client.confirm_attachment.call_args.args == (TASK, ATT)
        assert json.loads(result.output) == {"uuid": ATT, "status": "ready"}

    def test_an_oversize_file_is_refused_before_any_request(
        self, runner: CliRunner, client: MagicMock, tmp_path: Path
    ) -> None:
        path: Path = tmp_path / "big.bin"
        with path.open("wb") as handle:
            handle.truncate(ATTACHMENT_MAX_SIZE_BYTES + 1)
        result = _invoke(runner, client, ["task", "attach", TASK, str(path)])
        assert result.exit_code == EXIT_USAGE_ERROR
        assert "25 MiB" in result.output
        client.presign_attachment.assert_not_called()

    def test_an_empty_file_is_refused(
        self, runner: CliRunner, client: MagicMock, tmp_path: Path
    ) -> None:
        path: Path = tmp_path / "empty.txt"
        path.write_bytes(b"")
        result = _invoke(runner, client, ["task", "attach", TASK, str(path)])
        assert result.exit_code == EXIT_USAGE_ERROR
        client.presign_attachment.assert_not_called()

    def test_unknown_types_fall_back_to_octet_stream(
        self, runner: CliRunner, client: MagicMock, tmp_path: Path
    ) -> None:
        path: Path = tmp_path / "blob.zzz-unknown"
        path.write_bytes(b"x")
        client.presign_attachment.return_value = _presign()
        client.confirm_attachment.return_value = {"uuid": ATT}
        _invoke(runner, client, ["task", "attach", TASK, str(path)])
        assert client.presign_attachment.call_args.kwargs["content_type"] == (
            "application/octet-stream"
        )

    def test_storage_unavailable_says_so(
        self, runner: CliRunner, client: MagicMock, tmp_path: Path
    ) -> None:
        path: Path = tmp_path / "a.txt"
        path.write_bytes(b"x")
        client.presign_attachment.side_effect = APIError(
            503, "No storage.", code="attachment_storage_unavailable"
        )
        result = _invoke(runner, client, ["task", "attach", TASK, str(path), "--json"])
        assert result.exit_code != 0
        body: dict[str, Any] = json.loads(result.output)
        assert body["code"] == "attachment_storage_unavailable"
        assert "storage" in body["message"].lower()
        client.upload_attachment_bytes.assert_not_called()

    def test_a_failed_upload_never_confirms(
        self, runner: CliRunner, client: MagicMock, tmp_path: Path
    ) -> None:
        path: Path = tmp_path / "a.txt"
        path.write_bytes(b"x")
        client.presign_attachment.return_value = _presign()
        client.upload_attachment_bytes.side_effect = APIError(
            302, "redirect", code="attachment_upload_redirected"
        )
        result = _invoke(runner, client, ["task", "attach", TASK, str(path)])
        assert result.exit_code != 0
        client.confirm_attachment.assert_not_called()

    def test_a_caption_uses_the_one_door_that_stores_it(
        self, runner: CliRunner, client: MagicMock, tmp_path: Path
    ) -> None:
        path: Path = tmp_path / "a.txt"
        path.write_bytes(b"x")
        client.upload_attachment_multipart.return_value = {"uuid": ATT}
        result = _invoke(
            runner, client, ["task", "attach", TASK, str(path), "--caption", "logs", "--json"]
        )
        assert result.exit_code == 0, result.output
        client.presign_attachment.assert_not_called()
        assert client.upload_attachment_multipart.call_args.kwargs["caption"] == "logs"

    def test_a_captioned_file_over_the_multipart_cap_is_refused(
        self, runner: CliRunner, client: MagicMock, tmp_path: Path
    ) -> None:
        path: Path = tmp_path / "mid.bin"
        with path.open("wb") as handle:
            handle.truncate(ATTACHMENT_MULTIPART_MAX_BYTES + 1)
        result = _invoke(runner, client, ["task", "attach", TASK, str(path), "--caption", "x"])
        assert result.exit_code == EXIT_USAGE_ERROR
        client.upload_attachment_multipart.assert_not_called()


class TestAttachmentsListGetDelete:
    def test_list(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_task_attachments.return_value = [
            {"uuid": ATT, "filename": "[b]x[/b].txt", "size": 5, "status": "ready"}
        ]
        result = _invoke(runner, client, ["task", "attachments", TASK])
        assert result.exit_code == 0, result.output
        assert '"[b]x[/b].txt"' in result.output

    def test_get_writes_the_file(
        self, runner: CliRunner, client: MagicMock, tmp_path: Path
    ) -> None:
        client.download_attachment.return_value = b"payload"
        target: Path = tmp_path / "out.txt"
        result = _invoke(
            runner, client, ["task", "attachment", "get", TASK, ATT, "-o", str(target)]
        )
        assert result.exit_code == 0, result.output
        assert target.read_bytes() == b"payload"

    def test_get_refuses_to_overwrite_without_force(
        self, runner: CliRunner, client: MagicMock, tmp_path: Path
    ) -> None:
        target: Path = tmp_path / "out.txt"
        target.write_bytes(b"keep me")
        result = _invoke(
            runner, client, ["task", "attachment", "get", TASK, ATT, "-o", str(target)]
        )
        assert result.exit_code == EXIT_USAGE_ERROR
        assert target.read_bytes() == b"keep me"
        client.download_attachment.assert_not_called()

    def test_get_overwrites_with_force(
        self, runner: CliRunner, client: MagicMock, tmp_path: Path
    ) -> None:
        target: Path = tmp_path / "out.txt"
        target.write_bytes(b"old")
        client.download_attachment.return_value = b"new"
        result = _invoke(
            runner,
            client,
            ["task", "attachment", "get", TASK, ATT, "-o", str(target), "--force", "--json"],
        )
        assert result.exit_code == 0, result.output
        assert target.read_bytes() == b"new"
        assert json.loads(result.output)["bytes"] == 3

    def test_get_of_a_missing_attachment_writes_nothing(
        self, runner: CliRunner, client: MagicMock, tmp_path: Path
    ) -> None:
        client.download_attachment.side_effect = APIError(404, "Gone.", code="not_found")
        target: Path = tmp_path / "out.txt"
        result = _invoke(
            runner, client, ["task", "attachment", "get", TASK, ATT, "-o", str(target)]
        )
        assert result.exit_code == EXIT_NOT_FOUND
        assert not target.exists()

    def test_delete_dry_run_and_yes(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["task", "attachment", "delete", TASK, ATT, "--dry-run"])
        assert result.exit_code == 0, result.output
        client.delete_task_attachment.assert_not_called()
        client.delete_task_attachment.return_value = {}
        result = _invoke(runner, client, ["task", "attachment", "delete", TASK, ATT, "--yes"])
        assert result.exit_code == 0, result.output
        assert client.delete_task_attachment.call_args.args == (TASK, ATT)


@pytest.mark.parametrize(
    "code",
    [
        "attachment_too_large",
        "attachment_storage_unavailable",
        "attachment_upload_redirected",
        "attachment_upload_target_refused",
        "attachment_download_redirected",
        "column_too_large",
    ],
)
def test_every_new_code_has_a_next_step_message(code: str) -> None:
    assert code in TASKS_ERROR_CODES
    assert ERROR_CODE_MESSAGES[code][0].isupper()


class TestReviewFindings:
    """Final Review (AI Diff Reviewer local pass) findings 1, 4 and 5."""

    def test_a_missing_parent_directory_is_a_clear_error(
        self, runner: CliRunner, client: MagicMock, tmp_path: Path
    ) -> None:
        client.download_attachment.return_value = b"x"
        target: Path = tmp_path / "no-such-dir" / "out.txt"
        result = _invoke(
            runner, client, ["task", "attachment", "get", TASK, ATT, "-o", str(target), "--json"]
        )
        assert result.exit_code == EXIT_USAGE_ERROR
        body: dict[str, Any] = json.loads(result.output)
        assert body["code"] == "output_not_writable"
        assert "This is a bug" not in result.output

    def test_a_file_that_appears_during_the_download_is_not_overwritten(
        self, runner: CliRunner, client: MagicMock, tmp_path: Path
    ) -> None:
        target: Path = tmp_path / "out.txt"

        def download(*_: Any) -> bytes:
            target.write_bytes(b"someone else's file")
            return b"attachment"

        client.download_attachment.side_effect = download
        result = _invoke(
            runner, client, ["task", "attachment", "get", TASK, ATT, "-o", str(target)]
        )
        assert result.exit_code == EXIT_USAGE_ERROR
        assert target.read_bytes() == b"someone else's file"

    def test_a_dangling_symlink_is_not_followed(
        self, runner: CliRunner, client: MagicMock, tmp_path: Path
    ) -> None:
        elsewhere: Path = tmp_path / "elsewhere.txt"
        link: Path = tmp_path / "out.txt"
        link.symlink_to(elsewhere)
        client.download_attachment.return_value = b"attachment"
        result = _invoke(runner, client, ["task", "attachment", "get", TASK, ATT, "-o", str(link)])
        assert result.exit_code == EXIT_USAGE_ERROR
        assert not elsewhere.exists()

    def test_a_storage_refusal_is_not_reported_as_a_login_problem(
        self, real: DailyBotClient
    ) -> None:
        first: Any = _response(status=302, headers={"Location": STORAGE_URL})
        refused: Any = _stream(status=401)
        with (
            patch("dailybot_cli.api_client.httpx.get", return_value=first),
            patch("dailybot_cli.api_client.httpx.stream", return_value=refused),
            pytest.raises(APIError) as caught,
        ):
            real.download_attachment(TASK, ATT)
        assert caught.value.code == "attachment_download_failed"
        assert "login" not in caught.value.detail.lower()

    def test_an_oversize_download_is_refused(self, real: DailyBotClient) -> None:
        big: Any = _response(
            content=b"x", headers={"Content-Length": str(ATTACHMENT_MAX_SIZE_BYTES + 1)}
        )
        with (
            patch("dailybot_cli.api_client.httpx.get", return_value=big),
            pytest.raises(APIError) as caught,
        ):
            real.download_attachment(TASK, ATT)
        assert caught.value.code == "attachment_too_large"

    def test_storage_is_cut_off_at_the_cap_while_streaming(self, real: DailyBotClient) -> None:
        # No Content-Length (chunked), or a small one that a compressed body blows
        # past: the cap has to hold on the bytes actually received.
        first: Any = _response(status=302, headers={"Location": STORAGE_URL})
        chunk: bytes = b"x" * (1024 * 1024)
        produced: list[int] = []

        def endless() -> Any:
            while True:
                produced.append(1)
                yield chunk

        body: Any = _stream(headers={"Content-Length": "10"})
        body.__enter__.return_value.iter_bytes.return_value = endless()
        with (
            patch("dailybot_cli.api_client.httpx.get", return_value=first),
            patch("dailybot_cli.api_client.httpx.stream", return_value=body),
            pytest.raises(APIError) as caught,
        ):
            real.download_attachment(TASK, ATT)
        assert caught.value.code == "attachment_too_large"
        assert len(produced) <= ATTACHMENT_MAX_SIZE_BYTES // len(chunk) + 1

    def test_a_storage_hop_that_runs_past_the_deadline_is_abandoned(
        self, real: DailyBotClient
    ) -> None:
        first: Any = _response(status=302, headers={"Location": STORAGE_URL})
        body: Any = _stream(chunks=[b"a", b"b", b"c"])
        clock: list[float] = [0.0]

        def tick() -> float:
            clock[0] += ATTACHMENT_DOWNLOAD_DEADLINE_SECS
            return clock[0]

        with (
            patch("dailybot_cli.api_client.httpx.get", return_value=first),
            patch("dailybot_cli.api_client.httpx.stream", return_value=body),
            patch("dailybot_cli.api_client.time.monotonic", side_effect=tick),
            pytest.raises(TransportError),
        ):
            real.download_attachment(TASK, ATT)
