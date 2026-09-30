"""The last Tasks doors: comment reactions, label edit/delete, recents, visits, resolve.

With these, every live `/v1/plan/` operation in the API contract has a CLI
command (task delegation answers 501 until its runtime ships). HTTP is mocked
(``AGENTS.md`` rule 7).
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient, is_reaction_emoji
from dailybot_cli.main import cli

API: str = "http://test-api.example.com"
T: str = "00000000-0000-0000-0000-000000000061"
C: str = "00000000-0000-0000-0000-000000000062"
L: str = "00000000-0000-0000-0000-000000000063"
B: str = "00000000-0000-0000-0000-000000000064"


def _response(payload: Any = None, status: int = 200) -> MagicMock:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = {} if payload is None else payload
    mock.headers = {}
    return mock


def _client() -> DailyBotClient:
    return DailyBotClient(api_url=API, token="t", agent_name="Claude Code")


class TestEmojiRule:
    @pytest.mark.parametrize("emoji", ["👍", "🚀", "❤️", "👩‍💻", "☀"])
    def test_accepted(self, emoji: str) -> None:
        assert is_reaction_emoji(emoji)

    # Outside the API contract's ranges: the server refuses these, so the CLI does too.
    @pytest.mark.parametrize("emoji", ["", ":+1:", "ok", "👍x", "👍" * 9, "<b>", "🇺🇸", "⭐", "1️⃣"])
    def test_refused(self, emoji: str) -> None:
        assert not is_reaction_emoji(emoji)


class TestWire:
    def test_react_posts_the_emoji_stamped(self) -> None:
        with patch("httpx.post", return_value=_response({"uuid": C, "reactions": []})) as post:
            _client().add_comment_reaction(T, C, "👍")
        assert post.call_args.args[0] == f"{API}/v1/plan/tasks/{T}/comments/{C}/reactions/"
        assert post.call_args.kwargs["json"] == {"emoji": "👍", "agent_name": "Claude Code"}

    def test_unreact_percent_encodes_the_emoji_in_the_path(self) -> None:
        with patch("httpx.request", return_value=_response(status=204)) as req:
            _client().remove_comment_reaction(T, C, "👍")
        method, url = req.call_args.args[:2]
        assert method == "DELETE"
        assert url == f"{API}/v1/plan/tasks/{T}/comments/{C}/reactions/%F0%9F%91%8D/"

    def test_unreact_refuses_a_non_emoji_before_the_request(self) -> None:
        with patch("httpx.request") as req, pytest.raises(APIError) as caught:
            _client().remove_comment_reaction(T, C, "../x")
        assert caught.value.code == "reaction_invalid_emoji"
        req.assert_not_called()

    def test_label_update_and_delete(self) -> None:
        with patch("httpx.patch", return_value=_response({"uuid": L})) as p:
            _client().update_tasks_label(L, color="#ef4444", is_archived=True)
        assert p.call_args.args[0] == f"{API}/v1/plan/labels/{L}/"
        assert p.call_args.kwargs["json"]["color"] == "#ef4444"
        assert p.call_args.kwargs["json"]["is_archived"] is True
        with patch("httpx.request", return_value=_response(status=204)) as req:
            _client().delete_tasks_label(L)
        assert req.call_args.args[:2] == ("DELETE", f"{API}/v1/plan/labels/{L}/")

    def test_recents_visit_resolve(self) -> None:
        with patch("httpx.get", return_value=_response({"results": []})) as get:
            _client().list_recent_boards()
        assert get.call_args.args[0] == f"{API}/v1/plan/me/recents/"
        with patch("httpx.post", return_value=_response({"board": B})) as post:
            _client().visit_board(B)
        assert post.call_args.args[0] == f"{API}/v1/plan/boards/{B}/visit/"
        with patch("httpx.get", return_value=_response({"resolved": {}})) as get:
            _client().resolve_attachments(["a1", "b2"])
        assert get.call_args.args[0] == f"{API}/v1/plan/attachments/resolve/"
        assert get.call_args.kwargs["params"] == {"ids": "a1,b2"}


def _invoke(module: str, argv: list[str], client: MagicMock) -> Any:
    with patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client):
        return CliRunner().invoke(cli, argv)


class TestCommands:
    def test_react_refuses_text_locally(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        result = _invoke("task", ["task", "comment-react", T, C, ":+1:"], client)
        assert result.exit_code == 2
        client.add_comment_reaction.assert_not_called()

    def test_react_and_unreact(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.add_comment_reaction.return_value = {"uuid": C, "reactions": [{"emoji": "👍"}]}
        assert (
            _invoke("task", ["task", "comment-react", T, C, "👍", "--json"], client).exit_code == 0
        )
        client.add_comment_reaction.assert_called_once_with(T, C, "👍")
        assert _invoke("task", ["task", "comment-unreact", T, C, "👍"], client).exit_code == 0
        client.remove_comment_reaction.assert_called_once_with(T, C, "👍")

    def test_label_update_needs_a_field(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        result = _invoke("board", ["board", "label", "update", L], client)
        assert result.exit_code == 2
        client.update_tasks_label.assert_not_called()

    def test_label_archive_flag(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.update_tasks_label.return_value = {"uuid": L, "name": "bug"}
        result = _invoke("board", ["board", "label", "update", L, "--archive", "--json"], client)
        assert result.exit_code == 0, result.output
        assert client.update_tasks_label.call_args.kwargs == {"is_archived": True}

    def test_label_delete_in_use_suggests_archiving(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.delete_tasks_label.side_effect = APIError(
            409, "in use", code="label_in_use", extra={"usage_count": 3}
        )
        result = _invoke("board", ["board", "label", "delete", L, "--yes", "--json"], client)
        assert result.exit_code == 4
        assert "archive" in json.loads(result.output)["message"].lower()

    def test_label_delete_dry_run_sends_nothing(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        assert _invoke("board", ["board", "label", "delete", L, "--dry-run"], client).exit_code == 0
        client.delete_tasks_label.assert_not_called()

    def test_recents_visit_resolve_commands(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.list_recent_boards.return_value = {
            "results": [{"board": B, "name": "Design", "key": "DSN", "visited_at": "2026-09-29"}]
        }
        result = _invoke("tasks", ["tasks", "recents"], client)
        assert result.exit_code == 0 and "Design" in result.output
        client.visit_board.return_value = {"board": B, "visited_at": "2026-09-29"}
        assert _invoke("board", ["board", "visit", B, "--json"], client).exit_code == 0
        client.resolve_attachments.return_value = {"resolved": {"a1": {"url": "/c/"}}}
        result = _invoke("tasks", ["tasks", "attachments-resolve", "a1", "b2", "--json"], client)
        assert result.exit_code == 0
        client.resolve_attachments.assert_called_once_with(["a1", "b2"])


class TestReplies:
    def test_reply_sends_parent_comment(self) -> None:
        with patch("httpx.post", return_value=_response({"uuid": "c2"})) as post:
            _client().comment_on_task(T, body="agreed", parent_comment=C)
        assert post.call_args.kwargs["json"]["parent_comment"] == C

    def test_reply_to_option(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.comment_on_task.return_value = {"uuid": "c2"}
        result = _invoke(
            "task", ["task", "comment", T, "agreed", "--reply-to", C, "--json"], client
        )
        assert result.exit_code == 0, result.output
        assert client.comment_on_task.call_args.kwargs["parent_comment"] == C
