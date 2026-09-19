"""Object-level Tasks commands (``dailybot task``).

Sibling of ``dailybot tasks`` (workspace-level). This group reads and mutates
**one** task. Every string it renders is user-authored and goes through
``display.present_untrusted``.

`/v1/tasks/tasks/` is **strict** about parameters and names the one it refuses,
unlike `me/tasks/` which silently ignores unknown ones. So every filter flag here
maps to a parameter the contract declares — a convenience flag that invents a
parameter name would produce a 400.
"""

from typing import Any

import click

from dailybot_cli.api_client import APIError, PaginatedResult
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_api_error,
    require_auth,
    resolve_error_message,
)
from dailybot_cli.commands.query_options import build_query_params, query_options
from dailybot_cli.display import (
    console,
    print_error,
    print_pagination_footer,
    print_task_detail,
    print_tasks_table,
)

# Parameters `/v1/tasks/tasks/` declares. `has_dates` is here deliberately: it was
# honoured for two years, never declared, and refused the moment the door became
# strict (MEASURED_ANSWERS.md §3). The declared set is the contract, not the
# historically-tolerated set.
TASK_INCLUDE_VALUES: tuple[str, ...] = ("labels", "participants", "subtasks")

# Short aliases owned by the shared `query_options` decorator: -a (--all),
# -l (--limit), -s (--search), -S (--since), -U (--until), -p (--page).
# Filter flags on this group are therefore long-only except `-b`, which is free.
# Click only *warns* about a duplicate short flag, so the collision is silent at
# runtime and the wrong option wins — a regression test pins it instead.


def _envelope(result: PaginatedResult) -> dict[str, Any]:
    return {
        "count": result.count,
        "next": result.next,
        "previous": result.previous,
        "results": result.results,
    }


@click.group()
def task() -> None:
    """Read and change one Dailybot task.

    \b
    For workspace-level questions — what is open, what changed, search — use
    `dailybot tasks` instead.

    \b
    Examples:
      dailybot task list --board <board-uuid>
      dailybot task get <task-uuid>
    """


@task.command("list")
@click.option("-b", "--board", default=None, help="Only tasks on this board.")
@click.option("--state", default=None, help="Only tasks in this workflow state.")
@click.option("--assignee", default=None, help="Only tasks assigned to this user.")
@click.option("--label", default=None, help="Only tasks carrying this label.")
@click.option(
    "--has-dates/--no-has-dates",
    "has_dates",
    default=None,
    help="Only tasks that do (or do not) carry dates.",
)
@click.option(
    "--include",
    type=click.Choice(TASK_INCLUDE_VALUES, case_sensitive=False),
    multiple=True,
    help="Ask for a roll-up. Nothing is included by default — absence is a real answer.",
)
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_list(
    board: str | None,
    state: str | None,
    assignee: str | None,
    label: str | None,
    has_dates: bool | None,
    include: tuple[str, ...],
    json_mode: bool,
    **flags: Any,
) -> None:
    """List tasks.

    \b
    Roll-ups are NOT requested by default. A field you did not ask for is absent
    from the payload, which is different from null and different from zero — ask
    for it with --include when you want it.

    \b
    Examples:
      dailybot task list --board <board-uuid> --state doing
      dailybot task list --assignee <user-uuid> --include labels --json
    """
    client = require_auth()
    filters: dict[str, Any] = {}
    if board:
        filters["board"] = board
    if state:
        filters["state"] = state
    if assignee:
        filters["assignee"] = assignee
    if label:
        filters["label"] = label
    if has_dates is not None:
        filters["has_dates"] = has_dates
    if include:
        filters["include"] = ",".join(sorted({value.lower() for value in include}))

    try:
        spec = build_query_params(**flags)
        merged: dict[str, Any] = {**(spec.params or {}), **filters}
        with console.status("Reading tasks..."):
            result: PaginatedResult = client.list_tasks(
                filters=merged or None,
                page=spec.page,
                page_size=spec.page_size,
                fetch_all=spec.fetch_all,
                limit=spec.limit,
            )
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(_envelope(result))
        return
    print_tasks_table(result.results)
    print_pagination_footer(len(result.results), result.count, has_more=bool(result.next))


@task.command("get")
@click.argument("task_uuid")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def task_get(task_uuid: str, json_mode: bool) -> None:
    """Show one task.

    \b
    Prints the API self-link. No web URL is shown: the web app owns its path
    shapes and they are not published, so a link built here would be a guess.

    \b
    Examples:
      dailybot task get <task-uuid>
      dailybot task get <task-uuid> --json
    """
    client = require_auth()
    try:
        with console.status("Reading the task..."):
            data: dict[str, Any] = client.get_task(task_uuid)
    except APIError as exc:
        if exc.code == "not_found":
            # Isolation is 404-not-403: an invisible object and a nonexistent one
            # must be indistinguishable, so this must not read as a permission error.
            print_error(resolve_error_message(exc))
            raise SystemExit(5) from exc
        exit_for_api_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_task_detail(data)
