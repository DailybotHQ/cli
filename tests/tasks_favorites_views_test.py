"""Favorites (API R3a) and single saved views (API R3d) — Tasks Beta PR6b.

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
    EXIT_NOT_AUTHENTICATED,
    EXIT_PERMISSION_DENIED,
    EXIT_USAGE_ERROR,
)
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"
BASE: str = f"{API_URL}/v1/tasks/"
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


def _invoke(
    runner: CliRunner, client: Any, args: list[str], *, module: str, person: bool = True
) -> Any:
    with (
        patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
        patch("dailybot_cli.commands._favorites.get_token", return_value="tok" if person else None),
    ):
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
            (["board", "star", BOARD, "--json"], "board", ("board", BOARD)),
            (["tasks", "view", "star", VIEW, "--json"], "tasks", ("view", VIEW)),
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
        result = _invoke(runner, client, ["board", "unstar", BOARD, "--json"], module="board")
        assert result.exit_code == 0, result.output
        client.delete_favorite.assert_called_once_with(PIN)
        assert json.loads(result.output)["unpinned"] is True

    def test_unstar_of_an_unpinned_target_is_a_no_op(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_favorites.return_value = {"results": []}
        result = _invoke(
            runner, client, ["tasks", "view", "unstar", VIEW, "--json"], module="tasks"
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
        result = _invoke(runner, client, ["board", "star", BOARD, "--json"], module="board")
        assert result.exit_code == EXIT_USAGE_ERROR
        assert json.loads(result.output)["code"] == "favorite_limit_reached"


class TestViews:
    def test_get(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_view.return_value = {"uuid": VIEW, "name": "Mine", "view_mode": "board"}
        result = _invoke(runner, client, ["tasks", "view", "get", VIEW], module="tasks")
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
                "tasks", "view", "update", VIEW, "--view-mode", "kanban", "--group-by", "owner",
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
        result = _invoke(runner, client, ["tasks", "view", "update", VIEW], module="tasks")
        assert result.exit_code == EXIT_USAGE_ERROR

    def test_shared_view_edits_need_a_manager(self, runner: CliRunner, client: MagicMock) -> None:
        client.update_view.side_effect = APIError(403, "No.", code="view_visibility_forbidden")
        result = _invoke(
            runner,
            client,
            ["tasks", "view", "update", VIEW, "--visibility", "shared", "--json"],
            module="tasks",
        )
        assert result.exit_code == EXIT_PERMISSION_DENIED

    def test_delete_confirms(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner, client, ["tasks", "view", "delete", VIEW, "--dry-run"], module="tasks"
        )
        assert result.exit_code == 0, result.output
        client.delete_view.assert_not_called()


@pytest.mark.parametrize(
    ("argv", "module"),
    [
        (["board", "star", BOARD, "--json"], "board"),
        (["board", "unstar", BOARD, "--json"], "board"),
        (["tasks", "favorites", "--json"], "tasks"),
        (["tasks", "view", "get", VIEW, "--json"], "tasks"),
        (["tasks", "view", "update", VIEW, "--name", "x", "--json"], "tasks"),
        (["tasks", "view", "delete", VIEW, "--yes", "--json"], "tasks"),
        (["tasks", "view", "star", VIEW, "--json"], "tasks"),
    ],
)
def test_person_only_doors_refuse_a_key(
    runner: CliRunner, client: MagicMock, argv: list[str], module: str
) -> None:
    result = _invoke(runner, client, argv, module=module, person=False)
    assert result.exit_code == EXIT_NOT_AUTHENTICATED
    for method in ("add_favorite", "list_favorites", "delete_favorite", "get_view", "update_view"):
        getattr(client, method).assert_not_called()


def test_projects_and_goals_cannot_be_starred() -> None:
    runner: CliRunner = CliRunner()
    for group in ("project", "goal"):
        assert " star " not in runner.invoke(cli, [group, "--help"]).output
