"""`--sort` on `plan task list` and `plan tasks mine`: aliases, pass-through, invalid_sort, display."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient, PaginatedResult
from dailybot_cli.commands._sorting import describe_sort, normalize_sort
from dailybot_cli.main import cli


@pytest.mark.parametrize(
    ("typed", "sent"),
    [
        ("priority", "priority"),
        ("-priority", "-priority"),
        ("due", "due_date"),
        ("-due", "-due_date"),
        ("start", "start_date"),
        ("-start", "-start_date"),
        ("created", "created_at"),
        ("updated", "updated_at"),
        ("-completed", "-completed_at"),
        ("rank", "rank"),
        ("due_date", "due_date"),
        ("Due", "due_date"),
        ("something_new", "something_new"),
    ],
)
def test_aliases_map_and_the_rest_passes_through(typed: str, sent: str) -> None:
    assert normalize_sort(typed) == sent


def test_the_description_says_which_end_is_first() -> None:
    assert describe_sort("priority") == "Sorted by priority (urgent first)"
    assert describe_sort("-priority") == "Sorted by priority (lowest first)"
    assert describe_sort("-due_date") == "Sorted by due_date descending"


def _client() -> MagicMock:
    client: MagicMock = MagicMock(spec=DailyBotClient)
    client.list_tasks.return_value = PaginatedResult(results=[], count=0, next=None, previous=None)
    client.list_my_tasks.return_value = PaginatedResult(
        results=[], count=0, next=None, previous=None
    )
    return client


def _run(module: str, argv: list[str], client: Any) -> Any:
    with patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client):
        return CliRunner().invoke(cli, ["plan", *argv])


class TestTaskList:
    def test_an_alias_reaches_the_wire_as_the_api_value(self) -> None:
        client: MagicMock = _client()
        result = _run("task", ["task", "list", "--sort", "-due"], client)
        assert result.exit_code == 0, result.output
        assert client.list_tasks.call_args.kwargs["filters"]["sort"] == "-due_date"

    def test_the_human_output_names_the_active_sort(self) -> None:
        result = _run("task", ["task", "list", "--sort", "priority"], _client())
        assert "Sorted by priority (urgent first)" in " ".join(result.output.split())

    def test_json_stays_one_document(self) -> None:
        result = _run("task", ["task", "list", "--sort", "priority", "--json"], _client())
        assert "count" in json.loads(result.output)

    def test_an_unknown_field_is_left_to_the_server(self) -> None:
        client: MagicMock = _client()
        client.list_tasks.side_effect = APIError(
            400,
            "Invalid sort.",
            code="invalid_sort",
            extra={"allowed": ["rank", "priority", "due_date"]},
        )
        result = _run("task", ["task", "list", "--sort", "bogus"], client)
        assert client.list_tasks.call_args.kwargs["filters"]["sort"] == "bogus"
        assert result.exit_code != 0
        err: str = " ".join(result.output.split())
        assert "invalid_sort" in err or "sort" in err.lower()
        assert "rank, priority, due_date" in err


class TestMine:
    def test_mine_sorts_with_the_same_flag(self) -> None:
        client: MagicMock = _client()
        result = _run("tasks", ["tasks", "mine", "--sort", "-priority"], client)
        assert result.exit_code == 0, result.output
        assert client.list_my_tasks.call_args.kwargs["params"]["sort"] == "-priority"
        assert "Sorted by priority (lowest first)" in " ".join(result.output.split())

    def test_mine_without_a_sort_sends_none_and_says_nothing(self) -> None:
        client: MagicMock = _client()
        result = _run("tasks", ["tasks", "mine"], client)
        assert "sort" not in (client.list_my_tasks.call_args.kwargs.get("params") or {})
        assert "Sorted by" not in result.output
