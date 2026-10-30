"""Every request the CLI makes identifies itself with a `dailybot-cli/<version>` User-Agent.

The backend counts CLI versions in the wild from this header before it changes
anything an old client depends on (the registration challenge first). So the
header rides on every path: anonymous, user-scoped, agent-scoped, the
alternative-credential retry, streamed downloads, and the credential-less hops to
object storage, which still carry no Dailybot credential.
"""

import json
import platform
import re
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from dailybot_cli import __version__
from dailybot_cli.api_client import DailyBotClient, user_agent

API_URL: str = "https://api.example.com"
STORAGE_URL: str = "https://storage.example-bucket.com/uploads/a-1?sig=abc"
UA_RE: re.Pattern[str] = re.compile(
    r"^dailybot-cli/(?P<ver>\S+) \(python/(?P<py>\d+\.\d+); (?P<os>[^;]+); (?P<method>[^)]+)\)$"
)


def _response(status: int = 200, body: Any = None, headers: dict[str, str] | None = None) -> Any:
    response: MagicMock = MagicMock(spec=httpx.Response)
    response.status_code = status
    response.headers = headers or {}
    response.json.return_value = {} if body is None else body
    response.text = json.dumps(body or {})
    return response


class _Stream:
    """A context manager standing in for `httpx.stream`."""

    def __init__(self, status: int = 200, chunks: list[bytes] | None = None) -> None:
        self.response: MagicMock = MagicMock()
        self.response.status_code = status
        self.response.headers = {}
        self.response.iter_bytes.return_value = iter(chunks or [b"data"])

    def __enter__(self) -> Any:
        return self.response

    def __exit__(self, *args: Any) -> None:
        return None


def _sent_headers(mock: MagicMock) -> dict[str, str]:
    return dict(mock.call_args.kwargs["headers"])


class TestUserAgentString:
    def test_it_names_the_cli_version_python_os_and_install_method(self) -> None:
        match: re.Match[str] | None = UA_RE.match(user_agent())
        assert match is not None, user_agent()
        assert match.group("ver") == __version__
        assert (
            match.group("py")
            == f"{platform.python_version_tuple()[0]}.{platform.python_version_tuple()[1]}"
        )
        assert match.group("os") == (platform.system().lower() or "unknown")

    def test_an_install_method_failure_degrades_to_unknown(self) -> None:
        user_agent.cache_clear()
        try:
            with patch(
                "dailybot_cli.api_client.detect_install_method", side_effect=OSError("boom")
            ):
                assert user_agent().endswith("; unknown)")
        finally:
            user_agent.cache_clear()


class TestEveryPathCarriesIt:
    def test_anonymous_registration_calls(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL)
        with patch(
            "dailybot_cli.api_client.httpx.get",
            return_value=_response(body={"challenge_id": "c", "instruction": "i"}),
        ) as get:
            client.get_registration_challenge()
        headers: dict[str, str] = _sent_headers(get)
        assert headers["User-Agent"] == user_agent()
        assert "Authorization" not in headers and "X-API-KEY" not in headers

        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response(status=201, body={})
        ) as post:
            client.register_agent(
                challenge_id="c", answer=1, reason="r" * 20, org_name="o", agent_name="a"
            )
        assert _sent_headers(post)["User-Agent"] == user_agent()

    def test_user_scoped_and_agent_scoped_requests(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, api_key="test-key")
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(body={})) as get:
            client.get_status()
        assert _sent_headers(get)["User-Agent"] == user_agent()

        with patch(
            "dailybot_cli.api_client.httpx.request", return_value=_response(body={})
        ) as request:
            client.get_agent_health(agent_name="a")
        assert _sent_headers(request)["User-Agent"] == user_agent()
        assert _sent_headers(request)["X-API-KEY"] == "test-key"

    def test_the_alternative_credential_retry(self) -> None:
        client: DailyBotClient = DailyBotClient(
            api_url=API_URL, token="test-token", api_key="test-key"
        )
        with patch(
            "dailybot_cli.api_client.httpx.request",
            side_effect=[_response(status=401, body={"detail": "no"}), _response(body={})],
        ) as request:
            client.get_agent_health(agent_name="a")
        assert request.call_count == 2
        retry_headers: dict[str, str] = dict(request.call_args_list[1].kwargs["headers"])
        assert retry_headers["User-Agent"] == user_agent()
        assert retry_headers["X-API-KEY"] == "test-key"

    def test_a_foreign_presigned_upload_gets_the_header_but_no_credential(self) -> None:
        client: DailyBotClient = DailyBotClient(
            api_url=API_URL, token="test-token", api_key="test-key"
        )
        presign: dict[str, Any] = {
            "upload_url": STORAGE_URL,
            "method": "PUT",
            "headers": {"Content-Type": "text/plain"},
        }
        with patch("dailybot_cli.api_client.httpx.request", return_value=_response()) as request:
            client.upload_attachment_bytes(presign, b"hello")
        headers: dict[str, str] = _sent_headers(request)
        assert headers == {"Content-Type": "text/plain", "User-Agent": user_agent()}

    def test_a_presign_header_cannot_be_overridden_by_the_server(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        presign: dict[str, Any] = {
            "upload_url": STORAGE_URL,
            "method": "PUT",
            "headers": {"Content-Type": "text/plain", "User-Agent": "spoofed"},
        }
        with patch("dailybot_cli.api_client.httpx.request", return_value=_response()) as request:
            client.upload_attachment_bytes(presign, b"hello")
        # A signed presign may pin its own User-Agent; the server's value wins there.
        assert _sent_headers(request)["User-Agent"] == "spoofed"

    def test_streamed_downloads_from_the_api_and_from_storage(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        api_stream: _Stream = _Stream()
        with patch("dailybot_cli.api_client.httpx.stream", return_value=api_stream) as stream:
            client.download_attachment("11111111-1111-1111-1111-111111111111", "a-1")
        assert stream.call_args.kwargs["headers"]["User-Agent"] == user_agent()

        with patch("dailybot_cli.api_client.httpx.stream", return_value=_Stream()) as stream:
            DailyBotClient._download_from_storage(STORAGE_URL)
        headers: dict[str, str] = stream.call_args.kwargs["headers"]
        assert headers["User-Agent"] == user_agent()
        assert "Authorization" not in headers and "X-API-KEY" not in headers


@pytest.fixture(autouse=True)
def _fresh_user_agent() -> Any:
    user_agent.cache_clear()
    yield
    user_agent.cache_clear()
