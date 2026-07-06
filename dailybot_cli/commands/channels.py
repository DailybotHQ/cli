"""Report-channel discovery commands for the user-scoped public API."""

from typing import Any

import click

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_api_error,
    require_auth,
)
from dailybot_cli.display import console, print_report_channels


@click.group()
def channels() -> None:
    """Discover report channels with your Dailybot session.

    \b
    Acts as you — visibility and permissions match the webapp for your account.
    """


@channels.command("list")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def channels_list(json_mode: bool) -> None:
    """List report channels you can attach to forms and check-ins.

    \b
    Acts as you. Use a channel UUID with `--report-channel` on
    `form create/edit` or `checkin create/config`.

    \b
    Examples:
      dailybot channels list
      dailybot channels list --json
    """
    client = require_auth()
    try:
        with console.status("Loading report channels..."):
            data: list[dict[str, Any]] = client.list_report_channels()
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(data)
        return
    print_report_channels(data)
