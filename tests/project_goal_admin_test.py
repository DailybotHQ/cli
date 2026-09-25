"""Projects and goals reach web parity (Tasks Beta PR5).

Project update/restore, members (person-only), saved views (If-Match), per-project
updates, update-post health + key (R4), milestone create/update/delete, and goal
update (declared status)/restore/link/unlink. Wire asserted against the contract.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import (
    IDEMPOTENCY_KEY_HEADER,
    APIError,
    DailyBotClient,
    PaginatedResult,
)
from dailybot_cli.commands.public_api_helpers import (
    EXIT_NOT_AUTHENTICATED,
    EXIT_PERMISSION_DENIED,
    EXIT_USAGE_ERROR,
)
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"
BASE: str = f"{API_URL}/v1/tasks/"
PROJECT: str = "p-1"
GOAL: str = "g-1"
MILESTONE: str = "m-1"
USER: str = "u-1"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


@pytest.fixture
def real() -> DailyBotClient:
    return DailyBotClient(api_url=API_URL, token="test-token")


def _response(payload: Any = None, status: int = 200, headers: dict[str, str] | None = None) -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = {} if payload is None else payload
    mock.headers = headers or {}
    return mock


def _invoke(
    runner: CliRunner,
    client: Any,
    args: list[str],
    *,
    module: str = "project",
    person: bool = True,
    stdin: str | None = None,
) -> Any:
    with (
        patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
        patch("dailybot_cli.commands.project.get_token", return_value="tok" if person else None),
    ):
        return runner.invoke(cli, args, input=stdin)


def _headers(call: Any) -> dict[str, str]:
    return dict(call.kwargs.get("headers") or {})


# ---------------------------------------------------------------------------
# Wire
# ---------------------------------------------------------------------------


class TestProjectWire:
    def test_update_patches_with_a_key(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.patch", return_value=_response({})) as patch_:
            real.update_project(PROJECT, health="at_risk", target_date="2027-01-15")
        assert patch_.call_args.args[0] == f"{BASE}projects/{PROJECT}/"
        assert patch_.call_args.kwargs["json"] == {"health": "at_risk", "target_date": "2027-01-15"}
        assert IDEMPOTENCY_KEY_HEADER in _headers(patch_.call_args)

    def test_restore_posts_with_a_key(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({})) as post:
            real.restore_project(PROJECT)
        assert post.call_args.args[0] == f"{BASE}projects/{PROJECT}/restore/"
        assert IDEMPOTENCY_KEY_HEADER in _headers(post.call_args)

    @pytest.mark.parametrize(
        ("kwargs", "body"),
        [({"user_uuid": USER}, {"user_uuid": USER}), ({"team_uuid": "t-1"}, {"team_uuid": "t-1"})],
    )
    def test_member_add_sends_exactly_one_subject(
        self, real: DailyBotClient, kwargs: dict[str, str], body: dict[str, str]
    ) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({}, 201)) as post:
            real.add_project_member(PROJECT, **kwargs)
        assert post.call_args.args[0] == f"{BASE}projects/{PROJECT}/members/"
        assert post.call_args.kwargs["json"] == body
        assert IDEMPOTENCY_KEY_HEADER not in _headers(post.call_args)

    def test_member_remove(self, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.request", return_value=_response(status=204)
        ) as request:
            real.remove_project_member(PROJECT, USER)
        assert request.call_args.args[:2] == ("DELETE", f"{BASE}projects/{PROJECT}/members/{USER}/")

    def test_views_save_sends_if_match(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response([])) as put:
            real.save_project_views(PROJECT, [{"name": "v", "filters": {}}], if_match='"2"')
        assert put.call_args.args[0] == f"{BASE}projects/{PROJECT}/views/"
        assert _headers(put.call_args)["If-Match"] == '"2"'

    @pytest.mark.parametrize(
        ("project", "path"),
        [(None, "projects/updates/"), (PROJECT, f"projects/{PROJECT}/updates/")],
    )
    def test_updates_feed_path(self, real: DailyBotClient, project: Any, path: str) -> None:
        envelope: dict[str, Any] = {"count": 0, "next": None, "previous": None, "results": []}
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(envelope)) as get:
            real.list_project_updates(project)
        assert get.call_args.args[0] == f"{BASE}{path}"

    def test_update_post_sends_health_and_a_key(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({}, 201)) as post:
            real.post_project_update(
                PROJECT, body="done", health="on_track", idempotency_key="k-1234567"
            )
        assert post.call_args.kwargs["json"] == {"body": "done", "health": "on_track"}
        assert _headers(post.call_args)[IDEMPOTENCY_KEY_HEADER] == "k-1234567"

    def test_milestone_crud_wire(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({}, 201)) as post:
            real.create_milestone(PROJECT, name="Beta", date="2026-11-01")
        assert post.call_args.args[0] == f"{BASE}projects/{PROJECT}/milestones/"
        assert post.call_args.kwargs["json"] == {"name": "Beta", "date": "2026-11-01"}
        assert IDEMPOTENCY_KEY_HEADER not in _headers(post.call_args)
        with patch("dailybot_cli.api_client.httpx.patch", return_value=_response({})) as patch_:
            real.update_milestone(PROJECT, MILESTONE, date="2026-11-15")
        assert patch_.call_args.args[0] == f"{BASE}projects/{PROJECT}/milestones/{MILESTONE}/"
        assert patch_.call_args.kwargs["json"] == {"date": "2026-11-15"}
        with patch(
            "dailybot_cli.api_client.httpx.request", return_value=_response(status=204)
        ) as request:
            real.delete_milestone(PROJECT, MILESTONE)
        assert request.call_args.args[:2] == (
            "DELETE",
            f"{BASE}projects/{PROJECT}/milestones/{MILESTONE}/",
        )

    def test_milestone_complete_and_reopen_send_a_key(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({})) as post:
            real.complete_milestone(PROJECT, MILESTONE)
            assert IDEMPOTENCY_KEY_HEADER in _headers(post.call_args)
            real.reopen_milestone(PROJECT, MILESTONE)
            assert IDEMPOTENCY_KEY_HEADER in _headers(post.call_args)

    def test_a_milestone_preview_sends_no_key(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({})) as post:
            real.complete_milestone(PROJECT, MILESTONE, dry_run=True)
        assert IDEMPOTENCY_KEY_HEADER not in _headers(post.call_args)


class TestGoalWire:
    def test_update_patches_without_a_key(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.patch", return_value=_response({})) as patch_:
            real.update_goal(GOAL, status="at_risk")
        assert patch_.call_args.args[0] == f"{BASE}goals/{GOAL}/"
        assert patch_.call_args.kwargs["json"] == {"status": "at_risk"}
        assert IDEMPOTENCY_KEY_HEADER not in _headers(patch_.call_args)

    def test_restore_link_unlink(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({})) as post:
            real.restore_goal(GOAL)
            assert post.call_args.args[0] == f"{BASE}goals/{GOAL}/restore/"
            real.link_goal_project(GOAL, PROJECT)
            assert post.call_args.args[0] == f"{BASE}goals/{GOAL}/projects/"
            assert post.call_args.kwargs["json"] == {"project": PROJECT}
        with patch(
            "dailybot_cli.api_client.httpx.request", return_value=_response(status=204)
        ) as request:
            real.unlink_goal_project(GOAL, PROJECT)
        assert request.call_args.args[:2] == ("DELETE", f"{BASE}goals/{GOAL}/projects/{PROJECT}/")


# ---------------------------------------------------------------------------
# Project commands
# ---------------------------------------------------------------------------


class TestProjectCommands:
    def test_update_maps_flags_and_dates(self, runner: CliRunner, client: MagicMock) -> None:
        client.update_project.return_value = {"uuid": PROJECT, "name": "Apollo"}
        result = _invoke(
            runner,
            client,
            [
                "project", "update", PROJECT, "--health", "at_risk", "--lead", USER,
                "--start-date", "2026-10-01", "--target-date", "2026-12-15",
                "--visibility", "members", "--json",
            ],
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        assert client.update_project.call_args.kwargs == {
            "idempotency_key": None,
            "visibility": "members",
            "lead": USER,
            "health": "at_risk",
            "start_date": "2026-10-01",
            "target_date": "2026-12-15",
        }

    @pytest.mark.parametrize(
        "extra",
        [
            [],
            ["--health", "fine"],
            ["--start-date", "2026-12-15", "--target-date", "2026-10-01"],
            ["--target-date", "15/12/2026"],
        ],
    )
    def test_update_refuses_bad_input_before_the_request(
        self, runner: CliRunner, client: MagicMock, extra: list[str]
    ) -> None:
        result = _invoke(runner, client, ["project", "update", PROJECT, *extra])
        assert result.exit_code == EXIT_USAGE_ERROR
        client.update_project.assert_not_called()

    def test_create_takes_the_same_fields(self, runner: CliRunner, client: MagicMock) -> None:
        client.create_project.return_value = {"uuid": PROJECT, "name": "Apollo"}
        result = _invoke(
            runner, client, ["project", "create", "-n", "Apollo", "--health", "on_track", "--json"]
        )
        assert result.exit_code == 0, result.output
        assert client.create_project.call_args.kwargs["health"] == "on_track"

    def test_restore(self, runner: CliRunner, client: MagicMock) -> None:
        client.restore_project.return_value = {"uuid": PROJECT, "is_archived": False}
        result = _invoke(runner, client, ["project", "restore", PROJECT, "--json"])
        assert result.exit_code == 0, result.output

    def test_restore_out_of_slots_is_refused(self, runner: CliRunner, client: MagicMock) -> None:
        client.restore_project.side_effect = APIError(
            402, "No slots.", code="plan_upgrade_required"
        )
        result = _invoke(runner, client, ["project", "restore", PROJECT, "--json"])
        assert result.exit_code == EXIT_PERMISSION_DENIED

    @pytest.mark.parametrize(
        "argv",
        [
            ["project", "members", PROJECT, "--json"],
            ["project", "member", "add", PROJECT, "--user", USER, "--json"],
            ["project", "member", "remove", PROJECT, USER, "--yes", "--json"],
            ["project", "view", "save", PROJECT, "-f", "-", "--if-match", '"1"', "--json"],
        ],
    )
    def test_person_only_doors_refuse_a_key(
        self, runner: CliRunner, client: MagicMock, argv: list[str]
    ) -> None:
        result = _invoke(runner, client, argv, person=False, stdin="[]")
        assert result.exit_code == EXIT_NOT_AUTHENTICATED
        assert json.loads(result.output)["status"] == "error"
        for method in (
            "list_project_members",
            "add_project_member",
            "remove_project_member",
            "save_project_views",
        ):
            getattr(client, method).assert_not_called()

    @pytest.mark.parametrize("extra", [[], ["--user", USER, "--team", "t-1"]])
    def test_member_add_needs_exactly_one_subject(
        self, runner: CliRunner, client: MagicMock, extra: list[str]
    ) -> None:
        result = _invoke(runner, client, ["project", "member", "add", PROJECT, *extra])
        assert result.exit_code == EXIT_USAGE_ERROR
        client.add_project_member.assert_not_called()

    def test_member_add_a_team(self, runner: CliRunner, client: MagicMock) -> None:
        client.add_project_member.return_value = {"subject_type": "team"}
        result = _invoke(
            runner, client, ["project", "member", "add", PROJECT, "--team", "t-1", "--json"]
        )
        assert result.exit_code == 0, result.output
        assert client.add_project_member.call_args.kwargs == {"user_uuid": None, "team_uuid": "t-1"}

    def test_member_remove_dry_run(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner, client, ["project", "member", "remove", PROJECT, USER, "--dry-run"]
        )
        assert result.exit_code == 0, result.output
        client.remove_project_member.assert_not_called()

    def test_views_and_etag(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_project_views_with_etag.return_value = ([{"uuid": "v-1"}], '"4"')
        result = _invoke(runner, client, ["project", "views", PROJECT, "--etag"])
        assert result.stdout == '"4"\n'

    def test_view_save_fetches_the_etag(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_project_views_with_etag.return_value = ([], '"4"')
        client.save_project_views.return_value = []
        result = _invoke(
            runner,
            client,
            ["project", "view", "save", PROJECT, "-f", "-", "--fetch-etag", "--json"],
            stdin='[{"name": "v", "filters": {}}]',
        )
        assert result.exit_code == 0, result.output
        assert client.save_project_views.call_args.kwargs == {"if_match": '"4"'}

    def test_updates_for_one_project(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_project_updates.return_value = PaginatedResult(
            results=[], count=0, next=None, previous=None
        )
        result = _invoke(runner, client, ["project", "updates", PROJECT, "--json"])
        assert result.exit_code == 0, result.output
        assert client.list_project_updates.call_args.args == (PROJECT,)

    def test_update_post_health_and_key(self, runner: CliRunner, client: MagicMock) -> None:
        client.post_project_update.return_value = {"uuid": "u-1"}
        result = _invoke(
            runner,
            client,
            [
                "project", "update-post", PROJECT, "done", "--health", "on_track",
                "--idempotency-key", "k-12345678", "--json",
            ],
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        assert client.post_project_update.call_args.kwargs == {
            "body": "done",
            "health": "on_track",
            "idempotency_key": "k-12345678",
        }

    def test_milestone_create(self, runner: CliRunner, client: MagicMock) -> None:
        client.create_milestone.return_value = {"uuid": MILESTONE, "name": "Beta"}
        result = _invoke(
            runner,
            client,
            ["project", "milestone-create", PROJECT, "-n", "Beta", "--date", "2026-11-01"],
        )
        assert result.exit_code == 0, result.output
        assert client.create_milestone.call_args.kwargs == {
            "name": "Beta",
            "date": "2026-11-01",
            "description": None,
        }

    def test_milestone_create_needs_a_date(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["project", "milestone-create", PROJECT, "-n", "Beta"])
        assert result.exit_code == EXIT_USAGE_ERROR

    def test_milestone_update_needs_a_field(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["project", "milestone-update", PROJECT, MILESTONE])
        assert result.exit_code == EXIT_USAGE_ERROR

    def test_milestone_delete_confirms(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner, client, ["project", "milestone-delete", PROJECT, MILESTONE, "--dry-run"]
        )
        assert result.exit_code == 0, result.output
        client.delete_milestone.assert_not_called()
        client.delete_milestone.return_value = {}
        result = _invoke(
            runner, client, ["project", "milestone-delete", PROJECT, MILESTONE, "--yes", "--json"]
        )
        assert json.loads(result.output)["retired"] is True


# ---------------------------------------------------------------------------
# Goal commands
# ---------------------------------------------------------------------------


class TestGoalCommands:
    def test_update_declares_status(self, runner: CliRunner, client: MagicMock) -> None:
        client.update_goal.return_value = {"uuid": GOAL, "status": "at_risk"}
        result = _invoke(
            runner, client, ["goal", "update", GOAL, "--status", "at_risk", "--json"], module="goal"
        )
        assert result.exit_code == 0, result.output
        assert client.update_goal.call_args.kwargs == {"status": "at_risk"}

    @pytest.mark.parametrize(
        "extra",
        [
            [],
            ["--status", "blocked"],
            ["--period-start", "2026-12-31", "--period-end", "2026-10-01"],
        ],
    )
    def test_update_refuses_bad_input(
        self, runner: CliRunner, client: MagicMock, extra: list[str]
    ) -> None:
        result = _invoke(runner, client, ["goal", "update", GOAL, *extra], module="goal")
        assert result.exit_code == EXIT_USAGE_ERROR
        client.update_goal.assert_not_called()

    def test_restore_name_conflict(self, runner: CliRunner, client: MagicMock) -> None:
        client.restore_goal.side_effect = APIError(409, "Taken.", code="goal_name_conflict")
        result = _invoke(runner, client, ["goal", "restore", GOAL, "--json"], module="goal")
        assert result.exit_code == EXIT_PERMISSION_DENIED
        assert json.loads(result.output)["code"] == "goal_name_conflict"

    def test_link(self, runner: CliRunner, client: MagicMock) -> None:
        client.link_goal_project.return_value = {"uuid": GOAL, "projects": [{"uuid": PROJECT}]}
        result = _invoke(runner, client, ["goal", "link", GOAL, PROJECT, "--json"], module="goal")
        assert result.exit_code == 0, result.output
        assert client.link_goal_project.call_args.args == (GOAL, PROJECT)

    def test_unlink_confirms(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner, client, ["goal", "unlink", GOAL, PROJECT, "--dry-run"], module="goal"
        )
        assert result.exit_code == 0, result.output
        client.unlink_goal_project.assert_not_called()
        client.unlink_goal_project.return_value = {}
        result = _invoke(
            runner, client, ["goal", "unlink", GOAL, PROJECT, "--yes", "--json"], module="goal"
        )
        assert json.loads(result.output)["unlinked"] is True
