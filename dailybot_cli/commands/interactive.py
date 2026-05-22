"""Interactive mode for Dailybot CLI."""

import readline  # noqa: F401 — enables arrow-key editing in input()
import sys
from typing import Any

import click
import httpx
import questionary
from questionary import Choice, Separator

from dailybot_cli import __version__
from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.auth import _do_login
from dailybot_cli.commands.kudos import execute_kudos_give
from dailybot_cli.commands.public_api_helpers import (
    InteractiveAbort,
    get_current_user_uuid,
    pick_from_list,
)
from dailybot_cli.commands.user_scoped_actions import (
    collect_form_content_guided,
    execute_checkin_complete,
    execute_form_list,
    execute_form_submit,
    execute_user_list,
    filter_submittable_forms,
)
from dailybot_cli.config import get_api_url, get_token, load_credentials
from dailybot_cli.display import (
    console,
    print_error,
    print_info,
    print_success,
    print_update_result,
    print_warning,
)

# Stable action IDs — dispatch is keyed on these, never on display strings.
ACTION_CHECKIN_COMPLETE: str = "checkin.complete"
ACTION_CHECKIN_UPDATE: str = "checkin.update"
ACTION_FORM_LIST: str = "form.list"
ACTION_FORM_SUBMIT: str = "form.submit"
ACTION_TEAM_LIST: str = "team.list"
ACTION_TEAM_KUDOS: str = "team.kudos"
ACTION_SESSION_INFO: str = "session.info"
ACTION_EXIT: str = "exit"

# Build the grouped menu once.  Separators are section headers (non-selectable).
_I: str = "  "  # indent for action items — 2 spaces under each section header

MENU_CHOICES: list[Choice | Separator] = [
    Separator("Check-ins"),
    Choice(_I + "Complete pending check-ins", value=ACTION_CHECKIN_COMPLETE),
    Choice(_I + "Send free-text update", value=ACTION_CHECKIN_UPDATE),
    Separator("Forms"),
    Choice(_I + "List forms", value=ACTION_FORM_LIST),
    Choice(_I + "Submit a form", value=ACTION_FORM_SUBMIT),
    Separator("Team"),
    Choice(_I + "List team members", value=ACTION_TEAM_LIST),
    Choice(_I + "Give kudos", value=ACTION_TEAM_KUDOS),
    Separator("Session"),
    Choice(_I + "View session info", value=ACTION_SESSION_INFO),
    Separator(""),
    Choice("Exit", value=ACTION_EXIT),
]

# Action → handler lookup — keeps run_interactive() free of long if/elif chains.
_HANDLER_MAP: dict[str, str] = {
    ACTION_CHECKIN_COMPLETE: "_fill_pending_checkins",
    ACTION_CHECKIN_UPDATE: "_send_update",
    ACTION_FORM_LIST: "_list_forms",
    ACTION_FORM_SUBMIT: "_submit_form",
    ACTION_TEAM_LIST: "_list_members",
    ACTION_TEAM_KUDOS: "_give_kudos",
    ACTION_SESSION_INFO: "_show_auth",
}


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


def _return_to_menu() -> None:
    """Abort the current action and return to the main menu (Esc)."""
    print_info("Cancelled.")


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
            org: str = (
                org_stored.get("name", "") if isinstance(org_stored, dict) else str(org_stored)
            )
            org_uuid: str = creds.get("organization_uuid", "") if creds else ""
            console.print(f"Logged in as {email} ({org})")
            if org_uuid:
                console.print(f"[dim]Org UUID: {org_uuid}[/dim]")
    console.print()

    client: DailyBotClient = DailyBotClient()

    while True:
        console.print()
        action: str | None = questionary.select(
            "What would you like to do?",
            choices=MENU_CHOICES,
        ).ask()

        # None means the user pressed Esc/Ctrl-C at the top-level menu — stay in
        # the loop so they can keep navigating (Quit is the explicit exit path).
        if action is None:
            continue

        if action == ACTION_EXIT:
            print_info("Goodbye!")
            break

        handler_name: str | None = _HANDLER_MAP.get(action)
        if handler_name is None:
            continue

        handler = getattr(sys.modules[__name__], handler_name)
        try:
            handler(client)
        except InteractiveAbort:
            _return_to_menu()


def _fill_pending_checkins(client: DailyBotClient) -> None:
    """Pick a pending check-in and guide the user through completing it."""
    try:
        with console.status("Fetching pending check-ins..."):
            status_data: dict[str, Any] = client.get_status()
    except APIError as e:
        print_error(e.detail)
        return

    checkins: list[dict[str, Any]] = status_data.get("pending_checkins", [])
    if not checkins:
        print_info("No pending check-ins.")
        return

    selected: dict[str, Any] | None = pick_from_list(
        checkins,
        "Which check-in do you want to complete?",
        _checkin_label,
        numbered_fallback=False,
    )
    if selected is None:
        raise InteractiveAbort()

    followup_uuid: str = str(selected.get("followup_uuid", ""))
    if not followup_uuid:
        print_error("Selected check-in has no followup UUID.")
        return

    try:
        execute_checkin_complete(
            client,
            followup_uuid,
            status_data=status_data,
            interactive=True,
            assume_yes=True,
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
            forms: list[dict[str, Any]] = filter_submittable_forms(
                client.list_forms(include_questions=False)
            )
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
        numbered_fallback=False,
    )
    if selected is None:
        raise InteractiveAbort()

    form_uuid: str = str(selected.get("id") or "")
    form_name: str = str(selected.get("name") or form_uuid)
    if not form_uuid:
        print_error("Selected form has no UUID.")
        return

    try:
        content_map: dict[str, Any] = collect_form_content_guided(
            client,
            form_uuid,
            interactive=True,
        )
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
        user for user in users if str(user.get("uuid", "")) != str(current_uuid or "")
    ]
    if not teammates:
        print_error("No teammates available to receive kudos.")
        return

    selected_user: dict[str, Any] | None = pick_from_list(
        teammates,
        "Who should receive kudos?",
        _user_label,
        numbered_fallback=False,
    )
    if selected_user is None:
        raise InteractiveAbort()

    message: str | None = questionary.text("Kudos message (team-visible):").ask()
    if message is None:
        raise InteractiveAbort()
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
            assume_yes=True,
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
