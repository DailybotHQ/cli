"""`dailybot tasks channels search` (PLAN_004)."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient, PaginatedResult
from dailybot_cli.commands.public_api_helpers import EXIT_NOT_AUTHENTICATED
from dailybot_cli.display import console
from dailybot_cli.main import cli

ROWS: list[dict[str, str]] = [
    {"external_id": "C0000000A", "name": "eng", "type": "channel"},
    {"external_id": "G0000000D", "name": "leads", "type": "private_channel"},
]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    mock: MagicMock = MagicMock(spec=DailyBotClient)
    mock.search_channels.return_value = PaginatedResult(
        results=ROWS, count=2, extra={"platform": "slack"}
    )
    return mock


@pytest.fixture(autouse=True)
def eighty_columns() -> Any:
    previous: int | None = console._width
    console.width = 80
    try:
        yield
    finally:
        console._width = previous


def _invoke(runner: CliRunner, client: MagicMock, args: list[str]) -> Any:
    with patch("dailybot_cli.commands.tasks_settings.require_auth", return_value=client):
        return runner.invoke(cli, ["tasks", "channels", *args])


def test_help_explains_the_difference_with_channels_list(runner: CliRunner) -> None:
    flat: str = " ".join(
        runner.invoke(cli, ["tasks", "channels", "search", "--help"]).output.split()
    )
    assert "channels list" in flat and "external id" in flat and "Examples" in flat


def test_the_group_is_listed_under_tasks(runner: CliRunner) -> None:
    assert "channels" in runner.invoke(cli, ["tasks", "--help"]).output


def test_search_text_and_type_reach_the_client(runner: CliRunner, client: MagicMock) -> None:
    result = _invoke(runner, client, ["search", "-q", "en", "--type", "channel"])
    assert result.exit_code == 0, result.output
    kwargs: dict[str, Any] = client.search_channels.call_args.kwargs
    assert kwargs["search"] == "en" and kwargs["channel_type"] == "channel"


def test_public_is_an_alias_for_the_channel_type(runner: CliRunner, client: MagicMock) -> None:
    _invoke(runner, client, ["search", "--type", "public"])
    assert client.search_channels.call_args.kwargs["channel_type"] == "channel"


def test_a_bad_type_is_refused_locally(runner: CliRunner, client: MagicMock) -> None:
    assert _invoke(runner, client, ["search", "--type", "nope"]).exit_code == 2
    client.search_channels.assert_not_called()


def test_no_filters_sends_none(runner: CliRunner, client: MagicMock) -> None:
    _invoke(runner, client, ["search"])
    kwargs: dict[str, Any] = client.search_channels.call_args.kwargs
    assert kwargs.get("search") is None and kwargs.get("channel_type") is None


def test_paging_flags_reach_the_client(runner: CliRunner, client: MagicMock) -> None:
    _invoke(runner, client, ["search", "--page", "2", "--page-size", "10"])
    kwargs: dict[str, Any] = client.search_channels.call_args.kwargs
    assert kwargs["page"] == 2 and kwargs["page_size"] == 10


def test_the_table_shows_whole_external_ids_at_80_columns(
    runner: CliRunner, client: MagicMock
) -> None:
    flat: str = " ".join(_invoke(runner, client, ["search"]).output.split())
    assert "C0000000A" in flat and "G0000000D" in flat and "private_channel" in flat
    assert "…" not in flat


def test_json_passes_the_envelope_with_the_platform(runner: CliRunner, client: MagicMock) -> None:
    body: dict[str, Any] = json.loads(_invoke(runner, client, ["search", "--json"]).output)
    assert body["results"] == ROWS and body["platform"] == "slack" and body["count"] == 2


def test_an_empty_result_says_so(runner: CliRunner, client: MagicMock) -> None:
    client.search_channels.return_value = PaginatedResult(results=[], count=0)
    assert "no channels" in _invoke(runner, client, ["search", "-q", "zzz"]).output.lower()


def test_more_pages_are_announced(runner: CliRunner, client: MagicMock) -> None:
    client.search_channels.return_value = PaginatedResult(
        results=ROWS, count=50, next="https://x/?page=2"
    )
    assert "--page" in _invoke(runner, client, ["search"]).output


def test_channel_names_are_data_not_markup(runner: CliRunner, client: MagicMock) -> None:
    client.search_channels.return_value = PaginatedResult(
        results=[{"external_id": "C1", "name": "[/dim][bold red]x", "type": "channel"}], count=1
    )
    result = _invoke(runner, client, ["search"])
    assert result.exit_code == 0 and result.exception is None


def test_platform_not_connected_is_explained(runner: CliRunner, client: MagicMock) -> None:
    client.search_channels.side_effect = APIError(400, "x", code="platform_not_connected")
    result = _invoke(runner, client, ["search"])
    assert result.exit_code == 2
    assert "chat platform" in result.output


def test_an_unauthenticated_call_exits_3(runner: CliRunner, client: MagicMock) -> None:
    client.search_channels.side_effect = APIError(401, "no", code="credential_absent")
    assert _invoke(runner, client, ["search"]).exit_code == EXIT_NOT_AUTHENTICATED
