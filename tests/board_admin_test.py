"""`dailybot board` administration surfaces (Tasks Beta PR2).

Reads first: states, members, labels and views. Each is one GET on the board's
sub-collection, emitted unchanged under `--json`; user-typed names render as data.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import EXIT_NOT_AUTHENTICATED, EXIT_NOT_FOUND
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"
BOARD: str = "b-1"

# (subcommand, client method, sub-path, a row that exercises the table)
READS: list[tuple[str, str, str, dict[str, Any]]] = [
    ("states", "list_board_states", "states", {"uuid": "s-1", "name": "Doing"}),
    ("members", "list_board_members", "members", {"user": {"uuid": "u-1", "name": "Jane"}}),
    ("labels", "list_board_labels", "labels", {"uuid": "l-1", "name": "bug"}),
    ("views", "list_board_views", "views", {"uuid": "v-1", "name": "Mine"}),
]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


def _invoke(runner: CliRunner, client: MagicMock, args: list[str], *, person: bool = True) -> Any:
    with (
        patch("dailybot_cli.commands.board.require_auth", return_value=client),
        patch("dailybot_cli.commands.board.get_token", return_value="tok" if person else None),
    ):
        return runner.invoke(cli, args)


class TestBoardCollectionReads:
    @pytest.mark.parametrize(("sub", "method", "path", "row"), READS)
    def test_the_client_hits_the_sub_collection(
        self, sub: str, method: str, path: str, row: dict[str, Any]
    ) -> None:
        real: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
        response: MagicMock = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.json.return_value = [row]
        response.headers = {}
        with patch("dailybot_cli.api_client.httpx.get", return_value=response) as get:
            getattr(real, method)(BOARD)
        assert get.call_args.args[0] == f"{API_URL}/v1/tasks/boards/{BOARD}/{path}/"

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

    def test_labels_refuse_an_api_key_before_the_request(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        result = _invoke(runner, client, ["board", "labels", BOARD, "--json"], person=False)
        assert result.exit_code == EXIT_NOT_AUTHENTICATED
        assert json.loads(result.output)["status"] == "error"
        client.list_board_labels.assert_not_called()

    @pytest.mark.parametrize("sub", ["states", "members", "views"])
    def test_key_ok_reads_do_not_refuse_a_key(
        self, runner: CliRunner, client: MagicMock, sub: str
    ) -> None:
        getattr(client, f"list_board_{sub}").return_value = []
        result = _invoke(runner, client, ["board", sub, BOARD], person=False)
        assert result.exit_code == 0, result.output
