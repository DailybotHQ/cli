"""`dailybot ask` — talk to the Dailybot AI.

Two modes, chosen by whether a message is supplied (the same pattern as
`psql`/`python`/`sqlite3`):

- ``dailybot ask "question"`` — one-shot headless answer printed to stdout
  (ideal for agents, CI, and scripts).
- ``dailybot ask`` — opens the full-screen interactive chat session.
"""

import sys
from typing import Any

import click

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.interactive_chat import launch_chat_tui
from dailybot_cli.commands.public_api_helpers import (
    emit_json,
    exit_for_api_error,
    require_bearer_auth,
)
from dailybot_cli.display import console, print_ai_answer

EMPTY_ANSWER: str = "Dailybot returned an empty response."


@click.command(name="ask")
@click.argument("message", required=False)
@click.option("--json", "json_mode", is_flag=True, help="Emit the answer as machine-readable JSON.")
@click.option(
    "--session-id",
    "-s",
    "session_id",
    default=None,
    help="Continue an existing chat session by id.",
)
def ask(message: str | None, json_mode: bool, session_id: str | None) -> None:
    """Ask the Dailybot AI a question, or open an interactive chat session.

    \b
    With a message -> one-shot headless answer (ideal for agents and scripts):
      dailybot ask "Summarize my pending check-ins"
      dailybot ask "What forms do I have?" --json
      echo "draft my standup" | dailybot ask
    \b
    Without a message -> opens the full-screen chat session:
      dailybot ask
    """
    # Resolve the message: explicit argument, else piped stdin. No message plus
    # an interactive terminal means the human wants the full chat session.
    if message is None and not sys.stdin.isatty():
        piped: str = sys.stdin.read().strip()
        message = piped or None

    client: DailyBotClient = require_bearer_auth()

    if message is None:
        launch_chat_tui(client)
        return

    try:
        with console.status("Asking Dailybot..."):
            response: dict[str, Any] = client.create_chat_completion(
                message=message,
                session_id=session_id,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    assistant: dict[str, Any] = response.get("message") or {}
    content: str = str(assistant.get("content") or "").strip() or EMPTY_ANSWER

    if json_mode:
        emit_json(
            {
                "message": content,
                "actions": response.get("actions") or [],
                "classification": response.get("classification"),
                "session_id": response.get("session_id") or session_id,
            }
        )
    else:
        print_ai_answer(content)
