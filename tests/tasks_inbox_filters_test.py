"""Inbox filters: `--mentioned` and `--type` on the inbox list and its unread badge.

The API filters server-side, so `count` and paging stay exact. Both doors take
the same filters, so a badge counts exactly its tab's rows. With no filter,
nothing extra is sent and the answer is unchanged.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import DailyBotClient, PaginatedResult
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"


def _response(payload: Any) -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = 200
    mock.json.return_value = payload
    mock.headers = {}
    return mock


@pytest.fixture
def real() -> DailyBotClient:
    return DailyBotClient(api_url=API_URL, token="test-token")


class TestWire:
    def test_mentioned_and_type_reach_the_inbox(self, real: DailyBotClient) -> None:
        page: dict[str, Any] = {"count": 0, "next": None, "previous": None, "results": []}
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(page)) as get:
            real.list_tasks_inbox(mentioned=True, event_type="task.owner_changed")
        params: dict[str, Any] = get.call_args.kwargs["params"]
        assert params["mentioned"] == "true"
        assert params["type"] == "task.owner_changed"

    def test_the_badge_takes_the_same_filters(self, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.get", return_value=_response({"unread_count": 2})
        ) as get:
            real.get_tasks_inbox_unread_count(mentioned=True)
        assert get.call_args.kwargs["params"] == {"mentioned": "true"}

    def test_no_filter_sends_nothing_extra(self, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.get", return_value=_response({"unread_count": 2})
        ) as get:
            real.get_tasks_inbox_unread_count()
        assert not get.call_args.kwargs.get("params")


def _invoke(argv: list[str], client: MagicMock) -> Any:
    with (
        patch("dailybot_cli.commands.tasks.require_auth", return_value=client),
        patch("dailybot_cli.commands.tasks.get_token", return_value="tok"),
    ):
        return CliRunner().invoke(cli, argv)


class TestCommands:
    def test_inbox_mentioned(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.list_tasks_inbox.return_value = PaginatedResult(
            results=[], count=0, next=None, previous=None
        )
        result = _invoke(["tasks", "inbox", "--mentioned", "--json"], client)
        assert result.exit_code == 0, result.output
        assert client.list_tasks_inbox.call_args.kwargs["mentioned"] is True

    def test_inbox_unread_by_type(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.get_tasks_inbox_unread_count.return_value = {"unread_count": 1}
        result = _invoke(
            ["tasks", "inbox-unread", "--type", "task.owner_changed", "--json"], client
        )
        assert result.exit_code == 0, result.output
        kwargs: dict[str, Any] = client.get_tasks_inbox_unread_count.call_args.kwargs
        assert kwargs["event_type"] == "task.owner_changed"
        assert kwargs["mentioned"] is None


class TestCommentReplies:
    """The comment list now carries `parent_comment`: replies render under their thread."""

    def test_a_reply_is_marked_and_a_top_level_comment_is_not(self) -> None:
        from rich.console import Console

        from dailybot_cli import display

        buffer: Console = Console(record=True, width=200, color_system=None)
        comments: list[dict[str, Any]] = [
            {"uuid": "c-1", "author": {"full_name": "Jane Doe"}, "body": "Root"},
            {
                "uuid": "c-2",
                "author": {"full_name": "John Roe"},
                "body": "Reply",
                "parent_comment": "c-1",
            },
        ]
        with patch.object(display, "console", buffer):
            display.print_task_comments(comments)
        lines: list[str] = [line for line in buffer.export_text().splitlines() if line.strip()]
        assert not lines[0].lstrip().startswith("↳")
        assert lines[1].lstrip().startswith("↳")
        assert "Reply" in lines[1]
