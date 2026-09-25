"""`dailybot board` administration surfaces.

Reads: states, members, labels, views. Writes: board update, columns (create,
update, archive, restore, reorder), members (add, remove), labels (create) and
saved views (save). Every write is asserted on the exact wire against the
published Tasks API contract: body, path, and whether the
Idempotency-Key header is sent — present only where the door accepts one.
"""

import io
import json
from typing import Any
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
BASE: str = f"{API_URL}/v1/tasks/"
BOARD: str = "b-1"
STATE: str = "s-1"
USER: str = "u-1"

# (subcommand, client method, sub-path, a row that exercises the table)
READS: list[tuple[str, str, str, dict[str, Any]]] = [
    ("states", "list_board_states", "states", {"uuid": "s-1", "name": "Doing"}),
    ("members", "list_board_members", "members", {"user": {"uuid": "u-1", "name": "Jane"}}),
    ("labels", "list_board_labels", "labels", {"uuid": "l-1", "name": "bug"}),
]


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
    person: bool = True,
    stdin: str | None = None,
) -> Any:
    with (
        patch("dailybot_cli.commands.board.require_auth", return_value=client),
        patch("dailybot_cli.commands.board.get_token", return_value="tok" if person else None),
    ):
        return runner.invoke(cli, args, input=stdin)


def _headers(call: Any) -> dict[str, str]:
    return dict(call.kwargs.get("headers") or {})


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


class TestBoardCollectionReads:
    @pytest.mark.parametrize(("sub", "method", "path", "row"), READS)
    def test_the_client_hits_the_sub_collection(
        self, real: DailyBotClient, sub: str, method: str, path: str, row: dict[str, Any]
    ) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response([row])) as get:
            getattr(real, method)(BOARD)
        assert get.call_args.args[0] == f"{BASE}boards/{BOARD}/{path}/"

    @pytest.mark.parametrize(("sub", "method", "path", "row"), READS)
    def test_json_is_the_server_payload_unchanged(
        self, runner: CliRunner, client: MagicMock, sub: str, method: str, path: str, row: Any
    ) -> None:
        payload: dict[str, Any] = {"count": 1, "next": None, "previous": None, "results": [row]}
        getattr(client, method).return_value = payload
        result = _invoke(runner, client, ["board", sub, BOARD, "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == payload

    @pytest.mark.parametrize(("sub", "method", "path", "row"), READS)
    def test_a_plain_list_renders_as_a_table(
        self, runner: CliRunner, client: MagicMock, sub: str, method: str, path: str, row: Any
    ) -> None:
        getattr(client, method).return_value = [row]
        result = _invoke(runner, client, ["board", sub, BOARD])
        assert result.exit_code == 0, result.output
        name: str = row.get("name") or row["user"]["name"]
        assert name in result.output

    @pytest.mark.parametrize(("sub", "method", "path", "row"), READS)
    def test_an_invisible_board_exits_not_found(
        self, runner: CliRunner, client: MagicMock, sub: str, method: str, path: str, row: Any
    ) -> None:
        getattr(client, method).side_effect = APIError(404, "Not found.", code="not_found")
        result = _invoke(runner, client, ["board", sub, BOARD, "--json"])
        assert result.exit_code == EXIT_NOT_FOUND
        assert json.loads(result.output)["code"] == "not_found"

    def test_names_render_as_data_not_markup(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_board_states.return_value = [{"uuid": "s-1", "name": "[bold]x[/bold]"}]
        result = _invoke(runner, client, ["board", "states", BOARD])
        # Escaped and quoted: the brackets survive literally, so no style was applied.
        assert '"[bold]x[/bold]"' in result.output

    def test_states_hide_retired_columns_unless_asked(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response([])) as get:
            real.list_board_states(BOARD)
            assert not get.call_args.kwargs.get("params")
            real.list_board_states(BOARD, include_archived=True)
            assert get.call_args.kwargs["params"] == {"include_archived": "true"}

    def test_the_include_archived_flag_reaches_the_client(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_board_states.return_value = []
        _invoke(runner, client, ["board", "states", BOARD, "--include-archived"])
        assert client.list_board_states.call_args.kwargs == {"include_archived": True}

    def test_labels_refuse_an_api_key_before_the_request(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["board", "labels", BOARD, "--json"], person=False)
        assert result.exit_code == EXIT_NOT_AUTHENTICATED
        assert json.loads(result.output)["status"] == "error"
        client.list_board_labels.assert_not_called()

    @pytest.mark.parametrize("sub", ["states", "members"])
    def test_key_ok_reads_do_not_refuse_a_key(
        self, runner: CliRunner, client: MagicMock, sub: str
    ) -> None:
        getattr(client, f"list_board_{sub}").return_value = []
        result = _invoke(runner, client, ["board", sub, BOARD], person=False)
        assert result.exit_code == 0, result.output


class TestBoardViewsRead:
    def test_the_etag_leaves_with_the_views(self, real: DailyBotClient) -> None:
        response: Any = _response([{"uuid": "v-1"}], headers={"ETag": '"7"'})
        with patch("dailybot_cli.api_client.httpx.get", return_value=response) as get:
            data, etag = real.list_board_views_with_etag(BOARD)
        assert get.call_args.args[0] == f"{BASE}boards/{BOARD}/views/"
        assert data == [{"uuid": "v-1"}]
        assert etag == '"7"'

    def test_etag_flag_prints_only_the_validator(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_board_views_with_etag.return_value = ([{"uuid": "v-1"}], '"7"')
        result = _invoke(runner, client, ["board", "views", BOARD, "--etag"])
        assert result.exit_code == 0, result.output
        assert result.stdout == '"7"\n'

    def test_json_is_the_view_array_unchanged(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_board_views_with_etag.return_value = ([{"uuid": "v-1"}], '"7"')
        result = _invoke(runner, client, ["board", "views", BOARD, "--json"])
        assert json.loads(result.output) == [{"uuid": "v-1"}]

    def test_human_output_names_the_etag(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_board_views_with_etag.return_value = ([{"uuid": "v-1", "name": "Mine"}], '"7"')
        result = _invoke(runner, client, ["board", "views", BOARD])
        assert '"7"' in result.output


# ---------------------------------------------------------------------------
# Board update
# ---------------------------------------------------------------------------


class TestBoardUpdate:
    def test_the_wire_is_a_patch_with_a_key(self, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.patch", return_value=_response({"uuid": BOARD})
        ) as patch_:
            real.update_board(BOARD, name="New", key="DSN", idempotency_key="k-12345678")
        assert patch_.call_args.args[0] == f"{BASE}boards/{BOARD}/"
        assert patch_.call_args.kwargs["json"] == {"name": "New", "key": "DSN"}
        assert _headers(patch_.call_args)[IDEMPOTENCY_KEY_HEADER] == "k-12345678"

    def test_the_command_maps_every_flag_to_its_field(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.update_board.return_value = {"uuid": BOARD, "name": "New"}
        result = _invoke(
            runner,
            client,
            [
                "board", "update", BOARD, "-n", "New", "--key", "DSN",
                "--visibility", "members", "--estimate-scale", "fibonacci",
                "--archive-after-days", "30", "--project", "p-1", "--json",
            ],
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        assert client.update_board.call_args.kwargs == {
            "idempotency_key": None,
            "name": "New",
            "key": "DSN",
            "visibility": "members",
            "estimate_scale": "fibonacci",
            "archive_after_days": 30,
            "project": "p-1",
        }

    def test_description_is_not_a_board_field(self, runner: CliRunner) -> None:
        # BoardWrite has no `description`; offering it would earn a 400.
        result = runner.invoke(cli, ["board", "update", "--help"])
        assert "--description" not in result.output

    def test_an_empty_update_is_a_usage_error(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["board", "update", BOARD])
        assert result.exit_code == EXIT_USAGE_ERROR
        client.update_board.assert_not_called()

    def test_an_unknown_visibility_never_reaches_the_server(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["board", "update", BOARD, "--visibility", "secret"])
        assert result.exit_code == EXIT_USAGE_ERROR
        client.update_board.assert_not_called()

    def test_a_refusal_exits_with_the_documented_code(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.update_board.side_effect = APIError(
            403, "No.", code="insufficient_scope", extra={"required_scope": "tasks:admin"}
        )
        result = _invoke(runner, client, ["board", "update", BOARD, "-n", "x", "--json"])
        assert result.exit_code == EXIT_PERMISSION_DENIED
        assert json.loads(result.output)["code"] == "insufficient_scope"


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------


class TestStateWire:
    def test_create_posts_with_a_key(self, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": STATE})
        ) as post:
            real.create_board_state(BOARD, name="Review", category="in_progress", position=2)
        assert post.call_args.args[0] == f"{BASE}boards/{BOARD}/states/"
        assert post.call_args.kwargs["json"] == {
            "name": "Review",
            "category": "in_progress",
            "position": 2,
        }
        assert IDEMPOTENCY_KEY_HEADER in _headers(post.call_args)

    def test_update_patches_without_a_key(self, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.patch", return_value=_response({"uuid": STATE})
        ) as patch_:
            real.update_board_state(BOARD, STATE, name="Shipped")
        assert patch_.call_args.args[0] == f"{BASE}boards/{BOARD}/states/{STATE}/"
        assert patch_.call_args.kwargs["json"] == {"name": "Shipped"}
        assert IDEMPOTENCY_KEY_HEADER not in _headers(patch_.call_args)

    def test_archive_sends_migrate_to_and_the_dry_run_param(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({})) as post:
            real.archive_board_state(BOARD, STATE, migrate_to="s-2", dry_run=True)
        assert post.call_args.args[0] == f"{BASE}boards/{BOARD}/states/{STATE}/archive/"
        assert post.call_args.kwargs["json"] == {"migrate_to": "s-2"}
        assert post.call_args.kwargs["params"] == {"dry_run": "true"}
        assert IDEMPOTENCY_KEY_HEADER not in _headers(post.call_args)

    def test_archive_without_migrate_to_sends_no_body(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({})) as post:
            real.archive_board_state(BOARD, STATE)
        assert post.call_args.kwargs.get("json") is None

    def test_restore_posts_to_the_restore_door(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({})) as post:
            real.restore_board_state(BOARD, STATE)
        assert post.call_args.args[0] == f"{BASE}boards/{BOARD}/states/{STATE}/restore/"

    def test_reorder_sends_the_full_order(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response([])) as post:
            real.reorder_board_states(BOARD, ["a", "b", "c"])
        assert post.call_args.args[0] == f"{BASE}boards/{BOARD}/states/reorder/"
        assert post.call_args.kwargs["json"] == {"order": ["a", "b", "c"]}


class TestStateCommands:
    def test_create_maps_flags(self, runner: CliRunner, client: MagicMock) -> None:
        client.create_board_state.return_value = {"uuid": STATE, "name": "Review"}
        result = _invoke(
            runner,
            client,
            [
                "board", "state", "create", BOARD, "-n", "Review", "--category", "in_progress",
                "--position", "2", "--default", "--json",
            ],
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        kwargs: dict[str, Any] = client.create_board_state.call_args.kwargs
        assert kwargs["name"] == "Review"
        assert kwargs["category"] == "in_progress"
        assert kwargs["position"] == 2
        assert kwargs["is_default"] is True

    def test_create_refuses_an_unknown_category(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner, client, ["board", "state", "create", BOARD, "-n", "x", "--category", "blocked"]
        )
        assert result.exit_code == EXIT_USAGE_ERROR
        client.create_board_state.assert_not_called()

    def test_update_needs_a_field(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(runner, client, ["board", "state", "update", BOARD, STATE])
        assert result.exit_code == EXIT_USAGE_ERROR

    def test_archive_previews_first_and_dry_run_writes_nothing(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        preview: dict[str, Any] = {"dry_run": True, "consequence": "Retire column Doing."}
        client.archive_board_state.return_value = preview
        result = _invoke(
            runner, client, ["board", "state", "archive", BOARD, STATE, "--dry-run", "--json"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == preview
        assert client.archive_board_state.call_count == 1
        assert client.archive_board_state.call_args.kwargs["dry_run"] is True

    def test_archive_with_yes_previews_then_acts(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.archive_board_state.side_effect = [
            {"dry_run": True, "consequence": "Retire."},
            {"uuid": STATE, "is_archived": True},
        ]
        result = _invoke(
            runner,
            client,
            ["board", "state", "archive", BOARD, STATE, "--migrate-to", "s-2", "--yes", "--json"],
        )
        assert result.exit_code == 0, result.output
        final: Any = client.archive_board_state.call_args_list[-1]
        assert final.kwargs == {"migrate_to": "s-2"}

    def test_state_in_use_exits_permission_denied(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.archive_board_state.side_effect = [
            {"dry_run": True, "consequence": "Retire."},
            APIError(409, "In use.", code="state_in_use"),
        ]
        result = _invoke(
            runner, client, ["board", "state", "archive", BOARD, STATE, "--yes", "--json"]
        )
        assert result.exit_code == EXIT_PERMISSION_DENIED
        assert json.loads(result.stdout.splitlines()[-1])["code"] == "state_in_use"

    def test_reorder_refuses_a_duplicate_before_the_request(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["board", "state", "reorder", BOARD, "a", "b", "a"])
        assert result.exit_code == EXIT_USAGE_ERROR
        client.reorder_board_states.assert_not_called()

    def test_reorder_sends_the_order_given(self, runner: CliRunner, client: MagicMock) -> None:
        client.reorder_board_states.return_value = [{"uuid": "a"}, {"uuid": "b"}]
        result = _invoke(runner, client, ["board", "state", "reorder", BOARD, "b", "a", "--json"])
        assert result.exit_code == 0, result.output
        assert client.reorder_board_states.call_args.args == (BOARD, ["b", "a"])

    def test_reorder_invalid_is_a_usage_error(self, runner: CliRunner, client: MagicMock) -> None:
        client.reorder_board_states.side_effect = APIError(
            400, "Bad order.", code="states_reorder_invalid"
        )
        result = _invoke(runner, client, ["board", "state", "reorder", BOARD, "a", "--json"])
        assert result.exit_code == EXIT_USAGE_ERROR

    @pytest.mark.parametrize("sub", ["create", "update", "archive", "restore", "reorder"])
    def test_state_writes_accept_an_api_key(self, runner: CliRunner, sub: str) -> None:
        # Columns are tasks:admin, which organization keys may hold for these doors.
        result = runner.invoke(cli, ["board", "state", sub, "--help"])
        assert result.exit_code == 0
        assert "dailybot login" not in result.output


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


class TestMembers:
    def test_add_wire(self, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"user_uuid": USER})
        ) as post:
            real.add_board_member(BOARD, USER)
        assert post.call_args.args[0] == f"{BASE}boards/{BOARD}/members/"
        assert post.call_args.kwargs["json"] == {"user_uuid": USER}
        assert IDEMPOTENCY_KEY_HEADER in _headers(post.call_args)

    def test_remove_wire(self, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.request", return_value=_response(status=204)
        ) as request:
            real.remove_board_member(BOARD, USER)
        assert request.call_args.args[:2] == ("DELETE", f"{BASE}boards/{BOARD}/members/{USER}/")

    @pytest.mark.parametrize(
        "argv",
        [
            ["board", "member", "add", BOARD, USER, "--json"],
            ["board", "member", "remove", BOARD, USER, "--yes", "--json"],
        ],
    )
    def test_member_writes_refuse_a_key_before_the_request(
        self, runner: CliRunner, client: MagicMock, argv: list[str]
    ) -> None:
        # Member writes are `tasks:admin` doors: refused like the server's 403.
        result = _invoke(runner, client, argv, person=False)
        assert result.exit_code == EXIT_PERMISSION_DENIED
        assert json.loads(result.output)["code"] == "insufficient_scope"
        client.add_board_member.assert_not_called()
        client.remove_board_member.assert_not_called()

    def test_add_sends_the_user(self, runner: CliRunner, client: MagicMock) -> None:
        client.add_board_member.return_value = {"user_uuid": USER}
        result = _invoke(runner, client, ["board", "member", "add", BOARD, USER, "--json"])
        assert result.exit_code == 0, result.output
        assert client.add_board_member.call_args.args == (BOARD, USER)

    def test_remove_dry_run_sends_nothing(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner, client, ["board", "member", "remove", BOARD, USER, "--dry-run", "--json"]
        )
        assert result.exit_code == 0, result.output
        body: dict[str, Any] = json.loads(result.output)
        assert body["dry_run"] is True
        assert body["previewed_by"] == "client"
        client.remove_board_member.assert_not_called()

    def test_remove_declined_aborts_with_exit_seven(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["board", "member", "remove", BOARD, USER], stdin="n\n")
        assert result.exit_code == EXIT_USER_ABORTED
        client.remove_board_member.assert_not_called()

    def test_last_grant_is_a_conflict(self, runner: CliRunner, client: MagicMock) -> None:
        client.remove_board_member.side_effect = APIError(
            409, "Last member.", code="last_grant_cannot_be_removed"
        )
        result = _invoke(
            runner, client, ["board", "member", "remove", BOARD, USER, "--yes", "--json"]
        )
        assert result.exit_code == EXIT_PERMISSION_DENIED
        assert json.loads(result.output)["code"] == "last_grant_cannot_be_removed"

    def test_there_is_no_member_set_command(self, runner: CliRunner) -> None:
        # Membership has no role column; PATCH only inspects the grant.
        result = runner.invoke(cli, ["board", "member", "--help"])
        assert " set " not in result.output


# ---------------------------------------------------------------------------
# Labels and saved views
# ---------------------------------------------------------------------------


class TestBoardLabelCreate:
    def test_wire(self, real: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": "l-1"})
        ) as post:
            real.create_board_label(BOARD, name="bug", color="#ef4444")
        assert post.call_args.args[0] == f"{BASE}boards/{BOARD}/labels/"
        assert post.call_args.kwargs["json"] == {"name": "bug", "color": "#ef4444"}
        assert IDEMPOTENCY_KEY_HEADER not in _headers(post.call_args)

    def test_refuses_a_key(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner, client, ["board", "label", "create", BOARD, "-n", "bug", "--json"], person=False
        )
        assert result.exit_code == EXIT_NOT_AUTHENTICATED
        client.create_board_label.assert_not_called()

    def test_maps_flags(self, runner: CliRunner, client: MagicMock) -> None:
        client.create_board_label.return_value = {"uuid": "l-1", "name": "bug"}
        result = _invoke(
            runner, client, ["board", "label", "create", BOARD, "-n", "bug", "-d", "Defects"]
        )
        assert result.exit_code == 0, result.output
        assert client.create_board_label.call_args.kwargs == {
            "name": "bug",
            "color": None,
            "description": "Defects",
        }


class TestBoardViewSave:
    VIEWS: str = '[{"name": "Mine", "filters": {}}]'

    def test_wire_sends_if_match_and_the_array(self, real: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response([])) as put:
            real.save_board_views(BOARD, [{"name": "Mine", "filters": {}}], if_match='"7"')
        assert put.call_args.args[0] == f"{BASE}boards/{BOARD}/views/"
        assert put.call_args.kwargs["json"] == [{"name": "Mine", "filters": {}}]
        assert _headers(put.call_args)["If-Match"] == '"7"'
        assert IDEMPOTENCY_KEY_HEADER not in _headers(put.call_args)

    def test_if_match_is_passed_through(self, runner: CliRunner, client: MagicMock) -> None:
        client.save_board_views.return_value = []
        result = _invoke(
            runner,
            client,
            ["board", "view", "save", BOARD, "-f", "-", "--if-match", '"7"', "--json"],
            stdin=self.VIEWS,
        )
        assert result.exit_code == 0, result.output
        assert client.save_board_views.call_args.kwargs == {"if_match": '"7"'}
        client.list_board_views_with_etag.assert_not_called()

    def test_fetch_etag_reads_first(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_board_views_with_etag.return_value = ([], '"9"')
        client.save_board_views.return_value = []
        result = _invoke(
            runner,
            client,
            ["board", "view", "save", BOARD, "-f", "-", "--fetch-etag", "--json"],
            stdin=self.VIEWS,
        )
        assert result.exit_code == 0, result.output
        assert client.save_board_views.call_args.kwargs == {"if_match": '"9"'}

    @pytest.mark.parametrize("extra", [[], ["--if-match", '"1"', "--fetch-etag"]])
    def test_exactly_one_etag_source_is_required(
        self, runner: CliRunner, client: MagicMock, extra: list[str]
    ) -> None:
        result = _invoke(
            runner, client, ["board", "view", "save", BOARD, "-f", "-", *extra], stdin=self.VIEWS
        )
        assert result.exit_code == EXIT_USAGE_ERROR
        client.save_board_views.assert_not_called()

    def test_a_non_array_file_is_refused(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner,
            client,
            ["board", "view", "save", BOARD, "-f", "-", "--if-match", '"1"'],
            stdin='{"name": "x"}',
        )
        assert result.exit_code == EXIT_USAGE_ERROR
        client.save_board_views.assert_not_called()

    def test_refuses_a_key(self, runner: CliRunner, client: MagicMock) -> None:
        result = _invoke(
            runner,
            client,
            ["board", "view", "save", BOARD, "-f", "-", "--if-match", '"1"', "--json"],
            person=False,
            stdin=self.VIEWS,
        )
        assert result.exit_code == EXIT_NOT_AUTHENTICATED
        client.save_board_views.assert_not_called()

    def test_a_stale_etag_is_reported(self, runner: CliRunner, client: MagicMock) -> None:
        client.save_board_views.side_effect = APIError(412, "Stale.", code="precondition_failed")
        result = _invoke(
            runner,
            client,
            ["board", "view", "save", BOARD, "-f", "-", "--if-match", '"1"', "--json"],
            stdin=self.VIEWS,
        )
        assert result.exit_code != 0
        assert json.loads(result.output)["code"] == "precondition_failed"


def test_stdin_fixture_is_text() -> None:
    # Guard for the `-f -` path: click.File("r") reads text, so a JSON array
    # arrives as a str the loader can parse.
    assert json.load(io.StringIO(TestBoardViewSave.VIEWS))[0]["name"] == "Mine"


def test_a_client_side_dry_run_never_treats_ids_as_markup() -> None:
    # Found by the Final Review: the consequence sentence embeds caller-supplied
    # ids, and a bracketed id used to reach Rich as markup.
    client: MagicMock = MagicMock(spec=DailyBotClient)
    with (
        patch("dailybot_cli.commands.board.require_auth", return_value=client),
        patch("dailybot_cli.commands.board.get_token", return_value="tok"),
    ):
        result = CliRunner().invoke(
            cli, ["board", "member", "remove", "[bold]b[/bold]", "[red]u", "--dry-run"]
        )
    assert result.exit_code == 0, result.output
    assert "[bold]b[/bold]" in result.output
    assert "[red]u" in result.output


class TestSnapshotRendering:
    """The BoardSnapshot shape: groups[] with task_count (true total) and has_more."""

    SNAPSHOT: dict[str, Any] = {  # noqa: RUF012
        "board": {"uuid": BOARD, "key": "ENG", "name": "Engineering"},
        "generated_at": "2026-09-25T15:00:00Z",
        "delta_cursor": "2026-09-25T15:00:00Z",
        "group_by": "state",
        "groups": [
            {"key": "s-1", "name": "Doing", "category": "in_progress", "task_count": 2,
             "has_more": False, "tasks": [{"key": "ENG-1"}, {"key": "ENG-2"}]},
            {"key": "s-2", "name": "Done", "category": "done", "task_count": 73,
             "has_more": True, "tasks": [{"key": f"ENG-{i}"} for i in range(50)]},
        ],
    }  # fmt: skip

    def test_true_totals_and_more(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_board_snapshot.return_value = self.SNAPSHOT
        result = _invoke(runner, client, ["board", "snapshot", BOARD])
        assert result.exit_code == 0, result.output
        assert "ENG" in result.output
        assert "73 (+23 more)" in result.output
        assert "in_progress" in result.output
        assert "2026-09-25T15:00:00Z" in result.output
