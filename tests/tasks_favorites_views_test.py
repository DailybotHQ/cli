"""Favorites and single saved views.

Only boards and saved views can be pinned; everything here is person-only and
refuses an API key before any request.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import IDEMPOTENCY_KEY_HEADER, APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    EXIT_PERMISSION_DENIED,
    EXIT_USAGE_ERROR,
)
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"
BASE: str = f"{API_URL}/v1/plan/"
BOARD: str = "00000000-0000-0000-0000-000000000001"
VIEW: str = "00000000-0000-0000-0000-000000000002"
PIN: str = "00000000-0000-0000-0000-000000000003"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


@pytest.fixture
def real() -> DailyBotClient:
    return DailyBotClient(api_url=API_URL, token="test-token")


def _response(payload: Any = None, status: int = 200) -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = {} if payload is None else payload
    mock.headers = {}
    return mock


def _invoke(runner: CliRunner, client: Any, args: list[str], *, module: str) -> Any:
    with patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client):
        return runner.invoke(cli, args)


class TestWire:
    def test_pin_with_a_key(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({}, 201)) as post:
            real.add_favorite(target_type="board", target_uuid=BOARD)
        assert post.call_args.args[0] == f"{BASE}me/favorites/"
        assert post.call_args.kwargs["json"] == {"target_type": "board", "target_uuid": BOARD}
        assert IDEMPOTENCY_KEY_HEADER in dict(post.call_args.kwargs.get("headers") or {})

    def test_list_and_unpin(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response([])) as get:
            real.list_favorites()
        assert get.call_args.args[0] == f"{BASE}me/favorites/"
        with patch(
            "dailybot_cli.api_client.httpx.request", return_value=_response(status=204)
        ) as request:
            real.delete_favorite(PIN)
        assert request.call_args.args[:2] == ("DELETE", f"{BASE}me/favorites/{PIN}/")

    def test_view_doors(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response({})) as get:
            real.get_view(VIEW)
        assert get.call_args.args[0] == f"{BASE}views/{VIEW}/"
        with patch("dailybot_cli.api_client.httpx.patch", return_value=_response({})) as patch_:
            real.update_view(VIEW, view_mode="board")
        assert patch_.call_args.kwargs["json"] == {"view_mode": "board"}
        with patch(
            "dailybot_cli.api_client.httpx.request", return_value=_response(status=204)
        ) as request:
            real.delete_view(VIEW)
        assert request.call_args.args[:2] == ("DELETE", f"{BASE}views/{VIEW}/")


class TestStar:
    @pytest.mark.parametrize(
        ("argv", "module", "target"),
        [
            (["plan", "board", "star", BOARD, "--json"], "board", ("board", BOARD)),
            (["plan", "tasks", "view", "star", VIEW, "--json"], "tasks", ("view", VIEW)),
        ],
    )
    def test_star_pins_the_target(
        self, runner: CliRunner, client: MagicMock, argv: list[str], module: str, target: Any
    ) -> None:
        client.add_favorite.return_value = {"uuid": PIN, "rank": 1}
        result = _invoke(runner, client, argv, module=module)
        assert result.exit_code == 0, result.output
        assert client.add_favorite.call_args.kwargs == {
            "target_type": target[0],
            "target_uuid": target[1],
        }

    def test_unstar_finds_the_pin_and_deletes_it(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_favorites.return_value = [
            {"uuid": "other", "target_type": "view", "target_uuid": BOARD},
            {"uuid": PIN, "target_type": "board", "target_uuid": BOARD},
        ]
        result = _invoke(
            runner, client, ["plan", "board", "unstar", BOARD, "--json"], module="board"
        )
        assert result.exit_code == 0, result.output
        client.delete_favorite.assert_called_once_with(PIN)
        assert json.loads(result.output)["unpinned"] is True

    def test_unstar_of_an_unpinned_target_is_a_no_op(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_favorites.return_value = {"results": []}
        result = _invoke(
            runner, client, ["plan", "tasks", "view", "unstar", VIEW, "--json"], module="tasks"
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {
            "unpinned": False,
            "reason": "not_pinned",
            "target": VIEW,
        }
        client.delete_favorite.assert_not_called()

    def test_the_pin_limit_is_reported(self, runner: CliRunner, client: MagicMock) -> None:
        client.add_favorite.side_effect = APIError(400, "Full.", code="favorite_limit_reached")
        result = _invoke(runner, client, ["plan", "board", "star", BOARD, "--json"], module="board")
        assert result.exit_code == EXIT_USAGE_ERROR
        assert json.loads(result.output)["code"] == "favorite_limit_reached"


class TestViews:
    def test_get(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_view.return_value = {"uuid": VIEW, "name": "Mine", "view_mode": "board"}
        result = _invoke(runner, client, ["plan", "tasks", "view", "get", VIEW], module="tasks")
        assert result.exit_code == 0, result.output
        assert "Mine" in result.output

    def test_update_maps_flags_and_filters(
        self, runner: CliRunner, client: MagicMock, tmp_path: Any
    ) -> None:
        filters = tmp_path / "f.json"
        filters.write_text('{"owner": ["me"]}')
        client.update_view.return_value = {"uuid": VIEW}
        result = _invoke(
            runner,
            client,
            [
                "plan", "tasks", "view", "update", VIEW, "--view-mode", "kanban", "--group-by", "owner",
                "--filters-file", str(filters), "--json",
            ],
            module="tasks",
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        assert client.update_view.call_args.kwargs == {
            "view_mode": "kanban",
            "group_by": "owner",
            "filters": {"owner": ["me"]},
        }

    def test_update_needs_a_field(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["plan", "tasks", "view", "update", VIEW], module="tasks")
        assert result.exit_code == EXIT_USAGE_ERROR

    def test_shared_view_edits_need_a_manager(self, runner: CliRunner, client: MagicMock) -> None:
        client.update_view.side_effect = APIError(403, "No.", code="view_visibility_forbidden")
        result = _invoke(
            runner,
            client,
            ["plan", "tasks", "view", "update", VIEW, "--visibility", "shared", "--json"],
            module="tasks",
        )
        assert result.exit_code == EXIT_PERMISSION_DENIED

    def test_delete_confirms(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner, client, ["plan", "tasks", "view", "delete", VIEW, "--dry-run"], module="tasks"
        )
        assert result.exit_code == 0, result.output
        client.delete_view.assert_not_called()


@pytest.mark.parametrize(
    ("argv", "module"),
    [
        (["plan", "board", "star", BOARD, "--json"], "board"),
        (["plan", "board", "unstar", BOARD, "--json"], "board"),
        (["plan", "tasks", "favorites", "--json"], "tasks"),
        (["plan", "tasks", "view", "get", VIEW, "--json"], "tasks"),
        (["plan", "tasks", "view", "update", VIEW, "--name", "x", "--json"], "tasks"),
        (["plan", "tasks", "view", "delete", VIEW, "--yes", "--json"], "tasks"),
        (["plan", "tasks", "view", "star", VIEW, "--json"], "tasks"),
    ],
)
def test_favorite_and_view_doors_send_the_request(
    runner: CliRunner, client: MagicMock, argv: list[str], module: str
) -> None:
    # A personal API key is its person on the API; the server decides.
    client.list_favorites.return_value = []
    _invoke(runner, client, argv, module=module)
    assert client.mock_calls != []


def test_projects_and_goals_cannot_be_starred() -> None:
    runner: CliRunner = CliRunner()
    for group in ("project", "goal"):
        assert " star " not in runner.invoke(cli, [group, "--help"]).output


class TestStrongIfMatch:
    """A weak ETag from the server is sent back as its strong form (RFC 9110 If-Match)."""

    WEAK: str = 'W/"0:empty"'
    STRONG: str = '"0:empty"'

    def test_board_view_save_strips_the_weak_prefix(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response([])) as put:
            real.save_board_views(BOARD, [{"name": "Mine", "filters": {}}], if_match=self.WEAK)
        assert dict(put.call_args.kwargs["headers"])["If-Match"] == self.STRONG

    def test_project_view_save_strips_the_weak_prefix(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response([])) as put:
            real.save_project_views(BOARD, [{"name": "Mine", "filters": {}}], if_match=self.WEAK)
        assert dict(put.call_args.kwargs["headers"])["If-Match"] == self.STRONG

    def test_a_strong_etag_is_sent_unchanged(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response([])) as put:
            real.save_board_views(BOARD, [], if_match='"7"')
        assert dict(put.call_args.kwargs["headers"])["If-Match"] == '"7"'

    def test_the_etag_printed_by_views_stays_as_the_server_sent_it(
        self, real: DailyBotClient
    ) -> None:
        response: Any = _response([])
        response.headers = {"ETag": self.WEAK}
        with patch("dailybot_cli.api_client.httpx.get", return_value=response):
            _, etag = real.list_board_views_with_etag(BOARD)
        assert etag == self.WEAK


class TestViewUpdateHasNoAgentStamp:
    """`PATCH views/<uuid>/` rejects `agent_name` as an unknown field, so it is not sent there."""

    def test_no_agent_name_in_body_or_header(self) -> None:
        stamped: DailyBotClient = DailyBotClient(
            api_url=API_URL, token="test-token", agent_name="Claude Code"
        )
        with patch("dailybot_cli.api_client.httpx.patch", return_value=_response({})) as patch_:
            stamped.update_view(VIEW, group_by="owner")
        assert patch_.call_args.kwargs["json"] == {"group_by": "owner"}
        assert not any("agent" in str(k).lower() for k in dict(patch_.call_args.kwargs["headers"]))

    def test_other_doors_still_carry_the_stamp(self) -> None:
        stamped: DailyBotClient = DailyBotClient(
            api_url=API_URL, token="test-token", agent_name="Claude Code"
        )
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({}, 201)) as post:
            stamped.add_favorite(target_type="board", target_uuid=BOARD)
        assert post.call_args.kwargs["json"]["agent_name"] == "Claude Code"


@pytest.mark.parametrize("group", ["board", "project"])
def test_view_save_help_states_the_shape_of_a_view(runner: CliRunner, group: str) -> None:
    """The file `view save -f` takes is an array of view objects; the help names their fields."""
    output: str = runner.invoke(cli, ["plan", group, "view", "save", "--help"]).output
    for field in ("name", "view_mode", "group_by", "visibility", "filters"):
        assert field in output
    for mode in ("list", "board", "kanban", "timeline", "calendar"):
        assert mode in output
    assert "W/" in output or "weak" in output.lower()
