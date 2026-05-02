"""Status command for Dailybot CLI."""

from typing import Any

import click

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.config import get_api_key, get_token
from dailybot_cli.display import (
    console,
    print_auth_status,
    print_error,
    print_info,
    print_pending_checkins,
    print_success,
)


def _check_auth() -> None:
    """Check authentication status: try OTP login first, then API key."""
    client: DailyBotClient = DailyBotClient()

    # Try OTP/login token first
    token: str | None = get_token()
    if token:
        try:
            with console.status("Checking login session..."):
                data: dict[str, Any] = client.auth_status()
            print_success("Authenticated via login (OTP)")
            print_auth_status(data)
            return
        except APIError:
            print_info("Login session is invalid or expired.")

    # Try API key
    api_key: str | None = get_api_key()
    if api_key:
        try:
            with console.status("Checking API key..."):
                client.get_agent_health(agent_name="CLI")
            print_success("Authenticated via API key")
            masked: str = api_key[:4] + "****"
            print_info(f"API key: {masked}")
            return
        except APIError as e:
            if e.status_code in (401, 403):
                print_error("API key is invalid or unauthorized.")
            else:
                # Non-auth error means the key itself is valid
                print_success("Authenticated via API key")
                masked = api_key[:4] + "****"
                print_info(f"API key: {masked}")
                return

    print_error("Not authenticated. Run: dailybot login or dailybot config key=YOUR_KEY")
    raise SystemExit(1)


@click.command()
@click.option("--auth", is_flag=True, default=False, help="Check authentication status.")
def status(auth: bool) -> None:
    """Show pending check-ins for today.

    \b
    Use --auth to verify your credentials are valid:
      dailybot status --auth
    """
    if auth:
        _check_auth()
        return

    token: str | None = get_token()
    if not token:
        print_error("Not logged in. Run: dailybot login")
        raise SystemExit(1)

    client: DailyBotClient = DailyBotClient()
    try:
        with console.status("Fetching pending check-ins..."):
            data: dict[str, Any] = client.get_status()
        checkins: list[dict[str, Any]] = data.get("pending_checkins", [])
        print_pending_checkins(checkins)
    except APIError as e:
        if e.status_code in (401, 403):
            print_error("Session expired. Please log in again: dailybot login")
        else:
            print_error(e.detail)
        raise SystemExit(1)
