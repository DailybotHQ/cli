"""Existing commands corrected against the published write contract.

Each fix is pinned on the exact wire the real client sends:

- `goal create` sends the required `period_start` / `period_end` dates;
- `task move --board` uses the `move-board/` door (``move/`` requires a state);
- `task move --state` resolves a column NAME or CATEGORY to its uuid client-side,
  because `move/` accepts a uuid only;
- `task create|update --priority` is an integer 1..5 (1 urgent … 5 none);
- `task link` sends `target_task` and a declared `relation_type`;
- `board create` offers no description (BoardWrite has none).
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import IDEMPOTENCY_KEY_HEADER, DailyBotClient
from dailybot_cli.commands.public_api_helpers import EXIT_USAGE_ERROR
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"
BASE: str = f"{API_URL}/v1/tasks/"
TASK: str = "ENG-142"
BOARD: str = "b-1"
STATE_UUID: str = "00000000-0000-0000-0000-000000000005"

# A board's live columns, deliberately out of position order.
STATES: list[dict[str, Any]] = [
    {"uuid": "s-done-2", "name": "Shipped", "category": "done", "position": 5},
    {"uuid": "s-todo", "name": "To do", "category": "todo", "position": 1},
    {"uuid": "s-done", "name": "Done", "category": "done", "position": 4},
    {"uuid": "s-doing", "name": "Doing", "category": "in_progress", "position": 2},
    {"uuid": "s-rev-a", "name": "Review", "category": "in_progress", "position": 3},
]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def real() -> DailyBotClient:
    return DailyBotClient(api_url=API_URL, token="test-token")


def _response(payload: Any, status: int = 200) -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = payload
    mock.headers = {}
    return mock


def _get_router(states: list[dict[str, Any]]) -> Any:
    """Answer the two reads a name resolution makes: the task, then its board's states."""

    def route(url: str, **_: Any) -> Any:
        if url.endswith(f"/tasks/{TASK}/"):
            return _response({"uuid": "t-1", "key": TASK, "board": BOARD})
        if url.endswith(f"/boards/{BOARD}/states/") or url.endswith("/boards/b-2/states/"):
            return _response(states)
        raise AssertionError(f"unexpected GET {url}")

    return route


def _invoke(runner: CliRunner, client: DailyBotClient, args: list[str], module: str) -> Any:
    with (
        patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
        patch(f"dailybot_cli.commands.{module}.get_token", return_value="tok", create=True),
    ):
        return runner.invoke(cli, args)


# ---------------------------------------------------------------------------
# goal create
# ---------------------------------------------------------------------------


class TestGoalCreatePeriod:
    def test_the_period_is_sent(self, runner: CliRunner, real: DailyBotClient) -> None:
        with (
            patch("dailybot_cli.commands.project.get_token", return_value="tok"),
            patch(
                "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": "g-1"}, 201)
            ) as post,
        ):
            result = _invoke(
                runner,
                real,
                [
                    "goal", "create", "-n", "Q4 reliability", "--period-start", "2026-10-01",
                    "--period-end", "2026-12-31", "--json",
                ],
                "goal",
            )  # fmt: skip
        assert result.exit_code == 0, result.output
        assert post.call_args.args[0] == f"{BASE}goals/"
        assert post.call_args.kwargs["json"] == {
            "name": "Q4 reliability",
            "period_start": "2026-10-01",
            "period_end": "2026-12-31",
        }

    @pytest.mark.parametrize(
        "extra",
        [
            [],
            ["--period-start", "2026-10-01"],
            ["--period-start", "2026-13-01", "--period-end", "2026-12-31"],
        ],
    )
    def test_a_missing_or_malformed_period_never_reaches_the_server(
        self, runner: CliRunner, real: DailyBotClient, extra: list[str]
    ) -> None:
        with (
            patch("dailybot_cli.commands.project.get_token", return_value="tok"),
            patch("dailybot_cli.api_client.httpx.post") as post,
        ):
            result = _invoke(runner, real, ["goal", "create", "-n", "x", *extra], "goal")
        assert result.exit_code == EXIT_USAGE_ERROR
        post.assert_not_called()

    def test_the_end_cannot_precede_the_start(
        self, runner: CliRunner, real: DailyBotClient
    ) -> None:
        with (
            patch("dailybot_cli.commands.project.get_token", return_value="tok"),
            patch("dailybot_cli.api_client.httpx.post") as post,
        ):
            result = _invoke(
                runner,
                real,
                [
                    "goal", "create", "-n", "x", "--period-start", "2026-12-31",
                    "--period-end", "2026-10-01",
                ],
                "goal",
            )  # fmt: skip
        assert result.exit_code == EXIT_USAGE_ERROR
        post.assert_not_called()


# ---------------------------------------------------------------------------
# task move
# ---------------------------------------------------------------------------


class TestMoveResolvesTheState:
    def _move(
        self, runner: CliRunner, real: DailyBotClient, args: list[str], states: Any = None
    ) -> tuple[Any, MagicMock, MagicMock]:
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                side_effect=_get_router(STATES if states is None else states),
            ) as get,
            patch(
                "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": "t-1"})
            ) as post,
        ):
            result = _invoke(runner, real, ["task", "move", TASK, *args], "task")
        return result, get, post

    def test_a_uuid_is_sent_as_is_without_extra_reads(
        self, runner: CliRunner, real: DailyBotClient
    ) -> None:
        result, get, post = self._move(runner, real, ["--state", STATE_UUID])
        assert result.exit_code == 0, result.output
        get.assert_not_called()
        assert post.call_args.args[0] == f"{BASE}tasks/{TASK}/move/"
        assert post.call_args.kwargs["json"] == {"state": STATE_UUID}

    @pytest.mark.parametrize(("value", "expected"), [("Doing", "s-doing"), ("review", "s-rev-a")])
    def test_a_name_matches_case_insensitively(
        self, runner: CliRunner, real: DailyBotClient, value: str, expected: str
    ) -> None:
        result, _get, post = self._move(runner, real, ["--state", value])
        assert result.exit_code == 0, result.output
        assert post.call_args.kwargs["json"] == {"state": expected}

    def test_a_category_picks_its_lowest_position_column(
        self, runner: CliRunner, real: DailyBotClient
    ) -> None:
        result, _get, post = self._move(runner, real, ["--state", "in_progress"])
        assert result.exit_code == 0, result.output
        assert post.call_args.kwargs["json"] == {"state": "s-doing"}

    def test_a_name_wins_over_a_category(self, runner: CliRunner, real: DailyBotClient) -> None:
        # "done" is both a category and the name of a column; the named column wins.
        result, _get, post = self._move(runner, real, ["--state", "done"])
        assert result.exit_code == 0, result.output
        assert post.call_args.kwargs["json"] == {"state": "s-done"}

    def test_an_ambiguous_name_lists_the_candidates(
        self, runner: CliRunner, real: DailyBotClient
    ) -> None:
        twins: list[dict[str, Any]] = [
            {"uuid": "a", "name": "QA", "category": "todo", "position": 1},
            {"uuid": "b", "name": "qa", "category": "in_progress", "position": 2},
        ]
        result, _get, post = self._move(runner, real, ["--state", "QA"], states=twins)
        assert result.exit_code == EXIT_USAGE_ERROR
        assert "a" in result.output and "b" in result.output
        post.assert_not_called()

    def test_an_unknown_state_lists_the_columns(
        self, runner: CliRunner, real: DailyBotClient
    ) -> None:
        result, _get, post = self._move(runner, real, ["--state", "Nowhere"])
        assert result.exit_code == EXIT_USAGE_ERROR
        assert "Doing" in result.output
        post.assert_not_called()

    def test_the_move_still_sends_a_key(self, runner: CliRunner, real: DailyBotClient) -> None:
        _result, _get, post = self._move(runner, real, ["--state", "Doing"])
        assert IDEMPOTENCY_KEY_HEADER in dict(post.call_args.kwargs.get("headers") or {})


class TestMoveToAnotherBoard:
    def test_board_only_uses_the_move_board_door(
        self, runner: CliRunner, real: DailyBotClient
    ) -> None:
        with (
            patch("dailybot_cli.api_client.httpx.get") as get,
            patch(
                "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": "t-1"})
            ) as post,
        ):
            result = _invoke(runner, real, ["task", "move", TASK, "--board", "b-2"], "task")
        assert result.exit_code == 0, result.output
        get.assert_not_called()
        assert post.call_args.args[0] == f"{BASE}tasks/{TASK}/move-board/"
        assert post.call_args.kwargs["json"] == {"board": "b-2"}
        # move-board/ does not accept an Idempotency-Key.
        assert IDEMPOTENCY_KEY_HEADER not in dict(post.call_args.kwargs.get("headers") or {})

    def test_a_named_state_resolves_on_the_target_board(
        self, runner: CliRunner, real: DailyBotClient
    ) -> None:
        with (
            patch("dailybot_cli.api_client.httpx.get", side_effect=_get_router(STATES)) as get,
            patch(
                "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": "t-1"})
            ) as post,
        ):
            result = _invoke(
                runner, real, ["task", "move", TASK, "--board", "b-2", "--state", "Doing"], "task"
            )
        assert result.exit_code == 0, result.output
        assert get.call_args.args[0] == f"{BASE}boards/b-2/states/"
        assert post.call_args.kwargs["json"] == {"board": "b-2", "state": "s-doing"}


# ---------------------------------------------------------------------------
# priority
# ---------------------------------------------------------------------------


class TestPriorityIsAnInteger:
    def test_update_sends_an_integer(self, runner: CliRunner, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.patch", return_value=_response({"uuid": "t-1"})
        ) as patch_:
            result = _invoke(runner, real, ["task", "update", TASK, "--priority", "2"], "task")
        assert result.exit_code == 0, result.output
        assert patch_.call_args.kwargs["json"] == {"priority": 2}

    def test_create_sends_an_integer(self, runner: CliRunner, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": "t-1"}, 201)
        ) as post:
            result = _invoke(
                runner, real, ["task", "create", "-t", "x", "-b", BOARD, "--priority", "1"], "task"
            )
        assert result.exit_code == 0, result.output
        assert post.call_args.kwargs["json"]["priority"] == 1

    @pytest.mark.parametrize("value", ["0", "6", "high"])
    def test_out_of_range_is_a_usage_error(
        self, runner: CliRunner, real: DailyBotClient, value: str
    ) -> None:
        with patch("dailybot_cli.api_client.httpx.patch") as patch_:
            result = _invoke(runner, real, ["task", "update", TASK, "--priority", value], "task")
        assert result.exit_code == EXIT_USAGE_ERROR
        patch_.assert_not_called()


# ---------------------------------------------------------------------------
# link
# ---------------------------------------------------------------------------


class TestLinkWire:
    @pytest.mark.parametrize(
        ("given", "sent"),
        [
            ("blocks", "blocks"),
            ("relates_to", "relates_to"),
            ("relates-to", "relates_to"),
            ("duplicates", "duplicates"),
        ],
    )
    def test_the_body_uses_the_contract_fields(
        self, runner: CliRunner, real: DailyBotClient, given: str, sent: str
    ) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": "r-1"}, 201)
        ) as post:
            result = _invoke(
                runner, real, ["task", "link", TASK, "ENG-99", "--type", given], "task"
            )
        assert result.exit_code == 0, result.output
        assert post.call_args.args[0] == f"{BASE}tasks/{TASK}/relations/"
        assert post.call_args.kwargs["json"] == {"relation_type": sent, "target_task": "ENG-99"}

    def test_an_unknown_type_is_a_usage_error(
        self, runner: CliRunner, real: DailyBotClient
    ) -> None:
        with patch("dailybot_cli.api_client.httpx.post") as post:
            result = _invoke(
                runner, real, ["task", "link", TASK, "ENG-99", "--type", "parent"], "task"
            )
        assert result.exit_code == EXIT_USAGE_ERROR
        assert "relates_to" in result.output
        post.assert_not_called()


# ---------------------------------------------------------------------------
# board create
# ---------------------------------------------------------------------------


class TestBoardCreateHasNoDescription:
    def test_description_is_refused_before_the_request(
        self, runner: CliRunner, real: DailyBotClient
    ) -> None:
        with patch("dailybot_cli.api_client.httpx.post") as post:
            result = _invoke(
                runner,
                real,
                [
                    "board",
                    "create",
                    "--project",
                    "00000000-0000-0000-0000-000000000002",
                    "--key",
                    "DSN",
                    "-n",
                    "Design",
                    "-d",
                    "x",
                    "--json",
                ],
                "board",
            )
        assert result.exit_code == EXIT_USAGE_ERROR
        post.assert_not_called()

    def test_the_create_body_has_no_description(
        self, runner: CliRunner, real: DailyBotClient
    ) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": BOARD}, 201)
        ) as post:
            result = _invoke(
                runner,
                real,
                [
                    "board",
                    "create",
                    "--project",
                    "00000000-0000-0000-0000-000000000002",
                    "--key",
                    "DSN",
                    "-n",
                    "Design",
                    "--json",
                ],
                "board",
            )
        assert result.exit_code == 0, result.output
        # No description, and exactly what the contract requires: name, project, key.
        assert post.call_args.kwargs["json"] == {
            "name": "Design",
            "project": "00000000-0000-0000-0000-000000000002",
            "key": "DSN",
        }
        assert json.loads(result.output)["uuid"] == BOARD

    def test_help_does_not_offer_description(self, runner: CliRunner) -> None:
        assert (
            "--description"
            not in runner.invoke(
                cli,
                [
                    "board",
                    "create",
                    "--project",
                    "00000000-0000-0000-0000-000000000002",
                    "--key",
                    "DSN",
                    "--help",
                ],
            ).output
        )


# ---------------------------------------------------------------------------
# tasks mine --scope and goal get (found by the developer-portal agent)
# ---------------------------------------------------------------------------


class TestMyTasksScope:
    @pytest.mark.parametrize(
        ("given", "sent"),
        [("owned", "owned"), ("participating", "participating"), ("involved", "involved"),
         ("assigned", "owned")],
    )  # fmt: skip
    def test_the_scope_on_the_wire(
        self, runner: CliRunner, real: DailyBotClient, given: str, sent: str
    ) -> None:
        envelope: dict[str, Any] = {"count": 0, "next": None, "previous": None, "results": []}
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(envelope)) as get:
            result = _invoke(runner, real, ["tasks", "mine", "--scope", given, "--json"], "tasks")
        assert result.exit_code == 0, result.output
        assert get.call_args.args[0] == f"{BASE}me/tasks/"
        assert get.call_args.kwargs["params"]["scope"] == sent

    @pytest.mark.parametrize("scope", ["created", "subscribed", "everything"])
    def test_undeclared_scopes_never_reach_the_server(
        self, runner: CliRunner, real: DailyBotClient, scope: str
    ) -> None:
        with patch("dailybot_cli.api_client.httpx.get") as get:
            result = _invoke(runner, real, ["tasks", "mine", "--scope", scope], "tasks")
        assert result.exit_code == EXIT_USAGE_ERROR
        get.assert_not_called()

    def test_help_lists_the_declared_scopes_only(self, runner: CliRunner) -> None:
        output: str = runner.invoke(cli, ["tasks", "mine", "--help"]).output
        assert "owned|participating|involved" in output
        assert "assigned" not in output


class TestGoalGetSendsNoInclude:
    def test_the_detail_read_sends_no_include(
        self, runner: CliRunner, real: DailyBotClient
    ) -> None:
        goal: dict[str, Any] = {"uuid": "g-1", "name": "Q4", "progress": None, "projects": []}
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(goal)) as get:
            result = _invoke(
                runner, real, ["goal", "get", "g-1", "--include", "progress", "--json"], "goal"
            )
        assert result.exit_code == 0, result.output
        assert get.call_args.args[0] == f"{BASE}goals/g-1/"
        assert not get.call_args.kwargs.get("params")
        assert "has no effect" in result.stderr

    def test_help_does_not_offer_include(self, runner: CliRunner) -> None:
        # The prose may point at `goal list --include`; no option line may offer it.
        output: str = runner.invoke(cli, ["goal", "get", "--help"]).output
        options: str = output.split("Options:", 1)[1]
        assert "--include" not in options
