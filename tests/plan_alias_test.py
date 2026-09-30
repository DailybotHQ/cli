"""`dailybot plan <group> ...` mounts the same groups as the root: same commands, old names intact."""

from typing import Any
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import DailyBotClient, PaginatedResult
from dailybot_cli.main import cli

GROUPS: tuple[str, ...] = ("tasks", "task", "board", "project", "goal")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_plan_is_listed_at_the_root_with_a_one_line_summary(runner: CliRunner) -> None:
    out: str = runner.invoke(cli, ["--help"]).output
    assert "plan" in out


@pytest.mark.parametrize("group", GROUPS)
def test_each_group_renders_under_plan(runner: CliRunner, group: str) -> None:
    result = runner.invoke(cli, ["plan", group, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage: cli plan " + group in result.output


@pytest.mark.parametrize("group", GROUPS)
def test_the_old_names_still_work(runner: CliRunner, group: str) -> None:
    assert runner.invoke(cli, [group, "--help"]).exit_code == 0


def test_the_alias_mounts_the_very_same_commands() -> None:
    plan = cli.commands["plan"]  # type: ignore[attr-defined]
    assert isinstance(plan, click.Group)
    for group in GROUPS:
        assert plan.commands[group] is cli.commands[group]  # type: ignore[attr-defined]


def test_the_plan_help_explains_the_product_name(runner: CliRunner) -> None:
    flat: str = " ".join(runner.invoke(cli, ["plan", "--help"]).output.split())
    assert "formerly Tasks" in flat and "dailybot tasks" in flat


def test_a_plan_path_reaches_the_same_client_method_as_the_root_path(runner: CliRunner) -> None:
    client: MagicMock = MagicMock(spec=DailyBotClient)
    client.list_notification_routes.return_value = PaginatedResult(
        results=[], count=0, extra={"viewer": {"can_manage": True}}
    )
    with patch("dailybot_cli.commands.tasks_settings.require_auth", return_value=client):
        via_plan = runner.invoke(cli, ["plan", "tasks", "routes", "list", "--json"])
        via_root = runner.invoke(cli, ["tasks", "routes", "list", "--json"])
    assert via_plan.exit_code == 0 and via_root.exit_code == 0
    assert client.list_notification_routes.call_count == 2
    assert via_plan.output == via_root.output


def test_the_alias_does_not_duplicate_the_groups_at_the_root() -> None:
    names: list[Any] = sorted(cli.commands)  # type: ignore[attr-defined]
    assert names.count("plan") == 1
