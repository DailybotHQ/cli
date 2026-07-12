"""Form commands for the user-scoped public API."""

import re
from collections.abc import Callable
from typing import Any

import click

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.authoring_helpers import (
    build_question,
    build_question_edit_fields,
    build_questions_interactively,
    check_report_channels,
    parse_options,
    parse_questions_file,
    question_extras_options,
    require_questions,
    require_short_question,
    require_short_questions,
    resolve_form_config,
    resolve_question_extras,
)
from dailybot_cli.commands.public_api_helpers import (
    confirm_write,
    emit_json,
    enforce_plan_access,
    exit_for_api_error,
    require_auth,
    validate_user_filter,
)
from dailybot_cli.commands.query_options import (
    build_query_params,
    paging_options,
    query_options,
)
from dailybot_cli.commands.user_scoped_actions import (
    execute_form_list,
    execute_form_submit,
    parse_form_content_json,
    resolve_form_content,
)
from dailybot_cli.display import (
    console,
    print_archived,
    print_error,
    print_form_created,
    print_form_detail,
    print_form_response_deleted,
    print_form_response_detail,
    print_form_response_state,
    print_form_responses_table,
    print_pagination_footer,
    print_question,
    print_questions_table,
    print_reordered,
    print_success,
)

# The server reuses `invalid_workflow_state` for a malformed `--state
# "Label:#color"` during authoring. On this listing it means the form has no
# workflow at all, so the shared message would send the user down the wrong path.
MAX_SUBMISSION_SOURCE_LENGTH: int = 512
_EMAIL_RE: re.Pattern[str] = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

FORM_LIST_FILTERS: tuple[str, ...] = ("all", "me", "public", "approval", "workflow", "archived")
FORM_LIST_ORDERS: tuple[str, ...] = ("alphabetical", "recent", "total")
RESPONSE_ORDERS: tuple[str, ...] = ("recent", "oldest")
RESPONSE_SOURCES: tuple[str, ...] = ("member", "anonymous", "automation", "public")
RESPONSE_FLOW_STATUSES: tuple[str, ...] = ("pending", "approved", "denied")
MAX_SUBMITTER_IDS: int = 50

_RESPONSES_ERROR_OVERRIDES: dict[str, str] = {
    "invalid_workflow_state": (
        "This form has no workflow, so --state doesn't apply. Drop the flag, or run "
        "`dailybot form get <form_uuid>` to see the states a workflow form defines."
    ),
}


def _maybe_load_form(client: DailyBotClient, form_uuid: str) -> dict[str, Any] | None:
    """Return form metadata if accessible; swallow errors (UI-only enrichment)."""
    try:
        return client.get_form(form_uuid)
    except APIError:
        return None


def _form_config_flag_options(func: Callable[..., Any]) -> Callable[..., Any]:
    """Attach the shared form-configuration flags to create + config.

    Dest names match ``authoring_helpers.resolve_form_config`` kwargs so the
    callback can forward them as ``**config_flags``. Toggle flags default to
    ``None`` (unset → not sent), keeping ``config`` a partial update.
    """
    options: list[Callable[..., Any]] = [
        click.option("--active/--inactive", "is_active", default=None, help="Activate/deactivate."),
        click.option(
            "--anonymous/--no-anonymous",
            "is_anonymous",
            default=None,
            help="Collect responses anonymously.",
        ),
        click.option(
            "--public/--no-public",
            "allow_public_responses",
            default=None,
            help="Allow public (shared-link) responses.",
        ),
        click.option(
            "--brand/--no-brand",
            "brand_with_logo",
            default=None,
            help="Brand the public form with your org logo.",
        ),
        click.option(
            "--require-identity/--no-require-identity",
            "require_email_and_name",
            default=None,
            help="Make email + name mandatory on public responses.",
        ),
        click.option(
            "--reopen-from-final/--no-reopen-from-final",
            "allow_reopen_from_final_state",
            default=None,
            help="Allow moving a response out of the final state.",
        ),
        click.option(
            "--state",
            "states",
            multiple=True,
            help='Workflow state "Label:#color" (repeatable, ordered). Enables the workflow.',
        ),
        click.option(
            "--no-workflow", "no_workflow", is_flag=True, help="Turn the workflow/states off."
        ),
        click.option(
            "--can-edit", "can_edit", default=None, help="everyone / owner_and_admins / restricted."
        ),
        click.option("--can-edit-user", "can_edit_users", multiple=True, help="Restricted editor."),
        click.option("--can-edit-team", "can_edit_teams", multiple=True, help="Restricted editor."),
        click.option(
            "--can-see", "can_see", default=None, help="everyone / owner_and_admins / restricted."
        ),
        click.option("--can-see-user", "can_see_users", multiple=True, help="Restricted viewer."),
        click.option("--can-see-team", "can_see_teams", multiple=True, help="Restricted viewer."),
        click.option(
            "--can-change-states",
            "can_change_states",
            default=None,
            help="everyone / owner_and_admins / restricted.",
        ),
        click.option(
            "--change-states-user", "change_states_users", multiple=True, help="Restricted mover."
        ),
        click.option(
            "--change-states-team", "change_states_teams", multiple=True, help="Restricted mover."
        ),
        click.option(
            "--approval/--no-approval",
            "use_for_approval",
            default=None,
            help="File new submissions for approval.",
        ),
        click.option(
            "--approver-user",
            "approver_users",
            multiple=True,
            help="Approver (name, email, or UUID).",
        ),
        click.option(
            "--approver-team", "approver_teams", multiple=True, help="Approver team (name or UUID)."
        ),
        click.option(
            "--no-approvers", "no_approvers", is_flag=True, help="Clear the approver list."
        ),
        click.option("--command", "command", default=None, help="ChatOps shortcut name."),
        click.option(
            "--no-command", "no_command", is_flag=True, help="Remove the ChatOps shortcut."
        ),
    ]
    for option in reversed(options):
        func = option(func)
    return func


@click.group()
def form() -> None:
    """Manage forms with your Dailybot session.

    \b
    Acts as you — visibility and permissions match the webapp for your account.
    """


@form.command("list")
@click.option(
    "--include-archived",
    is_flag=True,
    help="Include archived forms (hidden by default).",
)
@click.option(
    "--mine",
    is_flag=True,
    help="Only forms you own (default lists every form you can see in the org).",
)
@click.option(
    "--filter",
    "filter_scope",
    type=click.Choice(FORM_LIST_FILTERS, case_sensitive=False),
    default=None,
    help="Scope filter: all, me, public, approval, workflow, archived.",
)
@click.option(
    "--order",
    type=click.Choice(FORM_LIST_ORDERS, case_sensitive=False),
    default=None,
    help="Sort order: alphabetical, recent, or total responses.",
)
@click.option(
    "--ascending",
    "--asc",
    "is_ascend",
    is_flag=True,
    default=False,
    help="Sort ascending (default: descending).",
)
@click.option(
    "--include-questions",
    is_flag=True,
    default=False,
    help="Include question definitions in each form.",
)
@query_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_list(
    include_archived: bool,
    mine: bool,
    filter_scope: str | None,
    order: str | None,
    is_ascend: bool,
    include_questions: bool,
    json_mode: bool,
    page: int | None,
    page_size: int | None,
    fetch_all: bool,
    limit: int | None,
    search: str | None,
    since: str | None,
    until: str | None,
    on_date: str | None,
    last_week: bool,
    today: bool,
) -> None:
    """List forms visible to you.

    \b
    Acts as you. You can only see and act on what you could in the webapp:
    by default this is every form in your org you have list-view access to.
    Pass --mine to narrow to only the forms you own, or --filter to scope.
    Archived forms are hidden unless you pass --include-archived or --filter archived.

    \b
    Examples:
      dailybot form list
      dailybot form list --mine
      dailybot form list --filter workflow --order alphabetical --asc
      dailybot form list --filter approval
      dailybot form list --filter public --order total
      dailybot form list --search retro --since 2026-07-01
      dailybot form list --include-questions --json
      dailybot form list --all
    """
    enforce_plan_access("form_list", json_mode=json_mode)
    try:
        spec = build_query_params(
            page=page,
            page_size=page_size,
            fetch_all=fetch_all,
            limit=limit,
            search=search,
            since=since,
            until=until,
            on_date=on_date,
            last_week=last_week,
            today=today,
        )
    except ValueError as exc:
        print_error(str(exc))
        raise SystemExit(1)
    client = require_auth()
    execute_form_list(
        client,
        json_mode=json_mode,
        include_archived=include_archived,
        include_questions=include_questions,
        owner="me" if mine else None,
        filter_scope=filter_scope,
        order=order,
        is_ascend=is_ascend,
        spec=spec,
    )


@form.command("get")
@click.argument("form_uuid")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_get(form_uuid: str, json_mode: bool) -> None:
    """Get a form's full payload (questions + workflow states + permissions).

    \b
    Acts as you. You can only see and act on what you could in the webapp.

    \b
    Examples:
      dailybot form get <form_uuid>
      dailybot form get <form_uuid> --json
    """
    client = require_auth()
    try:
        with console.status("Loading form..."):
            data: dict[str, Any] = client.get_form(form_uuid)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(data)
        return
    print_form_detail(data)


@form.command("submit")
@click.argument("form_uuid")
@click.option(
    "--content",
    "-c",
    default=None,
    help="JSON map of question UUID to answer. When omitted, prompts each question in order.",
)
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
@click.option(
    "--automation",
    is_flag=True,
    default=False,
    help=(
        "Submit as an automation. The response will appear in channel "
        "notifications without any submitter name — useful when "
        "forwarding third-party form submissions via integrations."
    ),
)
@click.option(
    "--anonymous",
    is_flag=True,
    default=False,
    help=(
        "Submit anonymously. The response will appear with a random "
        "generated name instead of your real name."
    ),
)
@click.option(
    "--guest-name",
    default=None,
    help="Guest submitter name (used with --automation for third-party submissions).",
)
@click.option(
    "--guest-email",
    default=None,
    help="Guest submitter email (used with --automation for third-party submissions).",
)
@click.option(
    "--source",
    default=None,
    help="Provenance label for this submission (max 512 chars, e.g. 'workflow:release-pipeline').",
)
def form_submit(
    form_uuid: str,
    content: str | None,
    assume_yes: bool,
    json_mode: bool,
    automation: bool,
    anonymous: bool,
    guest_name: str | None,
    guest_email: str | None,
    source: str | None,
) -> None:
    """Submit a form response.

    \b
    Acts as you. You can only see and act on what you could in the webapp.

    When --content is omitted, the CLI loads the form via GET /v1/forms/{uuid}/
    and prompts each question one by one (same flow as completing a check-in).

    \b
    Examples:
      dailybot form submit <form_uuid>
      dailybot form submit <form_uuid> --content '{"<question_uuid>":"Yes"}'
      dailybot form submit <form_uuid> --content '{"<uuid>":"Answer"}' --yes
      dailybot form submit <form_uuid> --content '{"<uuid>":"A"}' --automation
      dailybot form submit <form_uuid> --content '{"<uuid>":"A"}' --anonymous
      dailybot form submit <form_uuid> --content '{"<uuid>":"A"}' --automation \\
        --guest-name "Release Bot" --guest-email "bot@example.com" \\
        --source "workflow:production-deploy"
    """
    if guest_email and not _EMAIL_RE.match(guest_email):
        print_error(f"Invalid email format: {guest_email}")
        raise SystemExit(1)
    if source and len(source) > MAX_SUBMISSION_SOURCE_LENGTH:
        print_error(
            f"--source is too long ({len(source)} chars, max {MAX_SUBMISSION_SOURCE_LENGTH})."
        )
        raise SystemExit(1)

    guest_user: dict[str, str] | None = None
    if guest_name or guest_email:
        guest_user = {}
        if guest_name:
            guest_user["full_name"] = guest_name
        if guest_email:
            guest_user["email"] = guest_email

    client = require_auth()
    content_map = resolve_form_content(client, form_uuid, content)
    execute_form_submit(
        client,
        form_uuid,
        content_map,
        assume_yes=assume_yes,
        json_mode=json_mode,
        automation=automation,
        anonymous=anonymous,
        guest_user=guest_user,
        submission_source=source,
    )


@form.command("responses")
@click.argument("form_uuid")
@click.option(
    "--state",
    default=None,
    help="Filter by workflow state key (e.g. draft, not Draft). Workflow forms only.",
)
@click.option(
    "--all",
    "all_responses",
    is_flag=True,
    help="List everyone's responses (requires VIEW_REPORTS permission).",
)
@click.option("--user", default=None, help="Filter to one user's responses (admin/owner only).")
@click.option(
    "--source",
    "submission_sources",
    default=None,
    help="Filter by origin (CSV: member, anonymous, automation, public).",
)
@click.option(
    "--submitter",
    "submitter_ids",
    default=None,
    help="Filter by submitter UUIDs (CSV, max 50).",
)
@click.option(
    "--flow-status",
    "flow_status",
    type=click.Choice(RESPONSE_FLOW_STATUSES, case_sensitive=False),
    default=None,
    help="Approval flow status: pending, approved, denied.",
)
@click.option(
    "--order",
    type=click.Choice(RESPONSE_ORDERS, case_sensitive=False),
    default=None,
    help="Sort order: recent or oldest.",
)
@click.option(
    "--ascending",
    "--asc",
    "is_ascend",
    is_flag=True,
    default=False,
    help="Sort ascending (alias for --order oldest).",
)
@click.option(
    "--from", "date_from", default=None, help="Responses on/after this date (YYYY-MM-DD)."
)
@click.option("--to", "date_to", default=None, help="Responses on/before this date (YYYY-MM-DD).")
@click.option(
    "--search", "-s", "search", default=None, help="Search content and submitter (max 256 chars)."
)
@click.option(
    "--latest",
    is_flag=True,
    help="Return only the most recent response (continue where you left off).",
)
@paging_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_responses(
    form_uuid: str,
    state: str | None,
    all_responses: bool,
    user: str | None,
    submission_sources: str | None,
    submitter_ids: str | None,
    flow_status: str | None,
    order: str | None,
    is_ascend: bool,
    date_from: str | None,
    date_to: str | None,
    search: str | None,
    latest: bool,
    page: int | None,
    page_size: int | None,
    limit: int | None,
    json_mode: bool,
) -> None:
    """List responses on a form.

    \b
    Acts as you. By default the server returns only responses you authored.
    --all / --user surface others' responses and require VIEW_REPORTS
    permission (server-enforced — a member receives 403).

    \b
    --source filters by origin: member, anonymous, automation, public.
    Multiple values are comma-separated (OR semantics).
    --submitter filters by specific user UUIDs (CSV, max 50, OR semantics).
    --flow-status filters approval status: pending, approved, denied.

    \b
    Examples:
      dailybot form responses <form_uuid>
      dailybot form responses <form_uuid> --state qa --json
      dailybot form responses <form_uuid> --all --from 2026-01-01 --to 2026-06-30
      dailybot form responses <form_uuid> --all --source automation
      dailybot form responses <form_uuid> --all --source "member,automation"
      dailybot form responses <form_uuid> --all --flow-status pending
      dailybot form responses <form_uuid> --all --search "deploy" --order oldest
      dailybot form responses <form_uuid> --user <user_uuid> --json
    """
    validate_user_filter(user)
    if submission_sources:
        parts: list[str] = [s.strip() for s in submission_sources.split(",")]
        invalid: list[str] = [s for s in parts if s not in RESPONSE_SOURCES]
        if invalid:
            print_error(
                f"Invalid source(s): {', '.join(invalid)}. Allowed: {', '.join(RESPONSE_SOURCES)}."
            )
            raise SystemExit(1)
    if submitter_ids:
        ids: list[str] = [s.strip() for s in submitter_ids.split(",")]
        if len(ids) > MAX_SUBMITTER_IDS:
            print_error(f"Too many submitter UUIDs ({len(ids)}, max {MAX_SUBMITTER_IDS}).")
            raise SystemExit(1)

    effective_order: str | None = order
    if is_ascend and not order:
        effective_order = "oldest"

    client = require_auth()
    truncated_search: str | None = search[:256] if search is not None else None
    meta: dict[str, Any] = {}
    try:
        with console.status("Fetching responses..."):
            responses: list[dict[str, Any]] = client.list_form_responses(
                form_uuid,
                state=state,
                all_responses=all_responses,
                user=user,
                submission_sources=submission_sources,
                submitter_user_ids=submitter_ids,
                flow_status=flow_status,
                order=effective_order,
                is_ascend=is_ascend,
                date_from=date_from,
                date_to=date_to,
                search=truncated_search,
                page=page,
                page_size=page_size,
                fetch_all=page is None and page_size is None and limit is None,
                limit=limit,
                meta=meta,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode, code_overrides=_RESPONSES_ERROR_OVERRIDES)

    if latest:
        responses = responses[:1] if responses else []

    if json_mode:
        emit_json(responses)
        return

    form_data: dict[str, Any] | None = _maybe_load_form(client, form_uuid)
    print_form_responses_table(form_uuid, responses, form_data)
    print_pagination_footer(
        len(responses),
        meta.get("count"),
        has_more=bool(meta.get("next")),
        more_hint="omit --page/--page-size to fetch every page",
    )


@form.group("response")
def form_response() -> None:
    """Operate on individual form responses (get / update / transition / delete)."""


@form_response.command("get")
@click.argument("form_uuid")
@click.argument("response_uuid")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_response_get(form_uuid: str, response_uuid: str, json_mode: bool) -> None:
    """Get a single response (state, allowed transitions, history, content).

    \b
    Examples:
      dailybot form response get <form_uuid> <response_uuid>
      dailybot form response get <form_uuid> <response_uuid> --json
    """
    client = require_auth()
    try:
        with console.status("Loading response..."):
            data: dict[str, Any] = client.get_form_response(form_uuid, response_uuid)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(data)
        return
    form_data: dict[str, Any] | None = _maybe_load_form(client, form_uuid)
    print_form_response_detail(data, form_data)


@form.command("update")
@click.argument("form_uuid")
@click.argument("response_uuid")
@click.option(
    "--content",
    "-c",
    required=True,
    help="JSON map of question UUID to new answer. Shallow-merged into the response.",
)
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_update(
    form_uuid: str,
    response_uuid: str,
    content: str,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    """Patch new answers into a response.

    \b
    The server authorizes by role: you may always edit your own response, and a
    form owner / org admin may edit anyone's (audited as metadata.last_edited_by).
    A non-privileged edit of someone else's response returns 403.

    \b
    Examples:
      dailybot form update <form_uuid> <response_uuid> \\
        --content '{"<question_uuid>": "PR #4242"}'
      dailybot form update <form_uuid> <response_uuid> -c '{...}' --yes --json
    """
    client = require_auth()
    content_map: dict[str, Any] = parse_form_content_json(content)

    summary_lines: list[str] = [
        f"Form UUID: {form_uuid}",
        f"Response UUID: {response_uuid}",
        "Updates:",
    ]
    for question_uuid, answer in content_map.items():
        summary_lines.append(f"  {question_uuid}: {answer}")
    confirm_write(summary_lines, assume_yes)

    try:
        with console.status("Updating response..."):
            result: dict[str, Any] = client.update_form_response(
                form_uuid=form_uuid,
                response_uuid=response_uuid,
                content=content_map,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return

    print_success(f"Response {response_uuid} updated.")
    form_data: dict[str, Any] | None = _maybe_load_form(client, form_uuid)
    print_form_response_state(result, form_data)


def _resolve_workflow_state(client: DailyBotClient, form_uuid: str, user_input: str) -> str:
    """Resolve a user-provided state label or key to the canonical state key.

    Fetches the form's workflow states and tries, in order:
    1. Exact key match (e.g. ``"done"`` matches key ``"done"``).
    2. Case-insensitive label match (e.g. ``"Done"`` matches label ``"Done"``
       → key ``"done"``).
    3. Case-insensitive key match (e.g. ``"Done"`` matches key ``"done"``).
    Falls back to the original input if no match, letting the API decide.
    """
    try:
        form_data: dict[str, Any] = client.get_form(form_uuid)
    except APIError:
        return user_input

    workflow: dict[str, Any] | None = form_data.get("workflow")
    if not workflow or not workflow.get("enabled"):
        return user_input

    states: list[dict[str, Any]] = workflow.get("states", [])
    if not states:
        return user_input

    for state in states:
        if state.get("key") == user_input:
            return user_input

    user_lower: str = user_input.lower()
    for state in states:
        label: str = state.get("label", "")
        if label.lower() == user_lower:
            return state["key"]

    for state in states:
        key: str = state.get("key", "")
        if key.lower() == user_lower:
            return key

    return user_input


@form.command("transition")
@click.argument("form_uuid")
@click.argument("response_uuid")
@click.argument("to_state")
@click.option("--note", default=None, help="Optional transition note for the audit trail.")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_transition(
    form_uuid: str,
    response_uuid: str,
    to_state: str,
    note: str | None,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    """Advance a response to a new workflow state.

    \b
    Accepts either the state key (e.g. 'done') or its human label (e.g. 'Done')
    — the CLI resolves labels to keys automatically (case-insensitive).

    \b
    The form's state_change_permission audience is the sole gate — there is no
    response-author short-circuit. If you're not in the audience the API will
    return 403 / form_response_change_state_forbidden.

    \b
    Examples:
      dailybot form transition <form_uuid> <response_uuid> qa --note "QA assigned"
      dailybot form transition <form_uuid> <response_uuid> Done
      dailybot form transition <form_uuid> <response_uuid> released --json
    """
    client = require_auth()

    resolved_state: str = _resolve_workflow_state(client, form_uuid, to_state)

    summary_lines: list[str] = [
        f"Form UUID: {form_uuid}",
        f"Response UUID: {response_uuid}",
        f"To state: {resolved_state}",
    ]
    if resolved_state != to_state:
        summary_lines.append(f"  (resolved from label '{to_state}')")
    if note:
        summary_lines.append(f"Note: {note}")
    confirm_write(summary_lines, assume_yes)

    try:
        with console.status("Transitioning response..."):
            result: dict[str, Any] = client.transition_form_response(
                form_uuid=form_uuid,
                response_uuid=response_uuid,
                to_state=resolved_state,
                note=note,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return

    print_success(f"Response {response_uuid} transitioned to '{resolved_state}'.")
    form_data: dict[str, Any] | None = _maybe_load_form(client, form_uuid)
    print_form_response_state(result, form_data)


@form.command("delete")
@click.argument("form_uuid")
@click.argument("response_uuid")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_delete(
    form_uuid: str,
    response_uuid: str,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    """Delete one of your responses (or any response, if you're owner / admin).

    \b
    Examples:
      dailybot form delete <form_uuid> <response_uuid>
      dailybot form delete <form_uuid> <response_uuid> --yes
    """
    client = require_auth()

    summary_lines: list[str] = [
        f"Form UUID: {form_uuid}",
        f"Response UUID: {response_uuid}",
        "This will permanently delete the response.",
    ]
    confirm_write(summary_lines, assume_yes)

    try:
        with console.status("Deleting response..."):
            client.delete_form_response(form_uuid=form_uuid, response_uuid=response_uuid)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json({"deleted": True, "form_uuid": form_uuid, "response_uuid": response_uuid})
        return

    print_form_response_deleted(form_uuid, response_uuid)


@form.command("create")
@click.option("--name", "-n", required=True, help="Form name.")
@click.option(
    "--questions-file",
    default=None,
    help="Path to a JSON array of question objects to seed the form.",
)
@click.option(
    "--interactive",
    is_flag=True,
    help="Build questions interactively (requires a terminal).",
)
@click.option(
    "--report-channel",
    "report_channels",
    multiple=True,
    help="Report-channel UUID (repeatable). See `dailybot channels list`.",
)
@click.option(
    "--ai-short-question",
    "ai_short_question",
    is_flag=True,
    help="Let Dailybot's AI generate each question's report title instead of "
    "requiring a 'short_question' on every question.",
)
@_form_config_flag_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_create(
    name: str,
    questions_file: str | None,
    interactive: bool,
    report_channels: tuple[str, ...],
    ai_short_question: bool,
    json_mode: bool,
    **config_flags: Any,
) -> None:
    """Create a form (seeded with questions and full config).

    \b
    Creating forms is role-gated server-side (admins/managers as applicable). A form
    must have at least one question at create time — seed them with --questions-file
    or --interactive (add/edit/remove more later via `dailybot form questions`). Each
    seeded question needs a report title (--short-question / "short_question") unless
    you pass --ai-short-question. The config flags (workflow states, permissions,
    anonymous/public/approval, command) mirror the web Setup tab.

    \b
    Examples:
      dailybot form create --name "Sprint Retro"
      dailybot form create -n "Retro" --questions-file questions.json
      dailybot form create -n "Release" --state "Draft:#ccc" --state "Done:#2ecc71" \\
        --command release --can-edit owner_and_admins --report-channel <channel_uuid>
    """
    client = require_auth()
    check_report_channels(report_channels)
    if interactive:
        questions: list[dict[str, Any]] | None = build_questions_interactively(ai_short_question)
    elif questions_file:
        questions = parse_questions_file(questions_file)
    else:
        questions = None
    require_questions(questions, "form")
    require_short_questions(questions or [], ai_short_question)
    config: dict[str, Any] = resolve_form_config(client, **config_flags)
    try:
        with console.status("Creating form..."):
            result: dict[str, Any] = client.create_form(
                name,
                questions,
                report_channels=list(report_channels) if report_channels else None,
                generate_short_question=ai_short_question,
                config=config or None,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return
    print_form_created(result)


@form.command("edit")
@click.argument("form_uuid")
@click.option("--name", "-n", default=None, help="New form name.")
@click.option(
    "--report-channel",
    "report_channels",
    multiple=True,
    help="Report-channel UUID (repeatable); replaces the form's channels.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_edit(
    form_uuid: str,
    name: str | None,
    report_channels: tuple[str, ...],
    json_mode: bool,
) -> None:
    """Edit a form's name and/or report channels.

    \b
    Examples:
      dailybot form edit <form_uuid> --name "Updated Retro"
      dailybot form edit <form_uuid> --report-channel <channel_uuid> --json
    """
    if name is None and not report_channels:
        raise click.UsageError("Nothing to edit. Pass --name and/or --report-channel.")
    client = require_auth()
    check_report_channels(report_channels)
    try:
        with console.status("Updating form..."):
            result: dict[str, Any] = client.update_form_config(
                form_uuid,
                name=name,
                report_channels=list(report_channels) if report_channels else None,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return
    print_success(f"Form {form_uuid} updated.")
    print_form_created(result, updated=True)


@form.command("config")
@click.argument("form_uuid")
@click.option("--name", "-n", default=None, help="New form name.")
@click.option(
    "--report-channel",
    "report_channels",
    multiple=True,
    help="Report-channel UUID (repeatable); replaces the form's channels.",
)
@_form_config_flag_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_config(
    form_uuid: str,
    name: str | None,
    report_channels: tuple[str, ...],
    json_mode: bool,
    **config_flags: Any,
) -> None:
    """Edit a form's full configuration (partial update).

    \b
    Superset of `form edit`: name + channels plus workflow states, permissions,
    anonymous/public/approval settings, and the ChatOps command — mirroring the web
    Setup tab. Only the flags you pass change; role-gated server-side.

    \b
    Examples:
      dailybot form config <form_uuid> --inactive --command release
      dailybot form config <form_uuid> --state "Draft:#ccc" --state "Done:#2ecc71"
      dailybot form config <form_uuid> --anonymous --public --require-identity
      dailybot form config <form_uuid> --can-see restricted --can-see-team "Eng"
      dailybot form config <form_uuid> --approval --approver-user "Jane Doe"
    """
    client = require_auth()
    check_report_channels(report_channels)
    config: dict[str, Any] = resolve_form_config(client, **config_flags)
    if name is None and not report_channels and not config:
        raise click.UsageError(
            "Nothing to edit. Pass --name, --report-channel, or a config flag (see --help)."
        )
    try:
        with console.status("Updating form..."):
            result: dict[str, Any] = client.update_form_config(
                form_uuid,
                name=name,
                report_channels=list(report_channels) if report_channels else None,
                config=config or None,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return
    print_success(f"Form {form_uuid} updated.")
    print_form_created(result, updated=True)


@form.command("archive")
@click.argument("form_uuid")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_archive(form_uuid: str, assume_yes: bool, json_mode: bool) -> None:
    """Archive (soft-delete) a form.

    \b
    Data is preserved server-side. This is distinct from `form delete`, which
    removes an individual response.

    \b
    Examples:
      dailybot form archive <form_uuid>
      dailybot form archive <form_uuid> --yes
    """
    client = require_auth()
    confirm_write(
        [f"Form UUID: {form_uuid}", "This will archive (soft-delete) the form."],
        assume_yes,
    )
    try:
        with console.status("Archiving form..."):
            client.archive_form(form_uuid)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json({"archived": True, "form_uuid": form_uuid})
        return
    print_archived("form", form_uuid)


@form.group("questions")
def form_questions() -> None:
    """Manage a form's questions (list / add / edit / delete / reorder)."""


@form_questions.command("list")
@click.argument("form_uuid")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_questions_list(form_uuid: str, json_mode: bool) -> None:
    """List a form's questions.

    \b
    Examples:
      dailybot form questions list <form_uuid>
    """
    client = require_auth()
    try:
        with console.status("Loading form..."):
            data: dict[str, Any] = client.get_form(form_uuid)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    questions: list[dict[str, Any]] = data.get("questions") or []
    if json_mode:
        emit_json(questions)
        return
    print_questions_table(questions)


@form_questions.command("add")
@click.argument("form_uuid")
@click.option(
    "--type", "question_type", required=True, help="text/multiple_choice/boolean/numeric."
)
@click.option("--question", required=True, help="The question text.")
@click.option("--options", default=None, help="Comma-separated options (multiple_choice only).")
@click.option("--required/--optional", "required", default=True, help="Mark the question required.")
@click.option(
    "--blocker/--no-blocker",
    "is_blocker",
    default=False,
    help="Tag this as the blocker question.",
)
@question_extras_options
@click.option(
    "--ai-short-question",
    "ai_short_question",
    is_flag=True,
    help="Skip --short-question and let Dailybot's AI generate the report title.",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_questions_add(
    form_uuid: str,
    question_type: str,
    question: str,
    options: str | None,
    required: bool,
    is_blocker: bool,
    ai_short_question: bool,
    json_mode: bool,
    **extra_flags: Any,
) -> None:
    """Add a question to a form.

    \b
    A report title (--short-question) is required unless you pass
    --ai-short-question. Other extras: --variation (repeatable), and logic via
    --logic-file or inline --jump-if-equals/--jump-to.

    \b
    Examples:
      dailybot form questions add <form_uuid> --type text \\
        --question "What went well?" --short-question "Wins"
      dailybot form questions add <form_uuid> --type multiple_choice \\
        --question "Rating?" --options "Excellent,Good,Average,Poor" --ai-short-question
      dailybot form questions add <form_uuid> --type boolean --question "Ship it?" \\
        --short-question "Ship" --jump-if-equals "No" --jump-to 4
    """
    client = require_auth()
    require_short_question(extra_flags.get("short_question"), ai_short_question)
    extras: dict[str, Any] = resolve_question_extras(**extra_flags)
    payload: dict[str, Any] = build_question(
        question_type,
        question,
        options=parse_options(options),
        required=required,
        is_blocker=is_blocker,
        **extras,
    )
    if ai_short_question:
        payload["generate_short_question"] = True
    try:
        with console.status("Adding question..."):
            result: dict[str, Any] = client.add_form_question(form_uuid, payload)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return
    print_success("Question added.")
    print_question(result)


@form_questions.command("edit")
@click.argument("form_uuid")
@click.argument("question_uuid")
@click.option("--question", default=None, help="New question text.")
@click.option("--type", "question_type", default=None, help="New question type.")
@click.option("--options", default=None, help="New comma-separated options (multiple_choice).")
@click.option("--required/--optional", "required", default=None, help="Toggle required.")
@click.option(
    "--blocker/--no-blocker",
    "is_blocker",
    default=None,
    help="Toggle the blocker tag.",
)
@question_extras_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_questions_edit(
    form_uuid: str,
    question_uuid: str,
    question: str | None,
    question_type: str | None,
    options: str | None,
    required: bool | None,
    is_blocker: bool | None,
    json_mode: bool,
    **extra_flags: Any,
) -> None:
    """Update a question's text, type, options, required, blocker, or extras.

    \b
    Extras: --short-question (report title), --variation (repeatable), and logic
    via --logic-file or inline --jump-if-equals/--jump-to.

    \b
    Examples:
      dailybot form questions edit <form_uuid> <question_uuid> --question "Reworded?"
      dailybot form questions edit <form_uuid> <question_uuid> --optional
      dailybot form questions edit <form_uuid> <question_uuid> \\
        --short-question "Rating" --variation "How would you rate it?"
    """
    extras: dict[str, Any] = resolve_question_extras(**extra_flags)
    fields: dict[str, Any] = build_question_edit_fields(
        question, question_type, options, required, is_blocker, **extras
    )
    if not fields:
        raise click.UsageError(
            "Nothing to edit. Pass --question, --type, --options, --required, --blocker, "
            "--short-question, --variation, or logic (--logic-file / --jump-if-equals + --jump-to)."
        )
    client = require_auth()
    try:
        with console.status("Updating question..."):
            result: dict[str, Any] = client.update_form_question(form_uuid, question_uuid, fields)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return
    print_success("Question updated.")
    print_question(result)


@form_questions.command("delete")
@click.argument("form_uuid")
@click.argument("question_uuid")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_questions_delete(
    form_uuid: str,
    question_uuid: str,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    """Remove a question from a form.

    \b
    Examples:
      dailybot form questions delete <form_uuid> <question_uuid>
      dailybot form questions delete <form_uuid> <question_uuid> --yes
    """
    client = require_auth()
    confirm_write(
        [
            f"Form UUID: {form_uuid}",
            f"Question UUID: {question_uuid}",
            "This will permanently remove the question.",
        ],
        assume_yes,
    )
    try:
        with console.status("Deleting question..."):
            client.delete_form_question(form_uuid, question_uuid)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json({"deleted": True, "form_uuid": form_uuid, "question_uuid": question_uuid})
        return
    print_success(f"Question {question_uuid} deleted.")


@form_questions.command("reorder")
@click.argument("form_uuid")
@click.argument("question_uuids", nargs=-1, required=True)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_questions_reorder(
    form_uuid: str,
    question_uuids: tuple[str, ...],
    json_mode: bool,
) -> None:
    """Set a new question order (pass question UUIDs in the desired order).

    \b
    Examples:
      dailybot form questions reorder <form_uuid> <q3> <q1> <q2>
    """
    client = require_auth()
    order: list[str] = list(question_uuids)
    try:
        with console.status("Reordering questions..."):
            client.reorder_form_questions(form_uuid, order)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json({"reordered": True, "form_uuid": form_uuid, "order": order})
        return
    print_reordered("form", order)
