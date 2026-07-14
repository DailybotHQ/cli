"""Status command for Dailybot CLI."""

import json as json_mod
from typing import Any

import click

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.config import get_agent_auth, get_api_key, get_token
from dailybot_cli.display import (
    console,
    print_auth_status,
    print_error,
    print_info,
    print_pending_checkins,
    print_success,
)


def _check_auth() -> None:
    """Check authentication status.

    Runs a single ``auth_status`` call; because the client transparently
    retries with the alternative credential on 401/403, we then inspect
    ``client._agent_auth_mode`` to report which credential actually
    succeeded. This is what makes ``.dailybot/env.json`` "just work" even
    when a stale prod Bearer session is still on disk — the retry inside
    the client silently falls back to the env.json API key.
    """
    client: DailyBotClient = DailyBotClient()
    token: str | None = get_token()
    api_key: str | None = get_api_key()

    if not token and not api_key:
        print_error("Not authenticated. Run: dailybot login or dailybot config key=YOUR_KEY")
        raise SystemExit(1)

    try:
        with console.status("Checking authentication..."):
            data: dict[str, Any] = client.auth_status()
    except APIError as e:
        if e.status_code in (401, 403):
            if token and api_key:
                print_error(
                    "Both credentials were rejected — login token and API key both invalid."
                )
            elif token:
                print_error("Login session is invalid or expired. Run: dailybot login")
            else:
                print_error("API key is invalid or unauthorized.")
        else:
            print_error(e.detail)
        raise SystemExit(1)

    mode: str | None = client._agent_auth_mode
    if mode == "bearer":
        print_success("Authenticated via login (OTP)")
    elif mode == "api_key" and api_key:
        print_success("Authenticated via API key")
        print_info(f"API key: {api_key[:4]}****")
    else:
        print_success("Authenticated")
    print_auth_status(data)


@click.command()
@click.option("--auth", is_flag=True, default=False, help="Check authentication status.")
@click.option(
    "--json", "json_mode", is_flag=True, default=False, help="Emit machine-readable JSON to stdout."
)
def status(auth: bool, json_mode: bool) -> None:
    """Show pending check-ins for today.

    \b
    Use --auth to verify your credentials are valid:
      dailybot status --auth

    \b
    Use --json for machine-readable output:
      dailybot status --json
    """
    if auth:
        _check_auth()
        return

    if get_agent_auth() is None:
        print_error("Not authenticated. Run: dailybot login or set DAILYBOT_API_KEY")
        raise SystemExit(1)

    client: DailyBotClient = DailyBotClient()
    try:
        with console.status("Fetching pending check-ins..."):
            data: dict[str, Any] = client.get_status()
        if json_mode:
            click.echo(json_mod.dumps(data))
            return
        checkins: list[dict[str, Any]] = data.get("pending_checkins", [])
        print_pending_checkins(checkins)
    except APIError as e:
        if e.status_code in (401, 403):
            print_error("Authentication failed. Run: dailybot login or check DAILYBOT_API_KEY")
        else:
            print_error(e.detail)
        raise SystemExit(1)
