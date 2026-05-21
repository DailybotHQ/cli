"""Interactive mode for Dailybot CLI."""

import readline  # noqa: F401 — enables arrow-key editing in input()
from typing import Any

import click
import httpx
import questionary

from dailybot_cli import __version__
from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.auth import _do_login
from dailybot_cli.config import get_api_url, get_token, load_credentials
from dailybot_cli.display import (
    console,
    print_error,
    print_info,
    print_pending_checkins,
    print_success,
    print_update_result,
    print_warning,
)

MENU_SEND_UPDATE: str = "Send update"
MENU_VIEW_PENDING: str = "View pending check-ins"
MENU_AUTH_STATUS: str = "Auth status"
MENU_QUIT: str = "Quit"

MENU_CHOICES: list[str] = [
    MENU_SEND_UPDATE,
    MENU_VIEW_PENDING,
    MENU_AUTH_STATUS,
    MENU_QUIT,
]


def run_interactive() -> None:
    """Run the interactive TUI mode."""
    creds: dict[str, Any] | None = load_credentials()
    token: str | None = get_token()

    console.print(f"\n[bold]Dailybot CLI[/bold] [dim]v{__version__}[/dim]")
    api_url: str = get_api_url()
    console.print(f"[dim]API: {api_url}[/dim]")

    if not token or not creds:
        console.print()
        print_info("Let's get you logged in.")
        console.print()
        email: str = click.prompt("Email")
        try:
            _do_login(email)
        except SystemExit:
            print_error("Login failed.")
            return
        creds = load_credentials()
    else:
        stored_api: str = str(creds.get("api_url") or api_url).rstrip("/")
        if stored_api != api_url.rstrip("/"):
            console.print()
            print_warning(
                f"Stored login targets {stored_api}, but this session uses {api_url}. "
                "Run: dailybot login"
            )
            console.print()
            email = click.prompt("Email")
            try:
                _do_login(email)
            except SystemExit:
                print_error("Login failed.")
                return
            creds = load_credentials()
        else:
            email = creds.get("email", "") if creds else ""
            org_stored: Any = creds.get("organization", "") if creds else ""
            org: str = org_stored.get("name", "") if isinstance(org_stored, dict) else str(org_stored)
            org_uuid: str = creds.get("organization_uuid", "") if creds else ""
            console.print(f"Logged in as {email} ({org})")
            if org_uuid:
                console.print(f"[dim]Org UUID: {org_uuid}[/dim]")
    console.print()

    client: DailyBotClient = DailyBotClient()

    while True:
        console.print()
        choice: str | None = questionary.select(
            "What would you like to do?",
            choices=MENU_CHOICES,
        ).ask()

        if choice is None or choice == MENU_QUIT:
            print_info("Goodbye!")
            break
        elif choice == MENU_SEND_UPDATE:
            _send_update(client)
        elif choice == MENU_VIEW_PENDING:
            _view_pending(client)
        elif choice == MENU_AUTH_STATUS:
            _show_auth(client)


def _send_update(client: DailyBotClient) -> None:
    """Prompt for and send an update."""
    print_info("Enter your update (press Enter on empty line to submit):")
    lines: list[str] = []
    while True:
        try:
            line: str = input("> ")
        except EOFError:
            break
        if line == "" and lines:
            break
        lines.append(line)

    message: str = "\n".join(lines).strip()
    if not message:
        print_error("Empty update. Nothing sent.")
        return

    try:
        with console.status("Submitting update..."):
            result: dict[str, Any] = client.submit_update(message=message)
        print_update_result(result)
    except httpx.TimeoutException:
        print_error(
            "The request timed out. Dailybot may be processing your update — "
            "please check your check-ins before retrying."
        )
    except APIError as e:
        print_error(e.detail)


def _view_pending(client: DailyBotClient) -> None:
    """Fetch and display pending check-ins."""
    try:
        with console.status("Fetching..."):
            data: dict[str, Any] = client.get_status()
        checkins: list[dict[str, Any]] = data.get("pending_checkins", [])
        print_pending_checkins(checkins)
    except APIError as e:
        print_error(e.detail)


def _show_auth(client: DailyBotClient) -> None:
    """Show current auth status."""
    try:
        data: dict[str, Any] = client.auth_status()
        user_raw: Any = data.get("user", "")
        email: str = (
            user_raw.get("email", "")
            if isinstance(user_raw, dict)
            else str(user_raw or data.get("email", ""))
        )
        org_raw: Any = data.get("organization", "")
        org_name: str = org_raw.get("name", "") if isinstance(org_raw, dict) else str(org_raw)
        org_uuid: str = org_raw.get("uuid", "") if isinstance(org_raw, dict) else ""
        msg: str = f"Logged in as {email} ({org_name})"
        if org_uuid:
            msg += f" | Org UUID: {org_uuid}"
        print_success(msg)
    except APIError as e:
        print_error(e.detail)
