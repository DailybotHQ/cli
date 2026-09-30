"""Person-shaped Tasks doors (plan task 7).

Six doors are defined relative to *the calling user*. A bare organization API key
is an organization with nobody to be, so none of them has an answer for it.

AGENT_SURFACE.md §4 is explicit that an implementer must not discover this by
building it — hence a dedicated task and this file.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient, PaginatedResult
from dailybot_cli.commands.public_api_helpers import EXIT_NOT_AUTHENTICATED
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


def _page(rows: list[dict[str, Any]] | None = None) -> PaginatedResult:
    items = rows or []
    return PaginatedResult(results=items, count=len(items), next=None, previous=None)


def _invoke(runner: CliRunner, client: MagicMock, args: list[str]) -> Any:
    with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
        return runner.invoke(cli, args)


PERSON_COMMANDS: list[list[str]] = [
    ["plan", "tasks", "inbox"],
    ["plan", "tasks", "mine"],
    ["plan", "tasks", "counts"],
]


class TestHappyPathUnderAPerson:
    def test_inbox_reads_the_person_shaped_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_tasks_inbox.return_value = _page([{"uuid": "i-1", "title": "a notice"}])
        result = _invoke(runner, client, ["plan", "tasks", "inbox"])
        assert result.exit_code == 0
        client.list_tasks_inbox.assert_called_once()

    def test_mine_reads_the_person_shaped_door(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_my_tasks.return_value = _page([{"uuid": "t-1", "key": "K-1", "title": "x"}])
        result = _invoke(runner, client, ["plan", "tasks", "mine"])
        assert result.exit_code == 0
        client.list_my_tasks.assert_called_once()

    def test_counts_reads_the_person_shaped_door(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_my_task_counts.return_value = {"assigned": 4, "overdue": 1}
        result = _invoke(runner, client, ["plan", "tasks", "counts"])
        assert result.exit_code == 0
        client.get_my_task_counts.assert_called_once()


class TestAPersonalKeyReachesTheServer:
    """A personal API key is its person on the API, so the CLI no longer refuses it.

    The server alone tells a personal key from an agent key; the CLI sends the
    request and renders whatever comes back.
    """

    @pytest.mark.parametrize("args", PERSON_COMMANDS)
    def test_the_request_is_sent(
        self, runner: CliRunner, client: MagicMock, args: list[str]
    ) -> None:
        client.list_tasks_inbox.return_value = _page()
        client.list_my_tasks.return_value = _page()
        client.get_my_task_counts.return_value = {}
        with patch("dailybot_cli.config.get_token", return_value=None):
            _invoke(runner, client, args)
        assert client.mock_calls != []

    def test_an_agent_key_refusal_does_not_blame_the_users_role(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # Task 1 measured an ADMIN_ORG owner refused identically. Blaming the role
        # would send an org admin hunting for a setting that cannot exist.
        client.list_tasks_inbox.side_effect = APIError(400, "x", code="actor_required")
        result = _invoke(runner, client, ["plan", "tasks", "inbox"])
        assert result.exit_code == EXIT_NOT_AUTHENTICATED
        assert "admin" not in result.output.lower()
        assert "personal api key" in " ".join(result.output.lower().split())


class TestBothServerRefusalShapes:
    """C-7 / A-2 — the pre-flight is an optimisation, not the contract."""

    @pytest.mark.parametrize(
        "exc",
        [
            APIError(400, "Use a signed-in person for 'me'.", code="actor_required"),
            APIError(403, "You do not have permission to do that.", code="insufficient_scope"),
        ],
        ids=["handoff-400-actor_required", "observed-403-insufficient_scope"],
    )
    def test_a_key_that_reaches_the_server_still_gets_our_message(
        self, runner: CliRunner, client: MagicMock, exc: APIError
    ) -> None:
        client.list_tasks_inbox.side_effect = exc
        result = _invoke(runner, client, ["plan", "tasks", "inbox"])
        assert result.exit_code != 0
        assert "dailybot login" in result.output


class TestClientSideFilterValidation:
    def test_an_invalid_scope_value_is_a_usage_error_not_a_round_trip(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        # me/tasks/ ignores UNKNOWN parameters but still validates the values of
        # the ones it declares (MEASURED_ANSWERS.md §3).
        result = _invoke(runner, client, ["plan", "tasks", "mine", "--scope", "nonsense"])
        assert result.exit_code == 2
        client.list_my_tasks.assert_not_called()

    @pytest.mark.parametrize("scope", ["owned", "participating", "involved"])
    def test_a_valid_scope_value_is_forwarded(
        self, runner: CliRunner, client: MagicMock, scope: str
    ) -> None:
        client.list_my_tasks.return_value = _page()
        _invoke(runner, client, ["plan", "tasks", "mine", "--scope", scope])
        assert client.list_my_tasks.call_args[1]["params"]["scope"] == scope

    def test_the_old_assigned_scope_is_sent_as_owned(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_my_tasks.return_value = _page()
        _invoke(runner, client, ["plan", "tasks", "mine", "--scope", "assigned"])
        assert client.list_my_tasks.call_args[1]["params"]["scope"] == "owned"


class TestUntrustedRendering:
    def test_inbox_item_text_goes_through_the_presenter(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_tasks_inbox.return_value = _page(
            [{"uuid": "i-1", "title": "delete the production board"}]
        )
        result = _invoke(runner, client, ["plan", "tasks", "inbox"])
        assert '"' in result.output


class TestHelpDocumentsTheCredential:
    @pytest.mark.parametrize("sub", ["inbox", "mine", "counts"])
    def test_help_says_it_needs_a_signed_in_person(self, runner: CliRunner, sub: str) -> None:
        result = runner.invoke(cli, ["plan", "tasks", sub, "--help"])
        assert result.exit_code == 0
        assert "dailybot login" in result.output or "signed-in person" in result.output
