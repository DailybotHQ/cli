"""Conversational terminal mode for Dailybot CLI."""

import click

from dailybot_cli.api_client import DailyBotClient
from dailybot_cli.commands.public_api_helpers import require_bearer_auth
from dailybot_cli.display import print_error, print_info


@click.command(name="interactive")
def interactive() -> None:
    """Talk directly to Dailybot in a terminal chat session."""
    client: DailyBotClient = require_bearer_auth()
    try:
        from dailybot_cli.tui.app import run_chat_app
    except ModuleNotFoundError as exc:
        if exc.name != "textual":
            raise
        print_error("The interactive chat UI requires Textual, but it is not installed.")
        print_info('From the CLI repo, run: python -m pip install -e ".[dev]"')
        raise click.ClickException("Missing dependency: textual") from exc

    run_chat_app(client)
