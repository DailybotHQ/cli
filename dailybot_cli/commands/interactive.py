"""Interactive mode for Dailybot CLI."""

import readline  # noqa: F401 — enables arrow-key editing in input()
from typing import Any

import click
import httpx
import questionary

from dailybot_cli import __version__
from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.auth import _do_login
from dailybot_cli.commands.kudos import execute_kudos_give
from dailybot_cli.commands.public_api_helpers import get_current_user_uuid, pick_from_list
from dailybot_cli.commands.user_scoped_actions import (
    collect_form_content_interactive,
    execute_checkin_complete,
    execute_form_list,
    execute_form_submit,
    execute_user_list,
)
from dailybot_cli.config import get_api_url, get_token, load_credentials
from dailybot_cli.display import (
    console,
    print_checkin_list_overview,
    print_error,
    print_info,
    print_pending_checkins,
    print_success,
    print_update_result,
    print_warning,
)

MENU_PENDING_CHECKINS: str = "Fill in pending check-ins"
MENU_LIST_FORMS: str = "List forms"
MENU_SUBMIT_FORM: str = "Submit a form"
MENU_LIST_MEMBERS: str = "List team members"
MENU_GIVE_KUDOS: str = "Give kudos"
MENU_SEND_UPDATE: str = "Send free-text update"
MENU_AUTH_STATUS: str = "Auth status"
MENU_QUIT: str = "Quit"

MENU_CHOICES: list[str] = [
    MENU_PENDING_CHECKINS,
    MENU_LIST_FORMS,
    MENU_SUBMIT_FORM,
    MENU_LIST_MEMBERS,
    MENU_GIVE_KUDOS,
    MENU_SEND_UPDATE,
    MENU_AUTH_STATUS,
    MENU_QUIT,
]


def _checkin_label(checkin: dict[str, Any]) -> str:
    name: str = str(checkin.get("followup_name") or "Check-in")
    question_count: int = len(checkin.get("template_questions", []))
    return f"{name} ({question_count} question{'s' if question_count != 1 else ''})"


def _form_label(form: dict[str, Any]) -> str:
    name: str = str(form.get("name") or form.get("id") or "Form")
    active: bool = bool(form.get("is_active"))
    suffix: str = "" if active else " [inactive]"
    return f"{name}{suffix}"


def _user_label(user: dict[str, Any]) -> str:
    return str(user.get("full_name") or user.get("uuid") or "Unknown")


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
        elif choice == MENU_PENDING_CHECKINS:
            _fill_pending_checkins(client)
        elif choice == MENU_LIST_FORMS:
            _list_forms(client)
        elif choice == MENU_SUBMIT_FORM:
            _submit_form(client)
        elif choice == MENU_LIST_MEMBERS:
            _list_members(client)
        elif choice == MENU_GIVE_KUDOS:
            _give_kudos(client)
        elif choice == MENU_SEND_UPDATE:
            _send_update(client)
        elif choice == MENU_AUTH_STATUS:
            _show_auth(client)


def _fill_pending_checkins(client: DailyBotClient) -> None:
    """Show pending check-ins, then guide the user through completing one."""
    try:
        with console.status("Fetching pending check-ins..."):
            status_data: dict[str, Any] = client.get_status()
    except APIError as e:
        print_error(e.detail)
        return

    checkins: list[dict[str, Any]] = status_data.get("pending_checkins", [])
    count: int = int(status_data.get("count", len(checkins)))
    print_checkin_list_overview(count, checkins)
    if not checkins:
        return

    print_pending_checkins(checkins)

    if len(checkins) == 1:
        should_complete: bool = questionary.confirm(
            "Fill in this check-in now?",
            default=True,
        ).ask()
        if not should_complete:
            return
        selected = checkins[0]
    else:
        selected = pick_from_list(
            checkins,
            "Which check-in do you want to fill in?",
            _checkin_label,
        )
        if selected is None:
            print_info("Cancelled.")
            return

    followup_uuid: str = str(selected.get("followup_uuid", ""))
    if not followup_uuid:
        print_error("Selected check-in has no followup UUID.")
        return

    try:
        execute_checkin_complete(
            client,
            followup_uuid,
            status_data=status_data,
        )
    except SystemExit:
        return


def _list_forms(client: DailyBotClient) -> None:
    """List forms visible to the user."""
    try:
        execute_form_list(client)
    except SystemExit:
        return


def _submit_form(client: DailyBotClient) -> None:
    """Pick a form and submit answers interactively."""
    try:
        with console.status("Fetching forms..."):
            forms: list[dict[str, Any]] = client.list_forms()
    except APIError as e:
        print_error(e.detail)
        return

    if not forms:
        print_info("No forms visible to you.")
        return

    selected: dict[str, Any] | None = pick_from_list(
        forms,
        "Which form do you want to submit?",
        _form_label,
    )
    if selected is None:
        print_info("Cancelled.")
        return

    form_uuid: str = str(selected.get("id") or "")
    form_name: str = str(selected.get("name") or form_uuid)
    if not form_uuid:
        print_error("Selected form has no UUID.")
        return

    print_info(
        "Enter each answer by question UUID. "
        "When the API exposes form question definitions, the CLI will prompt by label."
    )
    try:
        content_map: dict[str, Any] = collect_form_content_interactive()
        execute_form_submit(
            client,
            form_uuid,
            content_map,
            form_name=form_name,
        )
    except SystemExit:
        return


def _list_members(client: DailyBotClient) -> None:
    """List organization members."""
    try:
        execute_user_list(client)
    except SystemExit:
        return


def _give_kudos(client: DailyBotClient) -> None:
    """Pick a teammate and send kudos interactively."""
    try:
        with console.status("Loading team members..."):
            users: list[dict[str, Any]] = client.list_users()
            current_uuid: str | None = get_current_user_uuid(client)
    except APIError as e:
        print_error(e.detail)
        return

    teammates: list[dict[str, Any]] = [
        user
        for user in users
        if str(user.get("uuid", "")) != str(current_uuid or "")
    ]
    if not teammates:
        print_error("No teammates available to receive kudos.")
        return

    selected_user: dict[str, Any] | None = pick_from_list(
        teammates,
        "Who should receive kudos?",
        _user_label,
    )
    if selected_user is None:
        print_info("Cancelled.")
        return

    message: str | None = questionary.text("Kudos message (team-visible):").ask()
    if message is None:
        print_info("Cancelled.")
        return
    message = message.strip()
    if not message:
        print_error("Empty message. Nothing sent.")
        return

    receiver_uuid: str = str(selected_user["uuid"])
    receiver_name: str = str(selected_user.get("full_name") or receiver_uuid)

    try:
        execute_kudos_give(
            client,
            receiver_uuid,
            receiver_name,
            message,
            current_uuid,
        )
    except SystemExit:
        return


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
