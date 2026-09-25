"""The Tasks Beta ergonomics bar, enforced on every Tasks command (sweep).

Walks every visible subcommand of `tasks`, `task`, `board`, `project` and `goal`
and checks the agent-first bar the Beta commits to: `--json` everywhere, at least
one example in `--help`, task arguments named TASK (a key or a uuid), and a
`--dry-run` on every command whose verb destroys, removes or retires something.
A new command that misses the bar fails here, not in review.
"""

from collections.abc import Iterator

import click
import pytest
from click.testing import CliRunner

from dailybot_cli.main import cli

TASKS_GROUPS: tuple[str, ...] = ("tasks", "task", "board", "project", "goal")
# Verbs that destroy, remove or retire. Each such command must offer --dry-run.
DESTRUCTIVE_VERBS: tuple[str, ...] = ("archive", "delete", "remove", "unlink")
# Metavars a task argument may carry.
TASK_METAVARS: frozenset[str] = frozenset({"TASK", "OTHER_TASK"})


def _commands() -> Iterator[tuple[str, click.Command]]:
    def walk(command: click.Command, path: list[str]) -> Iterator[tuple[str, click.Command]]:
        if isinstance(command, click.Group):
            for name, sub in sorted(command.commands.items()):
                if not getattr(sub, "hidden", False):
                    yield from walk(sub, [*path, name])
        else:
            yield " ".join(path), command

    for group in TASKS_GROUPS:
        yield from walk(cli.commands[group], [group])  # type: ignore[attr-defined]


COMMANDS: list[tuple[str, click.Command]] = list(_commands())
IDS: list[str] = [path for path, _ in COMMANDS]


def _option_names(command: click.Command) -> set[str]:
    return {
        opt
        for param in command.params
        if isinstance(param, click.Option) and not param.hidden
        for opt in param.opts
    }


def test_the_sweep_sees_the_whole_surface() -> None:
    # A floor, so a broken walker cannot pass by checking nothing.
    assert len(COMMANDS) >= 90


@pytest.mark.parametrize(("path", "command"), COMMANDS, ids=IDS)
def test_every_command_has_json(path: str, command: click.Command) -> None:
    assert "--json" in _option_names(command), path


@pytest.mark.parametrize(("path", "command"), COMMANDS, ids=IDS)
def test_every_help_has_an_example(path: str, command: click.Command) -> None:
    result = CliRunner().invoke(cli, [*path.split(), "--help"])
    assert result.exit_code == 0, path
    assert "Examples:" in result.output, path
    assert f"dailybot {path.split()[0]}" in result.output, path


@pytest.mark.parametrize(("path", "command"), COMMANDS, ids=IDS)
def test_task_arguments_say_task_not_uuid(path: str, command: click.Command) -> None:
    for param in command.params:
        if isinstance(param, click.Argument) and param.name in ("task_uuid", "task_ref"):
            assert param.metavar in TASK_METAVARS, f"{path}: {param.name} -> {param.metavar}"


@pytest.mark.parametrize(("path", "command"), COMMANDS, ids=IDS)
def test_destructive_verbs_offer_a_dry_run(path: str, command: click.Command) -> None:
    verb: str = path.split()[-1]
    if any(verb == v or verb.endswith(f"-{v}") for v in DESTRUCTIVE_VERBS):
        assert "--dry-run" in _option_names(command), path
        assert "--yes" in _option_names(command), path


@pytest.mark.parametrize(("path", "command"), COMMANDS, ids=IDS)
def test_argument_metavars_name_the_thing_not_the_format(path: str, command: click.Command) -> None:
    # BOARD / PROJECT / GOAL / MILESTONE, never BOARD_UUID: one naming style across
    # the family, and TASK must not read as uuid-only (a key works everywhere).
    for param in command.params:
        if isinstance(param, click.Argument):
            shown: str = param.metavar or (param.name or "").upper()
            assert not shown.endswith("_UUID"), f"{path}: {shown}"
