"""`dailybot plan <group> ...` mounts the same groups as the root: same commands, old names intact."""

import click
import pytest
from click.testing import CliRunner

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
def test_the_old_top_level_names_are_gone(runner: CliRunner, group: str) -> None:
    assert group not in cli.commands  # type: ignore[attr-defined]
    assert runner.invoke(cli, [group, "--help"]).exit_code == 2


def test_the_plan_root_mounts_every_group() -> None:
    plan = cli.commands["plan"]  # type: ignore[attr-defined]
    assert isinstance(plan, click.Group)
    assert set(GROUPS) <= set(plan.commands)


def test_the_plan_help_explains_the_product_name(runner: CliRunner) -> None:
    flat: str = " ".join(runner.invoke(cli, ["plan", "--help"]).output.split())
    assert "formerly Tasks" in flat and "dailybot plan tasks" in flat


def test_no_help_text_or_hint_names_the_removed_top_level_form() -> None:
    import pathlib
    import re

    stale: re.Pattern[str] = re.compile(r"dailybot (tasks|task|board|project|goal)\b")
    root: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent / "dailybot_cli"
    offenders: list[str] = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if stale.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, offenders
