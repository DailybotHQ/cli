"""Shared helpers for user-scoped public API commands."""

import json
import re
from collections.abc import Callable
from typing import Any, NoReturn

import click
import questionary

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.config import get_agent_auth
from dailybot_cli.display import error_console, print_error, print_info

USER_SCOPED_MODEL_HELP: str = (
    "Acts as you. You can only see and act on what you could in the webapp."
)

EXIT_USAGE_ERROR: int = 2
EXIT_NOT_AUTHENTICATED: int = 3
EXIT_PERMISSION_DENIED: int = 4
EXIT_NOT_FOUND: int = 5
EXIT_QUOTA_EXHAUSTED: int = 5
EXIT_RATE_LIMITED: int = 6
EXIT_USER_ABORTED: int = 7

# Server-side error codes from {detail, code} responses. Kept here so command
# handlers and tests share a single source of truth.
ERROR_CODE_MESSAGES: dict[str, str] = {
    "form_response_change_state_forbidden": (
        "You don't have permission to change the state of this submission. "
        "The form's audience may restrict transitions to specific users / teams. "
        "Ask the form owner."
    ),
    "final_state_locked": (
        "This response is in the final workflow state and the form doesn't allow "
        "reopening. Ask the form owner to enable `allow_reopen_from_final_state`."
    ),
    "form_response_delete_forbidden": (
        "You can't delete this response (you're not the author, form owner, or org admin)."
    ),
    "user_can_not_see_form_responses": (
        "You don't have permission to read responses on this form."
    ),
    "form_response_not_found": "Response not found.",
    "form_does_not_exists": "Form not found.",
    "payload_too_large": "Payload too large.",
    "no_valid_team": "Team not found. Check `dailybot team list`.",
    "no_valid_users": (
        "Empty receiver set — `--to` or `--team` must resolve to at least one valid receiver."
    ),
    "no_users_found": "Some users not found or duplicated.",
}


class InteractiveAbort(Exception):
    """Raised when the user cancels an interactive prompt (e.g. Esc)."""


UUID_PATTERN: re.Pattern[str] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def require_auth() -> DailyBotClient:
    """Ensure a login session or API key exists and return a client.

    User-scoped endpoints accept either a Bearer login token or an org API key,
    so this helper succeeds under either credential and only fails when neither
    is present.
    """
    if get_agent_auth() is None:
        print_error("Not authenticated. Run: dailybot login or set DAILYBOT_API_KEY")
        raise SystemExit(EXIT_NOT_AUTHENTICATED)
    return DailyBotClient()


def emit_json(data: Any) -> None:
    """Print machine-readable JSON to stdout."""
    click.echo(json.dumps(data))


def emit_json_error(message: str, status: int) -> None:
    """Print a machine-readable error object to stdout."""
    emit_json({"error": message, "status": status})


def exit_for_api_error(exc: APIError, json_mode: bool) -> NoReturn:
    """Map API failures to user-facing messages and process exit codes."""
    code: str | None = getattr(exc, "code", None)
    mapped_message: str | None = ERROR_CODE_MESSAGES.get(code) if code else None

    if exc.status_code == 401:
        message: str = "Session expired. Run: dailybot login"
        exit_code: int = EXIT_NOT_AUTHENTICATED
    elif exc.status_code == 403:
        message = mapped_message or exc.detail
        exit_code = EXIT_PERMISSION_DENIED
    elif exc.status_code == 404:
        message = mapped_message or exc.detail
        exit_code = EXIT_NOT_FOUND
    elif exc.status_code == 402:
        message = "Form response quota exhausted for your organization."
        exit_code = EXIT_QUOTA_EXHAUSTED
    elif exc.status_code == 406:
        message = "Daily kudos limit reached."
        exit_code = EXIT_PERMISSION_DENIED
    elif exc.status_code == 429:
        message = "Rate limit exceeded (60 requests/minute). Wait and try again."
        exit_code = EXIT_RATE_LIMITED
    elif exc.status_code == 400:
        message = mapped_message or exc.detail
        exit_code = EXIT_USAGE_ERROR
    else:
        message = mapped_message or exc.detail
        exit_code = 1

    if json_mode:
        payload: dict[str, Any] = {"error": message, "status": exc.status_code}
        if code:
            payload["code"] = code
        if exc.detail and exc.detail != message:
            payload["detail"] = exc.detail
        emit_json(payload)
    else:
        print_error(message)
    raise SystemExit(exit_code)


def confirm_write(summary_lines: list[str], assume_yes: bool) -> None:
    """Prompt for confirmation before a team-visible write."""
    if assume_yes:
        return

    for line in summary_lines:
        error_console.print(line)

    if not click.confirm(
        "Proceed? This will be visible to your team.",
        default=False,
    ):
        error_console.print("[dim]Aborted.[/dim]")
        raise SystemExit(EXIT_USER_ABORTED)


def normalize_checkin_list_json(data: dict[str, Any]) -> dict[str, Any]:
    """Add derived 0-based question indexes for JSON consumers."""
    pending: list[dict[str, Any]] = []
    for checkin in data.get("pending_checkins", []):
        questions: list[dict[str, Any]] = []
        for index, question in enumerate(checkin.get("template_questions", [])):
            enriched: dict[str, Any] = dict(question)
            enriched["index"] = index
            questions.append(enriched)
        entry: dict[str, Any] = dict(checkin)
        entry["template_questions"] = questions
        pending.append(entry)
    return {"pending_checkins": pending, "count": data.get("count", len(pending))}


def find_pending_checkin(
    pending_checkins: list[dict[str, Any]],
    followup_uuid: str,
) -> dict[str, Any] | None:
    """Return the pending check-in matching followup_uuid, if present."""
    for checkin in pending_checkins:
        if checkin.get("followup_uuid") == followup_uuid:
            return checkin
    return None


def parse_answer_flags(answers: tuple[str, ...]) -> dict[int, str]:
    """Parse repeatable ``index=response`` answer flags."""
    parsed: dict[int, str] = {}
    for raw in answers:
        if "=" not in raw:
            raise ValueError(f'Invalid answer format "{raw}". Use index=response (e.g. 0=Done).')
        index_str, response = raw.split("=", 1)
        try:
            index: int = int(index_str.strip())
        except ValueError as exc:
            raise ValueError(f'Invalid answer index "{index_str}".') from exc
        parsed[index] = response
    return parsed


def resolve_user_by_name_or_uuid(
    users: list[dict[str, Any]],
    identifier: str,
) -> tuple[str, str]:
    """Resolve a user UUID and display name from a UUID or name fragment."""
    if UUID_PATTERN.match(identifier):
        for user in users:
            if user.get("uuid") == identifier:
                name: str = str(user.get("full_name") or identifier)
                return identifier, name
        return identifier, identifier

    exact_matches: list[dict[str, Any]] = [
        user for user in users if str(user.get("full_name", "")).lower() == identifier.lower()
    ]
    if len(exact_matches) == 1:
        match: dict[str, Any] = exact_matches[0]
        return str(match["uuid"]), str(match.get("full_name") or match["uuid"])

    partial_matches: list[dict[str, Any]] = [
        user for user in users if identifier.lower() in str(user.get("full_name", "")).lower()
    ]
    if len(partial_matches) == 1:
        match = partial_matches[0]
        return str(match["uuid"]), str(match.get("full_name") or match["uuid"])
    if len(partial_matches) > 1:
        names: str = ", ".join(str(user.get("full_name", "")) for user in partial_matches)
        raise ValueError(f'Ambiguous receiver "{identifier}". Matches: {names}')

    raise ValueError(f'No user found matching "{identifier}".')


def resolve_team_by_name_or_uuid(
    teams: list[dict[str, Any]],
    identifier: str,
) -> tuple[str, str]:
    """Resolve a team UUID and name from a UUID or case-insensitive name match.

    The scoping is enforced server-side by GET /v1/teams/ — admins see all org
    teams, members see only their own. The CLI never client-filters.
    """
    if UUID_PATTERN.match(identifier):
        for team in teams:
            if str(team.get("uuid")) == identifier:
                name: str = str(team.get("name") or identifier)
                return identifier, name
        return identifier, identifier

    target: str = identifier.lower()
    exact_matches: list[dict[str, Any]] = [
        team for team in teams if str(team.get("name", "")).lower() == target
    ]
    if len(exact_matches) == 1:
        match: dict[str, Any] = exact_matches[0]
        return str(match["uuid"]), str(match.get("name") or match["uuid"])
    if len(exact_matches) > 1:
        names: str = ", ".join(str(team.get("name", "")) for team in exact_matches)
        raise ValueError(f'Ambiguous team "{identifier}". Matches: {names}')

    partial_matches: list[dict[str, Any]] = [
        team for team in teams if target in str(team.get("name", "")).lower()
    ]
    if len(partial_matches) == 1:
        match = partial_matches[0]
        return str(match["uuid"]), str(match.get("name") or match["uuid"])
    if len(partial_matches) > 1:
        names = ", ".join(str(team.get("name", "")) for team in partial_matches)
        raise ValueError(f'Ambiguous team "{identifier}". Matches: {names}')

    raise ValueError(
        f"No team named '{identifier}' visible to you. You may not be a member, "
        "or it doesn't exist. Org admins see all teams; members see only their "
        "own. Run `dailybot team list` to confirm."
    )


def get_current_user_uuid(client: DailyBotClient) -> str | None:
    """Return the authenticated user's UUID from auth status, if available.

    Reads the Bearer-only ``/v1/cli/auth/status/`` endpoint. Under API-key
    authentication that endpoint rejects the request, so this returns ``None``
    rather than propagating the error — callers treat an unknown current user as
    "skip the client-side self-check" and let the server enforce its own rules.
    """
    try:
        data: dict[str, Any] = client.auth_status()
    except APIError:
        return None
    user_raw: Any = data.get("user")
    if isinstance(user_raw, dict):
        uuid_value: Any = user_raw.get("uuid")
        if uuid_value:
            return str(uuid_value)
    return None


def pick_from_list(
    items: list[Any],
    prompt: str,
    label_fn: Callable[[Any], str],
    *,
    numbered_fallback: bool = True,
) -> Any | None:
    """Pick an item with questionary, falling back to a numbered list."""
    if not items:
        return None

    choices: list[questionary.Choice] = [
        questionary.Choice(title=label_fn(item), value=item) for item in items
    ]
    selected: Any | None = questionary.select(prompt, choices=choices).ask()
    if selected is not None:
        return selected
    if not numbered_fallback:
        return None

    print_info("Select by number:")
    for index, item in enumerate(items, start=1):
        click.echo(f"  {index}. {label_fn(item)}")

    while True:
        choice: int = click.prompt("Number", type=int)
        if 1 <= choice <= len(items):
            return items[choice - 1]
        print_error(f"Enter a number between 1 and {len(items)}.")
