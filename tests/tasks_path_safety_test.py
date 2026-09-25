"""Identifiers never change which Tasks endpoint a command reaches.

A task key or uuid is interpolated into a URL path. A value such as
`X/../../boards/<uuid>/archive/?` would otherwise be collapsed by the HTTP stack
into a different door — `task watch` archiving a board. Task text is untrusted
and an agent may copy an "id" out of it, so every path segment is validated
before any request is sent.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import EXIT_USAGE_ERROR
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"
BOARD: str = "00000000-0000-0000-0000-000000000001"

HOSTILE: list[str] = [
    f"X/../../boards/{BOARD}/archive/?",
    "ENG-1/archive",
    "ENG-1?x=1",
    "ENG-1#frag",
    "..",
    ".",
    "ENG-1%2F..",
    "ENG 1",
    "ENG-1\\..",
    "",
]


@pytest.fixture
def real() -> DailyBotClient:
    return DailyBotClient(api_url=API_URL, token="test-token")


def _response(payload: Any) -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = 200
    mock.json.return_value = payload
    mock.headers = {}
    return mock


class TestClientBoundary:
    @pytest.mark.parametrize("value", HOSTILE)
    def test_a_hostile_identifier_is_refused_before_any_request(
        self, real: DailyBotClient, value: str
    ) -> None:
        with (
            patch("dailybot_cli.api_client.httpx.post") as post,
            patch("dailybot_cli.api_client.httpx.request") as request,
            pytest.raises(APIError) as caught,
        ):
            real.subscribe_task(value)
        assert caught.value.code == "invalid_identifier"
        assert caught.value.status_code == 400
        post.assert_not_called()
        request.assert_not_called()

    @pytest.mark.parametrize("value", ["ENG-142", "eng-7", BOARD, "t_1"])
    def test_keys_and_uuids_pass(self, real: DailyBotClient, value: str) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response({})) as get:
            real.get_task(value)
        assert get.call_args.args[0] == f"{API_URL}/v1/tasks/tasks/{value}/"

    def test_the_url_builder_refuses_traversal_on_its_own(self, real: DailyBotClient) -> None:
        with pytest.raises(APIError):
            real._tasks_url("tasks/../boards/x/archive/")

    def test_the_error_does_not_echo_the_value(self, real: DailyBotClient) -> None:
        with pytest.raises(APIError) as caught:
            real.get_task("[red]x[/red]/..")
        assert "[red]" not in caught.value.detail


class TestCommandExit:
    def test_task_restore_with_a_traversal_exits_usage_and_sends_nothing(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        with (
            patch("dailybot_cli.commands.task.require_auth", return_value=client),
            patch("dailybot_cli.api_client.httpx.post") as post,
            patch("dailybot_cli.api_client.httpx.request") as request,
        ):
            result = CliRunner().invoke(cli, ["task", "restore", HOSTILE[0]])
        assert result.exit_code == EXIT_USAGE_ERROR, result.output
        post.assert_not_called()
        request.assert_not_called()

    def test_task_comment_with_a_slash_exits_usage(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        with (
            patch("dailybot_cli.commands.task.require_auth", return_value=client),
            patch("dailybot_cli.api_client.httpx.post") as post,
            patch("dailybot_cli.api_client.httpx.request") as request,
        ):
            result = CliRunner().invoke(cli, ["task", "comment", "ENG-1/archive", "hi"])
        assert result.exit_code == EXIT_USAGE_ERROR, result.output
        post.assert_not_called()
        request.assert_not_called()


def _refusal(status: int, code: str) -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = {"code": code, "detail": "refused"}
    mock.headers = {}
    return mock


class TestCredentialKindRetry:
    """A person refused on a Tasks door is never silently replayed as the organization."""

    def test_a_bearer_403_is_not_replayed_with_the_org_key(self) -> None:
        client: DailyBotClient = DailyBotClient(
            api_url=API_URL, token="test-token", api_key="test-key"
        )
        with (
            patch(
                "dailybot_cli.api_client.httpx.post",
                return_value=_refusal(403, "permission_denied"),
            ) as post,
            pytest.raises(APIError) as caught,
        ):
            client.restore_task("ENG-1")
        assert caught.value.status_code == 403
        assert post.call_count == 1
        assert "Authorization" in post.call_args.kwargs["headers"]

    def test_a_key_refused_on_a_person_door_still_retries_as_the_person(self) -> None:
        client: DailyBotClient = DailyBotClient(
            api_url=API_URL, token="test-token", api_key="test-key"
        )
        client._prefer_api_key = True
        with patch(
            "dailybot_cli.api_client.httpx.post",
            side_effect=[_refusal(403, "insufficient_scope"), _response({"ok": True})],
        ) as post:
            client.subscribe_task("ENG-1")
        assert post.call_count == 2
        assert "Authorization" in post.call_args_list[1].kwargs["headers"]

    def test_an_expired_session_still_falls_back_on_401(self) -> None:
        client: DailyBotClient = DailyBotClient(
            api_url=API_URL, token="test-token", api_key="test-key"
        )
        with patch(
            "dailybot_cli.api_client.httpx.get",
            side_effect=[_refusal(401, "not_authenticated"), _response({"key": "ENG-1"})],
        ) as get:
            client.get_task("ENG-1")
        assert get.call_count == 2


def _page_response(results: list[dict[str, Any]], next_url: str | None) -> Any:
    return _response({"count": 3, "next": next_url, "previous": None, "results": results})


class TestPaginationStaysOnTheApi:
    """A `next` link is server data; credentials follow it only to the API itself."""

    def test_a_next_link_to_another_host_is_followed_on_the_api_only(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        first: Any = _page_response(
            [{"uuid": "b-1"}], "https://evil.example/v1/tasks/boards/?page=2"
        )
        second: Any = _page_response([{"uuid": "b-2"}], None)
        with patch("dailybot_cli.api_client.httpx.get", side_effect=[first, second]) as get:
            client.list_boards(fetch_all=True)
        followed: str = get.call_args_list[1].args[0]
        assert followed == f"{API_URL}/v1/tasks/boards/?page=2"
        assert "evil.example" not in followed

    def test_a_same_host_link_is_followed_on_the_api_scheme(self) -> None:
        client: DailyBotClient = DailyBotClient(
            api_url="https://api.example.com", token="test-token"
        )
        first: Any = _page_response(
            [{"uuid": "b-1"}], "http://api.example.com/v1/tasks/boards/?page=2"
        )
        second: Any = _page_response([{"uuid": "b-2"}], None)
        with patch("dailybot_cli.api_client.httpx.get", side_effect=[first, second]) as get:
            result = client.list_boards(fetch_all=True)
        assert len(result.results) == 2
        assert get.call_args_list[1].args[0] == "https://api.example.com/v1/tasks/boards/?page=2"
