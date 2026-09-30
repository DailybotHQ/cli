"""Reactions on comments and project updates: who reacted, update doors, full lists.

The reaction entry is ``{emoji, count, reacted, users[≤10]}``; ``count`` is always
the true total, so a list is truncated exactly when ``count > len(users)``.
HTTP is mocked (``AGENTS.md`` rule 7).
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient, PaginatedResult
from dailybot_cli.display import format_reactions
from dailybot_cli.main import cli

API: str = "http://test-api.example.com"
T: str = "00000000-0000-0000-0000-000000000071"
C: str = "00000000-0000-0000-0000-000000000072"
P: str = "00000000-0000-0000-0000-000000000073"
U: str = "00000000-0000-0000-0000-000000000074"


def _response(payload: Any = None, status: int = 200) -> MagicMock:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = {} if payload is None else payload
    mock.headers = {}
    return mock


def _client() -> DailyBotClient:
    return DailyBotClient(api_url=API, token="t", agent_name="Claude Code")


def _user(name: str, agent: str | None = None) -> dict[str, Any]:
    return {
        "kind": "user",
        "uuid": "00000000-0000-0000-0000-0000000000aa",
        "name": name,
        "username": None,
        "avatar_url": None,
        "has_photo": False,
        "executed_by_agent": {"uuid": "x", "name": agent} if agent else None,
    }


class TestFormatReactions:
    def test_empty(self) -> None:
        assert format_reactions([]) == ""
        assert format_reactions(None) == ""

    def test_names_agent_and_viewer(self) -> None:
        text: str = format_reactions(
            [
                {
                    "emoji": "👍",
                    "count": 2,
                    "reacted": True,
                    "users": [_user("Jane Doe"), _user("John Roe", agent="Claude Code")],
                }
            ]
        )
        assert "👍 2" in text
        assert '"Jane Doe"' in text
        assert '"John Roe" [dim]via "Claude Code"[/dim]' in text
        assert "you reacted" in text

    def test_truncation_is_count_over_users(self) -> None:
        users: list[dict[str, Any]] = [_user(f"Person {i}") for i in range(10)]
        text: str = format_reactions(
            [{"emoji": "🚀", "count": 12, "reacted": False, "users": users}]
        )
        assert "🚀 12" in text
        assert "+2 more" in text

    def test_empty_users_still_counts_the_rest(self) -> None:
        text: str = format_reactions([{"emoji": "👍", "count": 12, "reacted": False, "users": []}])
        assert "+12 more" in text

    def test_legacy_entry_without_users(self) -> None:
        # Older servers send only {emoji, count, reacted}.
        assert "👍 3" in format_reactions([{"emoji": "👍", "count": 3, "reacted": False}])

    def test_hostile_names_are_neutralized(self) -> None:
        text: str = format_reactions(
            [{"emoji": "👍", "count": 1, "users": [_user("[bold]x\x1b[31m")]}]
        )
        assert "\x1b" not in text
        # Rich markup is escaped: printed literally, never applied as a style.
        assert "\\[bold]" in text


class TestWire:
    def test_update_react_posts_the_emoji_stamped(self) -> None:
        with patch("httpx.post", return_value=_response({"uuid": U, "reactions": []})) as post:
            _client().add_update_reaction(P, U, "👍")
        assert post.call_args.args[0] == f"{API}/v1/plan/projects/{P}/updates/{U}/reactions/"
        assert post.call_args.kwargs["json"] == {"emoji": "👍", "agent_name": "Claude Code"}

    def test_update_unreact_percent_encodes(self) -> None:
        with patch("httpx.request", return_value=_response(status=204)) as req:
            _client().remove_update_reaction(P, U, "👍")
        assert req.call_args.args[:2] == (
            "DELETE",
            f"{API}/v1/plan/projects/{P}/updates/{U}/reactions/%F0%9F%91%8D/",
        )

    def test_update_unreact_refuses_a_non_emoji(self) -> None:
        with patch("httpx.request") as req, pytest.raises(APIError) as caught:
            _client().remove_update_reaction(P, U, "../x")
        assert caught.value.code == "reaction_invalid_emoji"
        req.assert_not_called()

    def test_list_comment_reactions_filters_by_emoji(self) -> None:
        page: dict[str, Any] = {"count": 0, "next": None, "previous": None, "results": []}
        with patch("httpx.get", return_value=_response(page)) as get:
            _client().list_comment_reactions(T, C, emoji="👍")
        assert get.call_args.args[0] == f"{API}/v1/plan/tasks/{T}/comments/{C}/reactions/"
        assert get.call_args.kwargs["params"]["emoji"] == "👍"

    def test_list_update_reactions_without_emoji(self) -> None:
        page: dict[str, Any] = {"count": 0, "next": None, "previous": None, "results": []}
        with patch("httpx.get", return_value=_response(page)) as get:
            _client().list_update_reactions(P, U)
        assert get.call_args.args[0] == f"{API}/v1/plan/projects/{P}/updates/{U}/reactions/"
        assert "emoji" not in (get.call_args.kwargs.get("params") or {})


def _invoke(module: str, argv: list[str], client: MagicMock) -> Any:
    with patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client):
        return CliRunner().invoke(cli, argv)


def _page(results: list[dict[str, Any]]) -> PaginatedResult:
    return PaginatedResult(results=results, count=len(results), next=None, previous=None)


class TestCommands:
    def test_update_react_and_unreact(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.add_update_reaction.return_value = {"uuid": U, "reactions": []}
        result = _invoke("project", ["project", "update-react", P, U, "👍", "--json"], client)
        assert result.exit_code == 0, result.output
        client.add_update_reaction.assert_called_once_with(P, U, "👍")
        result = _invoke("project", ["project", "update-unreact", P, U, "👍", "--json"], client)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["removed"] is True
        client.remove_update_reaction.assert_called_once_with(P, U, "👍")

    def test_update_react_refuses_text_locally(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        result = _invoke("project", ["project", "update-react", P, U, ":+1:"], client)
        assert result.exit_code == 2
        client.add_update_reaction.assert_not_called()

    def test_update_react_needs_a_person(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.add_update_reaction.side_effect = APIError(400, "no", code="actor_required")
        result = _invoke("project", ["project", "update-react", P, U, "👍", "--json"], client)
        assert result.exit_code == 3
        assert json.loads(result.output)["code"] == "actor_required"

    def test_comment_reactions_list(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.list_comment_reactions.return_value = _page(
            [
                {
                    "emoji": "👍",
                    "user": _user("Jane Doe"),
                    "executed_by_agent": {"name": "Claude Code"},
                    "created_at": "2026-09-29T10:00:00Z",
                }
            ]
        )
        result = _invoke("task", ["task", "comment-reactions", T, C, "--emoji", "👍"], client)
        assert result.exit_code == 0, result.output
        assert "Jane Doe" in result.output and 'via "Claude Code"' in result.output
        assert client.list_comment_reactions.call_args.kwargs["emoji"] == "👍"

    def test_update_reactions_list_json(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.list_update_reactions.return_value = _page([])
        result = _invoke("project", ["project", "update-reactions", P, U, "--json"], client)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["results"] == []
        assert client.list_update_reactions.call_args.kwargs["emoji"] is None

    def test_list_refuses_a_non_emoji_filter(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        result = _invoke("task", ["task", "comment-reactions", T, C, "--emoji", "ok"], client)
        assert result.exit_code == 2
        client.list_comment_reactions.assert_not_called()


class TestLimit:
    def test_limit_reached_is_explained(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.add_update_reaction.side_effect = APIError(
            400, "limit", code="reaction_limit_reached", extra={"limit": 20}
        )
        result = _invoke("project", ["project", "update-react", P, U, "🎉", "--json"], client)
        assert result.exit_code == 2
        body: dict[str, Any] = json.loads(result.output)
        assert body["code"] == "reaction_limit_reached"
        assert "dailybot project update-unreact" in body["message"]
        assert "dailybot task comment-unreact" in body["message"]
        assert "The limit is 20" in body["message"]

    def test_limit_without_extra_stays_generic(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.add_comment_reaction.side_effect = APIError(
            400, "limit", code="reaction_limit_reached"
        )
        result = _invoke("task", ["task", "comment-react", T, C, "🎉", "--json"], client)
        assert result.exit_code == 2
        assert "The limit is" not in json.loads(result.output)["message"]


class TestListFlags:
    @pytest.mark.parametrize(
        ("module", "argv"),
        [
            ("task", ["task", "comment-reactions", T, C, "--search", "Jane"]),
            ("project", ["project", "update-reactions", P, U, "--today"]),
        ],
    )
    def test_no_filters_the_door_does_not_honour(self, module: str, argv: list[str]) -> None:
        # Only --emoji filters a reactor list; search and date flags would be silent no-ops.
        result = _invoke(module, argv, MagicMock(spec=DailyBotClient))
        assert result.exit_code == 2

    def test_all_fetches_every_page(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.list_update_reactions.return_value = _page([])
        result = _invoke("project", ["project", "update-reactions", P, U, "--all"], client)
        assert result.exit_code == 0, result.output
        assert client.list_update_reactions.call_args.kwargs["fetch_all"] is True


class TestRendering:
    def test_comments_show_reactors(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.list_task_comments.return_value = _page(
            [
                {
                    "uuid": C,
                    "body": "ship it",
                    "author": _user("Jane Doe"),
                    "reactions": [
                        {"emoji": "🚀", "count": 1, "reacted": False, "users": [_user("John Roe")]}
                    ],
                }
            ]
        )
        result = _invoke("task", ["task", "comments", T], client)
        assert result.exit_code == 0, result.output
        assert "🚀 1" in result.output and "John Roe" in result.output

    def test_updates_show_reactors(self) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.list_project_updates.return_value = _page(
            [
                {
                    "uuid": U,
                    "body": "on track",
                    "created_by": _user("Jane Doe"),
                    "reactions": [
                        {"emoji": "👍", "count": 1, "reacted": True, "users": [_user("Jane Doe")]}
                    ],
                }
            ]
        )
        result = _invoke("project", ["project", "updates", P], client)
        assert result.exit_code == 0, result.output
        assert "👍 1" in result.output
