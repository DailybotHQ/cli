"""Workspace saved views (``/v1/plan/views/workspace/``).

Annotated as ``dailybot plan views workspace`` and
``dailybot plan views workspace save``. Person-only; org keys need an actor.
"""

from typing import Any

import click

from dailybot_cli.api_client import APIError
from dailybot_cli.commands._beta import mark_beta
from dailybot_cli.commands._writes import report_write
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_tasks_error,
    load_json_input,
    require_auth,
    rows_of,
)
from dailybot_cli.display import console, print_info, print_tasks_rows

_VIEW_COLUMNS: list[tuple[str, str, bool]] = [
    ("Name", "name", False),
    ("Mode", "view_mode", True),
    ("Visibility", "visibility", True),
    ("UUID", "uuid", True),
]


@click.group("views")
def views() -> None:
    """Workspace-level saved views (not tied to one board or project).

    \b
    Needs a person: `dailybot login` or a personal API key.

    \b
    Examples:
      dailybot plan views workspace
      dailybot plan views workspace save -f views.json --if-match '"3"'
    """


mark_beta(views)


@views.group("workspace", invoke_without_command=True)
@click.option(
    "--etag",
    "etag_only",
    is_flag=True,
    help="Print only the ETag `views workspace save --if-match` needs, and nothing else.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
@click.pass_context
def views_workspace(ctx: click.Context, etag_only: bool, json_mode: bool) -> None:
    """List your workspace views plus shared ones across every project.

    \b
    The ETag covers THIS caller's own workspace views only — send it back on save.

    \b
    Examples:
      dailybot plan views workspace
      dailybot plan views workspace --etag
      dailybot plan views workspace --json
      dailybot plan views workspace save -f views.json --if-match '"3"'
    """
    if ctx.invoked_subcommand is not None:
        return
    client = require_auth()
    try:
        with console.status("Reading workspace views..."):
            data, etag = client.list_workspace_views_with_etag()
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if etag_only:
        if etag is None:
            raise click.ClickException(
                "The server returned no ETag for workspace views, so a save cannot be "
                "made safely from this response."
            )
        click.echo(etag)
        return
    if json_mode:
        payload: Any
        if isinstance(data, dict):
            payload = {**data, "etag": etag}
        elif isinstance(data, list):
            payload = {"results": data, "etag": etag}
        else:
            payload = {"data": data, "etag": etag}
        emit_json(payload)
        return
    rows: list[Any]
    if isinstance(data, dict):
        rows = rows_of(data)
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    print_tasks_rows("Workspace views", rows, _VIEW_COLUMNS, empty="No workspace views.")
    if etag:
        print_info(f"ETag: {etag} (pass it to `views workspace save --if-match`)")


@views_workspace.command("save")
@click.option(
    "-f",
    "--file",
    "views_file",
    type=click.File("r"),
    required=True,
    help="JSON array of views (`-` reads stdin). It REPLACES your whole list.",
)
@click.option(
    "--if-match",
    default=None,
    help="The ETag `views workspace` showed. Protects against overwriting a concurrent save.",
)
@click.option(
    "--fetch-etag",
    is_flag=True,
    help="Read the current ETag first instead of passing --if-match (narrower protection).",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def views_workspace_save(
    views_file: Any,
    if_match: str | None,
    fetch_etag: bool,
    json_mode: bool,
) -> None:
    """Replace your workspace views with the array in a file.

    \b
    This replaces the WHOLE list of your own workspace views, so the server
    requires the ETag you read. `visibility` is `personal` or `shared`
    (`board_default` is refused).

    \b
    Examples:
      dailybot plan views workspace --json
      dailybot plan views workspace save -f views.json --if-match '"3"'
      dailybot plan views workspace save -f views.json --fetch-etag --json
    """
    if (if_match is None) == (not fetch_etag):
        raise click.UsageError("Pass exactly one of --if-match <etag> or --fetch-etag.")
    try:
        views_payload: Any = load_json_input(views_file)
    except ValueError as exc:
        raise click.BadParameter(f"not valid JSON: {exc}", param_hint="--file") from exc
    if not isinstance(views_payload, list):
        raise click.BadParameter("must be a JSON array of views.", param_hint="--file")
    client = require_auth()
    try:
        etag: str | None = if_match
        if fetch_etag:
            with console.status("Reading the current workspace views..."):
                _current, etag = client.list_workspace_views_with_etag()
            if etag is None:
                raise click.ClickException(
                    "The server returned no ETag for workspace views, so a save cannot be "
                    "made safely. Nothing was changed."
                )
        with console.status("Saving workspace views..."):
            data: Any = client.save_workspace_views(views_payload, if_match=str(etag))
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    report_write(data if isinstance(data, dict) else {"views": data}, "Workspace views saved")
