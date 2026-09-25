"""Collaboration on one task (Tasks Beta PR3a).

Comments edit/delete, relations list/unlink, participants list/remove/role,
watch/unwatch and mute/unmute. Wire asserted against the published contract;
person-only doors (participants, subscription) refuse an API key before any
request, exactly where the contract lists no organization API key.
"""

import json
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import IDEMPOTENCY_KEY_HEADER, APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    EXIT_NOT_AUTHENTICATED,
    EXIT_NOT_FOUND,
    EXIT_PERMISSION_DENIED,
    EXIT_USAGE_ERROR,
    EXIT_USER_ABORTED,
)
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"
BASE: str = f"{API_URL}/v1/tasks/tasks/"
TASK: str = "ENG-142"
COMMENT: str = "c-1"
RELATION: str = "r-1"
USER: str = "u-1"
ME: str = "u-me"


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
    runner: CliRunner,
    client: Any,
    args: list[str],
    *,
    person: bool = True,
    stdin: str | None = None,
) -> Any:
    with (
        patch("dailybot_cli.commands.task.require_auth", return_value=client),
        patch("dailybot_cli.commands.task.get_token", return_value="tok" if person else None),
    ):
        return runner.invoke(cli, args, input=stdin)


def _headers(call: Any) -> dict[str, str]:
    return dict(call.kwargs.get("headers") or {})


# ---------------------------------------------------------------------------
# Wire
# ---------------------------------------------------------------------------


class TestWire:
    def test_comment_edit_patches_the_body_without_a_key(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.patch", return_value=_response({})) as patch_:
            real.update_task_comment(TASK, COMMENT, body="new")
        assert patch_.call_args.args[0] == f"{BASE}{TASK}/comments/{COMMENT}/"
        assert patch_.call_args.kwargs["json"] == {"body": "new"}
        assert IDEMPOTENCY_KEY_HEADER not in _headers(patch_.call_args)

    @pytest.mark.parametrize(
        ("method", "args", "path"),
        [
            ("delete_task_comment", (TASK, COMMENT), f"{TASK}/comments/{COMMENT}/"),
            ("delete_task_relation", (TASK, RELATION), f"{TASK}/relations/{RELATION}/"),
            ("remove_task_participant", (TASK, USER), f"{TASK}/participants/{USER}/"),
            ("unsubscribe_task", (TASK,), f"{TASK}/subscription/"),
        ],
    )
    def test_deletes_hit_their_door(
        self, real: DailyBotClient, method: str, args: tuple[str, ...], path: str
    ) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.request", return_value=_response(status=204)
        ) as request:
            getattr(real, method)(*args)
        assert request.call_args.args[:2] == ("DELETE", f"{BASE}{path}")

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("list_task_relations", "relations"),
            ("list_task_participants", "participants"),
        ],
    )
    def test_reads_hit_their_door(self, real: DailyBotClient, method: str, path: str) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response([])) as get:
            getattr(real, method)(TASK)
        assert get.call_args.args[0] == f"{BASE}{TASK}/{path}/"

    def test_participant_role_and_mute_ride_the_same_door(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({})) as post:
            real.add_task_participant(TASK, user_uuid=USER, role="watcher", is_muted=True)
        assert post.call_args.args[0] == f"{BASE}{TASK}/participants/"
        assert post.call_args.kwargs["json"] == {
            "user_uuid": USER,
            "role": "watcher",
            "is_muted": True,
        }
        assert IDEMPOTENCY_KEY_HEADER in _headers(post.call_args)

    def test_a_plain_add_sends_only_the_user(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({})) as post:
            real.add_task_participant(TASK, user_uuid=USER)
        assert post.call_args.kwargs["json"] == {"user_uuid": USER}

    def test_watch_sends_no_key(self, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"subscribed": True})
        ) as post:
            real.subscribe_task(TASK)
        assert post.call_args.args[0] == f"{BASE}{TASK}/subscription/"
        assert IDEMPOTENCY_KEY_HEADER not in _headers(post.call_args)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


class TestComments:
    def test_edit_sends_the_new_body(self, runner: CliRunner, client: MagicMock) -> None:
        client.update_task_comment.return_value = {"uuid": COMMENT, "body": "new"}
        result = _invoke(runner, client, ["task", "comment-edit", TASK, COMMENT, "new", "--json"])
        assert result.exit_code == 0, result.output
        assert client.update_task_comment.call_args.args == (TASK, COMMENT)
        assert client.update_task_comment.call_args.kwargs == {"body": "new"}

    def test_edit_reads_stdin_on_dash(self, runner: CliRunner, client: MagicMock) -> None:
        client.update_task_comment.return_value = {"uuid": COMMENT}
        result = _invoke(
            runner, client, ["task", "comment-edit", TASK, COMMENT, "-"], stdin="from stdin\n"
        )
        assert result.exit_code == 0, result.output
        assert client.update_task_comment.call_args.kwargs == {"body": "from stdin"}

    def test_an_empty_edit_is_refused(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["task", "comment-edit", TASK, COMMENT, "-"], stdin="\n")
        assert result.exit_code == EXIT_USAGE_ERROR
        client.update_task_comment.assert_not_called()

    def test_editing_someone_elses_comment_is_refused(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.update_task_comment.side_effect = APIError(403, "Not yours.", code="forbidden")
        result = _invoke(runner, client, ["task", "comment-edit", TASK, COMMENT, "x", "--json"])
        assert result.exit_code == EXIT_PERMISSION_DENIED

    def test_delete_dry_run_sends_nothing(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner, client, ["task", "comment-delete", TASK, COMMENT, "--dry-run", "--json"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["dry_run"] is True
        client.delete_task_comment.assert_not_called()

    def test_delete_with_yes_acts(self, runner: CliRunner, client: MagicMock) -> None:
        client.delete_task_comment.return_value = {}
        result = _invoke(
            runner, client, ["task", "comment-delete", TASK, COMMENT, "--yes", "--json"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {"deleted": True, "task": TASK, "comment": COMMENT}

    def test_delete_declined_aborts(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["task", "comment-delete", TASK, COMMENT], stdin="n\n")
        assert result.exit_code == EXIT_USER_ABORTED
        client.delete_task_comment.assert_not_called()


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------


class TestRelations:
    ROW: ClassVar[dict[str, Any]] = {
        "uuid": RELATION,
        "relation_type": "blocks",
        "direction": "incoming",
        "other_task": {"uuid": "t-2", "key": "ENG-9", "title": "[red]x[/red]"},
    }

    def test_list_json_is_the_server_payload(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_task_relations.return_value = [self.ROW]
        result = _invoke(runner, client, ["task", "relations", TASK, "--json"])
        assert json.loads(result.output) == [self.ROW]

    def test_list_renders_titles_as_data(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_task_relations.return_value = {"results": [self.ROW]}
        result = _invoke(runner, client, ["task", "relations", TASK])
        assert result.exit_code == 0, result.output
        assert '"[red]x[/red]"' in result.output
        assert "ENG-9" in result.output

    def test_unlink_dry_run_sends_nothing(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["task", "unlink", TASK, RELATION, "--dry-run"])
        assert result.exit_code == 0, result.output
        client.delete_task_relation.assert_not_called()

    def test_unlink_with_yes_acts(self, runner: CliRunner, client: MagicMock) -> None:
        client.delete_task_relation.return_value = {}
        result = _invoke(runner, client, ["task", "unlink", TASK, RELATION, "--yes", "--json"])
        assert result.exit_code == 0, result.output
        assert client.delete_task_relation.call_args.args == (TASK, RELATION)

    def test_unlink_accepts_an_api_key(self, runner: CliRunner, client: MagicMock) -> None:
        client.delete_task_relation.return_value = {}
        result = _invoke(runner, client, ["task", "unlink", TASK, RELATION, "--yes"], person=False)
        assert result.exit_code == 0, result.output

    def test_an_unknown_relation_is_not_found(self, runner: CliRunner, client: MagicMock) -> None:
        client.delete_task_relation.side_effect = APIError(404, "Gone.", code="not_found")
        result = _invoke(runner, client, ["task", "unlink", TASK, RELATION, "--yes", "--json"])
        assert result.exit_code == EXIT_NOT_FOUND


# ---------------------------------------------------------------------------
# Participants, watch, mute
# ---------------------------------------------------------------------------


class TestParticipants:
    def test_list_renders_members(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_task_participants.return_value = [
            {"member": {"uuid": USER, "name": "Jane"}, "role": "watcher", "is_muted": False}
        ]
        result = _invoke(runner, client, ["task", "participants", "list", TASK])
        assert result.exit_code == 0, result.output
        assert "Jane" in result.output and "watcher" in result.output

    def test_add_takes_a_role(self, runner: CliRunner, client: MagicMock) -> None:
        client.add_task_participant.return_value = {"role": "watcher"}
        result = _invoke(
            runner,
            client,
            ["task", "participants", "add", TASK, "--user", USER, "--role", "watcher", "--json"],
        )
        assert result.exit_code == 0, result.output
        assert client.add_task_participant.call_args.kwargs["role"] == "watcher"

    def test_remove_with_yes_acts(self, runner: CliRunner, client: MagicMock) -> None:
        client.remove_task_participant.return_value = {}
        result = _invoke(
            runner, client, ["task", "participants", "remove", TASK, USER, "--yes", "--json"]
        )
        assert result.exit_code == 0, result.output
        assert client.remove_task_participant.call_args.args == (TASK, USER)

    @pytest.mark.parametrize(
        "argv",
        [
            ["task", "participants", "remove", TASK, USER, "--yes", "--json"],
            ["task", "watch", TASK, "--json"],
            ["task", "unwatch", TASK, "--json"],
            ["task", "mute", TASK, "--json"],
            ["task", "unmute", TASK, "--json"],
        ],
    )
    def test_person_only_doors_refuse_a_key_before_the_request(
        self, runner: CliRunner, client: MagicMock, argv: list[str]
    ) -> None:
        result = _invoke(runner, client, argv, person=False)
        assert result.exit_code == EXIT_NOT_AUTHENTICATED
        assert json.loads(result.output)["status"] == "error"
        for method in (
            "remove_task_participant",
            "subscribe_task",
            "unsubscribe_task",
            "add_task_participant",
            "get_me",
        ):
            getattr(client, method).assert_not_called()


class TestWatchAndMute:
    def test_watch(self, runner: CliRunner, client: MagicMock) -> None:
        client.subscribe_task.return_value = {"subscribed": True}
        result = _invoke(runner, client, ["task", "watch", TASK, "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {"subscribed": True}

    def test_unwatch(self, runner: CliRunner, client: MagicMock) -> None:
        client.unsubscribe_task.return_value = {}
        result = _invoke(runner, client, ["task", "unwatch", TASK, "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {"subscribed": False, "task": TASK}

    @pytest.mark.parametrize(("sub", "muted"), [("mute", True), ("unmute", False)])
    def test_mute_posts_yourself_with_is_muted(
        self, runner: CliRunner, client: MagicMock, sub: str, muted: bool
    ) -> None:
        client.get_me.return_value = {"uuid": ME}
        client.add_task_participant.return_value = {"is_muted": muted}
        result = _invoke(runner, client, ["task", sub, TASK, "--json"])
        assert result.exit_code == 0, result.output
        assert client.add_task_participant.call_args.args == (TASK,)
        assert client.add_task_participant.call_args.kwargs == {"user_uuid": ME, "is_muted": muted}

    def test_mute_without_an_identity_stops(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_me.return_value = {}
        result = _invoke(runner, client, ["task", "mute", TASK])
        assert result.exit_code != 0
        client.add_task_participant.assert_not_called()
