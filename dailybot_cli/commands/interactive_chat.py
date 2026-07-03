"""Conversational terminal mode for Dailybot CLI (AI chat).

`dailybot interactive` is retained as a deprecated alias for `dailybot ask`
(with no message), which is now the canonical entry point for the AI chat.
"""

import click

from dailybot_cli.api_client import DailyBotClient
from dailybot_cli.commands.public_api_helpers import require_bearer_auth
from dailybot_cli.display import print_error, print_info, print_warning


def launch_chat_tui(client: DailyBotClient) -> None:
    """Launch the full-screen Textual AI chat session (textual is lazy-imported)."""
    try:
        from dailybot_cli.tui.app import run_chat_app
    except ModuleNotFoundError as exc:
        if exc.name != "textual":
            raise
        print_error("The interactive chat UI requires Textual, but it is not installed.")
        print_info('From the CLI repo, run: python -m pip install -e ".[dev]"')
        raise click.ClickException("Missing dependency: textual") from exc

    run_chat_app(client)


@click.command(name="interactive")
def interactive() -> None:
    """Deprecated alias for `dailybot ask` — opens the AI chat session."""
    print_warning("`dailybot interactive` is deprecated; use `dailybot ask` instead.")
    client: DailyBotClient = require_bearer_auth()
    launch_chat_tui(client)
