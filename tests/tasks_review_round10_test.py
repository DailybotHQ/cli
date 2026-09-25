"""Regression tests for the CI AI review's tenth pass on PR #85.

Five findings, and the interesting thing about them is the calibre: no structural
defect survived this round. Two are the previous rounds' fixes landing one step
short — `report_write` printed "pass it with --idempotency-key" on a command that
did not declare the flag, and the TTL constant existed twice again — and two are
things the round-9 change itself introduced (a helper written and never wired, a
project-structure entry never added).

The remaining one is older and is the only behavioural defect here: `tasks search`
silently truncated a too-long query and answered a different question with exit 0.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import (
    IDEMPOTENCY_KEY_SENT_KEY,
    MAX_SEARCH_QUERY_LENGTH,
    APIError,
    DailyBotClient,
)
from dailybot_cli.commands._writes import IDEMPOTENCY_TTL_HOURS, named
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


@pytest.fixture
def real_client() -> DailyBotClient:
    return DailyBotClient(api_url="http://t.example.com", token="t", api_key="k")


_PREVIEW: dict[str, Any] = {"operation": "task.archive", "dry_run": True, "reversible": True}


class TestTheKeyHintNamesAFlagTheCommandHas:
    """Finding 1: `task delete` printed advice it could not accept.

    The alias posts to the same archive door, which honours `Idempotency-Key`, so
    `report_write` echoed the key and told the caller to pass it back — through an
    option `task delete` did not declare. Following the CLI's own hint after a
    timeout was a Click usage error; not following it lost the replay guarantee.
    """

    def test_the_flag_exists(self, runner: CliRunner) -> None:
        assert "--idempotency-key" in runner.invoke(cli, ["task", "delete", "--help"]).stdout

    def test_it_reaches_the_client(self, runner: CliRunner, client: MagicMock) -> None:
        client.archive_task.side_effect = [_PREVIEW, {"uuid": "t-1"}]
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            runner.invoke(cli, ["task", "delete", "t-1", "--yes", "--idempotency-key", "mine-1"])
        assert client.archive_task.call_args[1]["idempotency_key"] == "mine-1"

    def test_the_hint_is_actionable(self, runner: CliRunner, client: MagicMock) -> None:
        client.archive_task.side_effect = [
            _PREVIEW,
            {"uuid": "t-1", IDEMPOTENCY_KEY_SENT_KEY: "key-9"},
        ]
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(cli, ["task", "delete", "t-1", "--yes"])
        assert "key-9" in result.stdout
        # And the flag it names is one this command really takes.
        replay = runner.invoke(cli, ["task", "delete", "--help"]).stdout
        assert "--idempotency-key" in replay


class TestATooLongQueryIsRefusedNotTruncated:
    """Finding 2: `tasks search` answered a question the caller did not ask.

    Every other search path in the client raises `search_query_too_long`. This one
    sliced the string and returned results for the prefix, with exit 0 — so a
    caller concluded the text was absent from the workspace.
    """

    def test_the_client_refuses(self, real_client: DailyBotClient) -> None:
        with pytest.raises(APIError) as caught:
            real_client.search_tasks("x" * (MAX_SEARCH_QUERY_LENGTH + 1))
        assert caught.value.code == "search_query_too_long"

    def test_no_request_is_made(self, real_client: DailyBotClient) -> None:
        with patch("httpx.get") as mock_get, pytest.raises(APIError):
            real_client.search_tasks("x" * (MAX_SEARCH_QUERY_LENGTH + 1))
        mock_get.assert_not_called()

    def test_a_query_at_the_ceiling_is_sent_whole(self, real_client: DailyBotClient) -> None:
        ok: MagicMock = MagicMock(spec=httpx.Response)
        ok.status_code = 200
        ok.json.return_value = {"count": 0, "next": None, "previous": None, "results": []}
        ok.headers = {}
        query: str = "x" * MAX_SEARCH_QUERY_LENGTH
        with patch("httpx.get", return_value=ok) as mock_get:
            real_client.search_tasks(query)
        assert mock_get.call_args[1]["params"]["q"] == query

    def test_the_command_surfaces_it(self, runner: CliRunner, client: MagicMock) -> None:
        client.search_tasks.side_effect = APIError(
            400, "Search query is too long.", code="search_query_too_long"
        )
        with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
            result = runner.invoke(cli, ["tasks", "search", "-q", "x" * 300])
        assert result.exit_code != 0


class TestOneConstantAndNoDeadHelpers:
    """Findings 3-4: a duplicated constant and a helper written but never wired.

    Both were introduced by the round-9 change. The constant is the second time
    this exact drift appeared in the branch, which is why it is now asserted rather
    than reviewed.
    """

    def test_the_ttl_is_defined_exactly_once(self) -> None:
        import pathlib
        import re

        # Asserting equality would pass on two copies that happen to agree today —
        # which is precisely the state this test exists to prevent. Assert on the
        # definitions instead.
        repo: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent
        pattern = re.compile(r"^IDEMPOTENCY_TTL_HOURS\s*[:=]", re.M)
        defining: list[str] = [
            str(path.relative_to(repo))
            for path in (repo / "dailybot_cli").rglob("*.py")
            if pattern.search(path.read_text())
        ]
        assert defining == ["dailybot_cli/commands/_writes.py"], defining

    def test_the_help_and_the_hint_cannot_disagree(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        help_text: str = runner.invoke(cli, ["task", "create", "--help"]).stdout
        client.create_task.return_value = {
            "title": "x",
            IDEMPOTENCY_KEY_SENT_KEY: "k",
            "_idempotency_replayed": False,
        }
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            printed: str = runner.invoke(cli, ["task", "create", "-t", "x"]).stdout
        marker: str = f"{IDEMPOTENCY_TTL_HOURS}h"
        assert marker in help_text
        assert marker in printed

    def test_named_is_the_one_used_by_the_creates(self) -> None:
        # It was defined and never called, which makes it look canonical while the
        # call sites keep their own inline version.
        assert named({"name": "x[y]"}, "fallback") == '"x\\[y]"'

    @pytest.mark.parametrize(
        ("argv", "module", "door", "field"),
        [
            (["board", "create", "-n", "B"], "board", "create_board", "name"),
            (["project", "create", "-n", "P"], "project", "create_project", "name"),
            (
                [
                    "goal",
                    "create",
                    "-n",
                    "G",
                    "--period-start",
                    "2026-10-01",
                    "--period-end",
                    "2026-12-31",
                ],
                "goal",
                "create_goal",
                "name",
            ),
            (["task", "create", "-t", "T"], "task", "create_task", "title"),
        ],
    )
    def test_the_creates_report_the_servers_name(
        self,
        runner: CliRunner,
        client: MagicMock,
        argv: list[str],
        module: str,
        door: str,
        field: str,
    ) -> None:
        getattr(client, door).return_value = {field: "server-side", "_idempotency_replayed": False}
        lookup: str = "project" if module == "goal" else module
        with (
            patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
            patch(f"dailybot_cli.commands.{lookup}.get_token", return_value="b"),
        ):
            result = runner.invoke(cli, argv)
        assert "server-side" in result.stdout


class TestTheProjectTreeListsTheNewHelper:
    """Finding 5: `commands/_writes.py` was not in AGENTS.md's structure tree.

    The tree is how an agent discovers where shared behaviour lives; a helper that
    is not in it gets a fifth copy written beside it.
    """

    def test_writes_is_documented(self) -> None:
        import pathlib

        # Resolved from the test file, not the CWD: the suite is run from several
        # places and a relative read passes or fails by accident.
        repo: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent
        assert "_writes.py" in (repo / "AGENTS.md").read_text()
