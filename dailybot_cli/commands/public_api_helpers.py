"""Shared helpers for user-scoped public API commands."""

import json
import re
from collections.abc import Callable
from typing import Any, NoReturn

import click
import questionary

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.config import get_agent_auth, get_org_plan, load_credentials
from dailybot_cli.display import error_console, print_error, print_info

# Plan tiers the server treats as "free" (matched case-insensitively). Kept
# tolerant of naming so the client short-circuit activates once the API exposes
# the tier (see enforce_plan_access).
FREE_PLAN_TIERS: frozenset[str] = frozenset({"free", "free_plan", "freemium"})

# Action identifiers that remain usable under a free plan (the server's Bearer
# allowlist). A command whose action is in this set is NEVER short-circuited.
FREE_PLAN_ALLOWLIST: frozenset[str] = frozenset(
    {
        "agent_report",
        "agent_email",
        "agent_messages",
        "agent_health",
        "agent_register",
        "agent_claim",
        "me",
        "organization",
        "cli_status",
        "login",
        "logout",
    }
)

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
    # Check-in response lifecycle
    "user_is_not_a_followup_member": "You're not a participant in this check-in.",
    "responses_not_allowed_on_inactive_followup": (
        "This check-in is inactive — responses aren't allowed."
    ),
    "previous_responses_are_not_allowed": (
        "Backfilling past responses is disabled for this check-in."
    ),
    "future_responses_are_not_allowed": ("Future-dated responses are disabled for this check-in."),
    "followup_not_allow_responses_before_trigger_time": (
        "It's too early — this check-in isn't open yet (before its trigger time)."
    ),
    "not_valid_followup_uuid": "Invalid check-in UUID.",
    "template_questions_version_conflict": (
        "The check-in's questions changed since you fetched them. Re-run and try again."
    ),
    "response_date_format_is_invalid": "Invalid date. Use YYYY-MM-DD.",
    # Forms & check-ins authoring (create/edit/questions/responses)
    "invalid_question_type": (
        "Invalid question type. Use one of: text, multiple_choice, boolean, numeric."
    ),
    "multiple_choice_requires_options": (
        "Multiple-choice questions need at least one option (--options)."
    ),
    "question_label_required": "Question text is required.",
    "short_question_required": (
        'Each question needs a report title. Pass --short-question "<title>", or '
        "--ai-short-question to let Dailybot generate it."
    ),
    "questions_limit_exceeded": "Too many questions (the limit is 50).",
    "questions_required": (
        "At least one question is required. Seed questions with --questions-file or --interactive."
    ),
    "invalid_question_data": "A question payload is malformed. Check the question fields.",
    "form_name_required": "A name is required.",
    "invalid_schedule_days": ("Schedule days must be integers 0-6 (0=Sunday .. 6=Saturday)."),
    "invalid_schedule_time": "Schedule time must be in HH:MM format (e.g. 09:00).",
    "invalid_timezone": "Unknown timezone. Use an IANA name (e.g. America/New_York).",
    "checkin_permission_denied": (
        "Your role doesn't allow authoring check-ins. Ask an admin or manager. "
        "The CLI acts within your role and can't elevate."
    ),
    "form_edit_forbidden": (
        "You don't have permission to edit this form (you're not the owner or an admin). "
        "The CLI acts within your role and can't elevate."
    ),
    "form_response_view_all_forbidden": (
        "Only admins/owners can list everyone's responses (--all / --user). "
        "Without them you see only your own. The CLI acts within your role."
    ),
    "form_response_edit_forbidden": (
        "You can only edit your own response unless you're the form owner or an admin. "
        "The CLI acts within your role and can't elevate."
    ),
    "form_not_found": "Form not found.",
    "form_name_too_short": "Form name is too short (minimum 3 characters).",
    # Form configuration (workflow / permissions / approval / command)
    "workflow_requires_states": (
        'A workflow needs at least one state. Pass --state "Label:#color" (or '
        "--no-workflow to turn states off)."
    ),
    "invalid_workflow_state": (
        'Invalid workflow state. Use --state "Label:#color" with a non-empty label and a hex color.'
    ),
    "invalid_permission_audience": (
        "Invalid permission audience. Use everyone / owner_and_admins, or restricted "
        "with at least one user/team."
    ),
    "invalid_approvers": "Invalid approvers. Name at least one user or team to approve.",
    "invalid_command": (
        "Invalid --command. Use 1-31 chars: lowercase letters, digits, '-' or '_', "
        "starting with a letter or digit."
    ),
    "command_already_exists": (
        "That ChatOps command is already used by another form. Pick a different --command."
    ),
    "checkin_not_found": "Check-in not found.",
    "question_not_found": "Question not found on this form or check-in.",
    # Question reorder validation
    "question_uuids_required": "Reorder needs the list of question UUIDs to order.",
    "question_uuids_incomplete": (
        "Reorder must include ALL of the resource's question UUIDs, not a subset."
    ),
    "question_uuids_duplicate": "Reorder has a duplicate question UUID — list each one once.",
    "invalid_question_variations": (
        "Invalid question variations. Pass up to 10 non-empty alternate phrasings."
    ),
    # invalid_question_logic is intentionally NOT mapped: the server's detail names
    # the offending operator/target and lists the valid values for the question
    # type, which is more actionable than any generic message we could substitute.
    "anonymous_irreversible": (
        "An anonymous check-in cannot be made non-anonymous. Create a new check-in "
        "if you need non-anonymous responses."
    ),
    "report_channel_not_found": (
        "Report channel not found — run `dailybot channels list` to see the "
        "channels available in your organization."
    ),
    "too_many_report_channels": "Too many report channels — the limit is 3.",
    "checkin_requires_participant": (
        "A check-in must have at least one participant (a team or a person). "
        "Add --user and/or --team."
    ),
    # Check-in configuration validation
    "unknown_field": (
        "The server rejected an unrecognized field. Update the CLI "
        "(`dailybot upgrade`) — this build sent a field the API doesn't accept yet."
    ),
    "invalid_start_on": "Invalid start date. Use YYYY-MM-DD.",
    "invalid_end_on": "Invalid end date. Use YYYY-MM-DD.",
    "invalid_frequency_type": (
        "Invalid --frequency. Only 'weekly' is accepted; for monthly or custom "
        "cadences use --frequency-advanced (monthly / custom, with --cron for custom)."
    ),
    "invalid_frequency": "Invalid --every. Must be an integer >= 1.",
    "invalid_reminder_count": "Invalid --reminders. Must be an integer 0-5.",
    "invalid_reminder_interval": "Invalid --reminder-interval. Must be 0-60 minutes.",
    "invalid_reminder_condition": (
        "Invalid --reminder-condition. Use smart_frequency or fixed_frequency."
    ),
    "invalid_privacy": "Invalid --privacy value. See `dailybot checkin config --help`.",
    "invalid_time_for_report": "Invalid --report-time. Use HH:MM.",
    "invalid_reminder_tone": "Invalid --reminder-tone. Use standard or persuasive.",
    "invalid_max_clarifying_questions": "Invalid --max-clarifying. Must be an integer 0-5.",
    "intelligence_requires_smart_checkin": (
        "AI features need smart mode. Enable --smart before --intelligence, and "
        "--intelligence before --max-clarifying."
    ),
    "invalid_frequency_cron": (
        "Invalid --cron. Use a 5-field cron expression (e.g. '0 9 * * 1,3,5')."
    ),
    "invalid_frequency_advanced": (
        "Invalid --frequency-advanced. Use disabled, monthly, or custom."
    ),
    # Plan gating & capability (403) — dispatched on `code`, some augmented with
    # `extra` (upgrade_url, required/current role) in exit_for_api_error.
    "plan_upgrade_required": (
        "This action requires a paid Dailybot plan. On the free plan the CLI can "
        "only submit agent reports, send agent emails, and read your own profile."
    ),
    "plan_free_api_keys_forbidden": (
        "API keys aren't available on the free plan. Run `dailybot login` to use a "
        "personal session instead, or upgrade your plan."
    ),
    "plan_missing_core_api_integrations": (
        "Your organization's plan doesn't include this API capability. Enable the "
        "required integration or upgrade your plan."
    ),
    "api_key_owner_inactive": (
        "The API key's owner account is inactive. Rotate the key or contact an org admin."
    ),
    "insufficient_role": "Your role doesn't allow this action.",
    "member_in_scope_required": (
        "This action needs a target user in your organization. Pick a valid member."
    ),
    # Validation (400)
    "target_user_inactive": "That user is inactive. Choose an active user.",
    "search_query_too_long": (
        "Search term is too long (maximum 256 characters). Shorten it and try again."
    ),
    "invalid_date_range": (
        "Invalid date. Use YYYY-MM-DD, and make sure the start date is on or before the end date."
    ),
    # Rate limiting (429)
    "free_plan_daily_limit_exceeded": (
        "You've reached today's free-plan limit for this action. Wait for it to reset "
        "or upgrade your plan."
    ),
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


def _augment_code_message(base: str, code: str, extra: dict[str, Any]) -> str:
    """Enrich a code's base message with machine-readable `extra` context."""
    if code == "plan_upgrade_required":
        upgrade_url: Any = extra.get("upgrade_url")
        if upgrade_url:
            return f"{base} Upgrade at: {upgrade_url}"
    elif code == "insufficient_role":
        required: Any = extra.get("required_role")
        current: Any = extra.get("current_role")
        if required or current:
            detail_bits: str = ""
            if required:
                detail_bits += f" Required role: {required}."
            if current:
                detail_bits += f" Your role: {current}."
            return f"{base}{detail_bits}"
    return base


def exit_for_api_error(exc: APIError, json_mode: bool) -> NoReturn:
    """Map API failures to user-facing messages and process exit codes.

    Dispatches strictly on the machine-readable ``code`` (never on ``detail``
    text); falls back to the status-code-based message when ``code`` is absent
    (older backends).
    """
    code: str | None = getattr(exc, "code", None)
    extra: dict[str, Any] = getattr(exc, "extra", {}) or {}
    mapped_message: str | None = ERROR_CODE_MESSAGES.get(code) if code else None
    if mapped_message and code:
        mapped_message = _augment_code_message(mapped_message, code, extra)

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
        retry_after: float | None = getattr(exc, "retry_after", None)
        # A free-plan daily limit has its own code-specific copy; a generic 429
        # falls back to the retry-after message.
        if mapped_message:
            message = mapped_message
        elif retry_after:
            message = f"Rate limit exceeded. Try again in {int(retry_after)}s."
        else:
            message = "Rate limit exceeded. Wait a moment and try again."
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
        retry_after_seconds: float | None = getattr(exc, "retry_after", None)
        if exc.status_code == 429 and retry_after_seconds is not None:
            payload["retry_after_seconds"] = int(retry_after_seconds)
        emit_json(payload)
    else:
        print_error(message)
    raise SystemExit(exit_code)


def enforce_plan_access(action: str, *, json_mode: bool = False) -> None:
    """Short-circuit a non-allowlisted command when the active org is known-free.

    Optimization only — it saves a guaranteed-403 roundtrip. The server remains
    the source of truth: when the plan tier is **unknown** (the API hasn't
    exposed it, or no cache yet) this is a no-op and the call proceeds, so a
    stale/absent cache can never *block* a command the server would allow.
    Allowlisted (agent-scoped / me / org / cli-status) actions never short-circuit.
    """
    if action in FREE_PLAN_ALLOWLIST:
        return
    creds: dict[str, Any] | None = load_credentials()
    org_uuid: str | None = creds.get("organization_uuid") if creds else None
    tier: str | None = get_org_plan(org_uuid)
    if tier is not None and tier.lower() in FREE_PLAN_TIERS:
        # Reuse the Task 2 upgrade-message renderer + exit code (no second renderer).
        exit_for_api_error(
            APIError(403, "This action requires a paid plan.", code="plan_upgrade_required"),
            json_mode,
        )


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
    """Resolve a user UUID and display name from a UUID, email, or name fragment."""
    if UUID_PATTERN.match(identifier):
        for user in users:
            if user.get("uuid") == identifier:
                name: str = str(user.get("full_name") or identifier)
                return identifier, name
        return identifier, identifier

    if "@" in identifier:
        email_matches: list[dict[str, Any]] = [
            user for user in users if str(user.get("email", "")).lower() == identifier.lower()
        ]
        if len(email_matches) == 1:
            hit: dict[str, Any] = email_matches[0]
            return str(hit["uuid"]), str(hit.get("full_name") or hit.get("email") or hit["uuid"])
        if not email_matches:
            # The directory only exposes emails to admins/managers; if no user has
            # an email at all, the caller can't resolve by email — hint at that.
            if not any(user.get("email") for user in users):
                raise ValueError(
                    f'Cannot resolve "{identifier}" by email — email lookup needs '
                    "admin/manager permissions. Use the person's name or UUID instead."
                )
            raise ValueError(f'No user found with email "{identifier}".')

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
