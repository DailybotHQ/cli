"""Check-in commands for the user-scoped public API."""

import sys
from collections.abc import Callable
from typing import Any

import click

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.authoring_helpers import (
    AuthoringError,
    build_checkin_config,
    build_question,
    build_question_edit_fields,
    build_questions_interactively,
    check_report_channels,
    parse_options,
    parse_participants,
    parse_questions_file,
    parse_schedule,
    prompt_participants_interactively,
    question_extras_options,
    require_questions,
    require_short_question,
    require_short_questions,
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
from dailybot_cli.commands.query_options import paging_options
from dailybot_cli.commands.user_scoped_actions import (
    execute_checkin_complete,
    execute_checkin_edit,
    execute_checkin_history,
    execute_checkin_list,
    execute_checkin_reset,
    execute_checkin_show,
    execute_checkin_status,
)
from dailybot_cli.display import (
    console,
    print_archived,
    print_checkin_created,
    print_question,
    print_reordered,
    print_success,
)

_HELP: str = "Acts as you. You can only see and act on what you could in the webapp."


def _config_flag_options(func: Callable[..., Any]) -> Callable[..., Any]:
    """Attach the shared check-in configuration flags to create + config.

    Dest names match ``authoring_helpers.build_checkin_config`` kwargs so the
    callback can forward them as ``**config_flags``. Toggle flags default to
    ``None`` (unset → not sent), keeping ``config`` a partial update.
    """
    options: list[Callable[..., Any]] = [
        click.option("--start-on", "start_on", default=None, help="Start date (YYYY-MM-DD)."),
        click.option("--end-on", "end_on", default=None, help="End date (YYYY-MM-DD)."),
        click.option(
            "--frequency",
            "frequency_type",
            default=None,
            help="Recurrence base (weekly). For monthly/custom use --frequency-advanced.",
        ),
        click.option("--every", "frequency", type=int, default=None, help="Repeat every N (>=1)."),
        click.option(
            "--trigger-based/--fixed-time",
            "is_trigger_based",
            default=None,
            help="Trigger-based vs a fixed time.",
        ),
        click.option(
            "--participant-timezone/--custom-timezone",
            "use_participant_timezone",
            default=None,
            help="Use each participant's timezone vs the custom one.",
        ),
        click.option(
            "--reminders",
            "reminders_max_count",
            type=int,
            default=None,
            help="Extra reminders to send to non-responders (0-5; 0 = off).",
        ),
        click.option(
            "--reminder-interval",
            "reminders_frequency_time",
            type=int,
            default=None,
            help="Minutes between reminders (0-60).",
        ),
        click.option(
            "--reminder-condition",
            "reminders_trigger_condition",
            default=None,
            help="smart_frequency / fixed_frequency.",
        ),
        click.option(
            "--work-days/--no-work-days",
            "use_user_defined_work_days",
            default=None,
            help="Respect each user's work days.",
        ),
        click.option(
            "--allow-early/--no-early",
            "allow_responses_before_trigger",
            default=None,
            help="Allow responses before the trigger time.",
        ),
        click.option(
            "--allow-past/--no-past",
            "allow_past_responses",
            default=None,
            help="Allow reports on past dates.",
        ),
        click.option(
            "--allow-future/--no-future",
            "allow_future_responses",
            default=None,
            help="Allow reports on future dates.",
        ),
        click.option(
            "--anonymous/--no-anonymous",
            "is_anonymous",
            default=None,
            help="Anonymous responses.",
        ),
        click.option("--privacy", "privacy", default=None, help="Response visibility level."),
        click.option(
            "--one-by-one/--aggregated",
            "send_reports_one_by_one",
            default=None,
            help="Post reports one-by-one vs aggregated.",
        ),
        click.option(
            "--intro", "custom_template_intro", default=None, help="Custom intro (3-1024 chars)."
        ),
        click.option(
            "--outro", "custom_template_outro", default=None, help="Custom outro (3-1024 chars)."
        ),
        click.option(
            "--report-time", "time_for_report", default=None, help="Report delivery time (HH:MM)."
        ),
        click.option(
            "--reminder-tone",
            "reminder_tone",
            default=None,
            help="Reminder voice: standard / persuasive.",
        ),
        click.option(
            "--smart/--no-smart",
            "is_smart_checkin",
            default=None,
            help="Enable smart (AI-driven adaptive) check-in mode.",
        ),
        click.option(
            "--intelligence/--no-intelligence",
            "is_intelligence_enabled",
            default=None,
            help="Enable AI insights on responses (requires --smart).",
        ),
        click.option(
            "--max-clarifying",
            "max_clarifying_questions",
            type=int,
            default=None,
            help="Max AI clarifying questions per response (0-5; requires --intelligence).",
        ),
        click.option(
            "--frequency-advanced",
            "frequency_advanced",
            default=None,
            help="Advanced recurrence: disabled / monthly / custom.",
        ),
        click.option(
            "--cron",
            "frequency_cron",
            default=None,
            help="5-field cron for custom cadence (e.g. '0 9 * * 1,3,5').",
        ),
    ]
    for option in reversed(options):
        func = option(func)
    return func


@click.group()
def checkin() -> None:
    """Manage check-ins with your Dailybot session.

    \b
    Acts as you — visibility and permissions match the webapp for your account.
    """


@checkin.command("list")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_list(json_mode: bool) -> None:
    """List pending check-ins for today.

    \b
    Acts as you. You can only see and act on what you could in the webapp.

    \b
    Examples:
      dailybot checkin list
      dailybot checkin list --json
    """
    enforce_plan_access("checkin_list", json_mode=json_mode)
    client = require_auth()
    execute_checkin_list(client, json_mode=json_mode)


@checkin.command("complete")
@click.argument("followup_uuid")
@click.option(
    "--answer",
    "-a",
    multiple=True,
    help='Answer as "index=response" (0-based). Prompts when omitted.',
)
@click.option(
    "--response-date",
    default=None,
    help="Target a specific day (YYYY-MM-DD). Defaults to today.",
)
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_complete(
    followup_uuid: str,
    answer: tuple[str, ...],
    response_date: str | None,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    """Complete a pending check-in.

    \b
    Acts as you. You can only see and act on what you could in the webapp.

    \b
    Examples:
      dailybot checkin complete <followup_uuid>
      dailybot checkin complete <followup_uuid> -a 0="Shipped auth" -a 1="Reviewing migrations"
      dailybot checkin complete <followup_uuid> --yes
    """
    client = require_auth()
    execute_checkin_complete(
        client,
        followup_uuid,
        answer_flags=answer,
        response_date=response_date,
        assume_yes=assume_yes,
        json_mode=json_mode,
    )


@checkin.command("status")
@click.option(
    "--date", "date", default=None, help="Target a specific day (YYYY-MM-DD). Defaults to today."
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_status(date: str | None, json_mode: bool) -> None:
    """Show pending/completed status for your check-ins on a date.

    \b
    Examples:
      dailybot checkin status
      dailybot checkin status --date 2026-07-01 --json
    """
    client = require_auth()
    execute_checkin_status(client, date=date, json_mode=json_mode)


@checkin.command("show")
@click.argument("followup_uuid")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_show(followup_uuid: str, json_mode: bool) -> None:
    """Show a check-in's configuration and questions.

    \b
    Examples:
      dailybot checkin show <followup_uuid>
      dailybot checkin show <followup_uuid> --json
    """
    client = require_auth()
    execute_checkin_show(client, followup_uuid, json_mode=json_mode)


@checkin.command("history")
@click.argument("followup_uuid")
@click.option("--days", type=int, default=None, help="Look back N days from today.")
@click.option("--from", "date_from", default=None, help="Range start (YYYY-MM-DD).")
@click.option("--to", "date_to", default=None, help="Range end (YYYY-MM-DD).")
@click.option(
    "--user",
    default=None,
    help="Filter to one participant's responses (admin/manager only; a member sees only their own).",
)
@click.option(
    "--search", "-s", "search", default=None, help="Filter response content (max 256 chars)."
)
@paging_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_history(
    followup_uuid: str,
    days: int | None,
    date_from: str | None,
    date_to: str | None,
    user: str | None,
    search: str | None,
    page: int | None,
    page_size: int | None,
    limit: int | None,
    json_mode: bool,
) -> None:
    """Show a check-in's response history.

    \b
    By default this lists every participant's responses in the range (check-ins
    are team-wide). Pass --user to narrow to one participant — admin/manager only;
    a member always sees only their own responses.

    \b
    Examples:
      dailybot checkin history <followup_uuid> --days 7
      dailybot checkin history <followup_uuid> --from 2026-06-01 --to 2026-06-30 --json
      dailybot checkin history <followup_uuid> --user <user_uuid> --days 30
    """
    validate_user_filter(user)
    client = require_auth()
    execute_checkin_history(
        client,
        followup_uuid,
        days=days,
        date_from=date_from,
        date_to=date_to,
        user=user,
        search=search,
        page=page,
        page_size=page_size,
        limit=limit,
        json_mode=json_mode,
    )


@checkin.command("reset")
@click.argument("followup_uuid")
@click.option("--date", "response_date", default=None, help="Target a specific day (YYYY-MM-DD).")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_reset(
    followup_uuid: str,
    response_date: str | None,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    """Delete (reset) your check-in response for a day.

    \b
    Examples:
      dailybot checkin reset <followup_uuid>
      dailybot checkin reset <followup_uuid> --date 2026-07-01 --yes
    """
    client = require_auth()
    execute_checkin_reset(
        client,
        followup_uuid,
        response_date=response_date,
        assume_yes=assume_yes,
        json_mode=json_mode,
    )


@checkin.command("edit")
@click.argument("followup_uuid")
@click.option(
    "--answer", "-a", multiple=True, help='Override an answer as "index=response" (0-based).'
)
@click.option("--date", "response_date", default=None, help="Target a specific day (YYYY-MM-DD).")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_edit(
    followup_uuid: str,
    answer: tuple[str, ...],
    response_date: str | None,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    """Edit an existing check-in response.

    \b
    With -a flags (or when a terminal is attached, prompts per question showing
    the current answer as the default).

    \b
    Examples:
      dailybot checkin edit <followup_uuid> -a 0="Updated answer" --yes
      dailybot checkin edit <followup_uuid>   # prompts each question
    """
    client = require_auth()
    execute_checkin_edit(
        client,
        followup_uuid,
        answer_flags=answer,
        response_date=response_date,
        assume_yes=assume_yes,
        json_mode=json_mode,
        interactive=(not answer and not json_mode and sys.stdin.isatty()),
    )


@checkin.command("create")
@click.option("--name", "-n", required=True, help="Check-in name.")
@click.option("--time", "time_", default=None, help="Trigger time (HH:MM).")
@click.option("--days", default=None, help="Comma-separated weekdays 0-6 (0=Sunday .. 6=Saturday).")
@click.option("--timezone", default=None, help="IANA timezone (e.g. America/New_York).")
@click.option("--schedule-file", default=None, help="Path to a JSON schedule object.")
@click.option(
    "--user", "users", multiple=True, help="Participant user (name, email, or UUID; repeatable)."
)
@click.option("--team", "teams", multiple=True, help="Participant team (name or UUID; repeatable).")
@click.option("--questions-file", default=None, help="Path to a JSON array of question objects.")
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
@_config_flag_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_create(
    name: str,
    time_: str | None,
    days: str | None,
    timezone: str | None,
    schedule_file: str | None,
    users: tuple[str, ...],
    teams: tuple[str, ...],
    questions_file: str | None,
    interactive: bool,
    report_channels: tuple[str, ...],
    ai_short_question: bool,
    json_mode: bool,
    **config_flags: Any,
) -> None:
    """Create a check-in with a schedule, participants, questions, and config.

    \b
    Creating check-ins is role-gated server-side. A check-in must
    have at least one question at create time — seed them with --questions-file or
    --interactive (add/edit/remove more later with `dailybot checkin questions`). The
    scheduling/behavior flags (frequency, reminders, timezone mode, submission rules,
    privacy) mirror the web UI.

    \b
    Examples:
      dailybot checkin create -n "Daily Standup" --time 09:00 --days 1,2,3,4,5 \\
        --timezone America/New_York --questions-file questions.json --team "Eng"
      dailybot checkin create -n "Standup" --team "Eng" --frequency weekly \\
        --reminders 3 --reminder-interval 30 --no-past --json

    \b
    A check-in must have at least one participant (a team or a person) — it only
    triggers for its participants. If you pass neither --user nor --team, an
    interactive terminal prompts you to pick some (the default team is suggested);
    a non-interactive run errors instead of creating an empty check-in.
    """
    client = require_auth()
    check_report_channels(report_channels)
    schedule: dict[str, Any] | None = parse_schedule(
        days=days, time=time_, timezone=timezone, schedule_file=schedule_file
    )
    config: dict[str, Any] = build_checkin_config(**config_flags)
    participants: dict[str, Any] = parse_participants(users, teams, client)
    if not participants and not json_mode:
        participants = prompt_participants_interactively(client)
    if not participants:
        raise AuthoringError(
            "A check-in must have at least one participant (a team or a person). "
            "Add --user and/or --team."
        )
    if interactive:
        questions: list[dict[str, Any]] | None = build_questions_interactively(ai_short_question)
    elif questions_file:
        questions = parse_questions_file(questions_file)
    else:
        questions = None
    require_questions(questions, "check-in")
    require_short_questions(questions or [], ai_short_question)
    try:
        with console.status("Creating check-in..."):
            result: dict[str, Any] = client.create_checkin(
                name,
                schedule=schedule,
                participants=participants or None,
                questions=questions,
                report_channels=list(report_channels) if report_channels else None,
                config=config or None,
                generate_short_question=ai_short_question,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return
    print_checkin_created(result)


@checkin.command("config")
@click.argument("followup_uuid")
@click.option("--name", "-n", default=None, help="New check-in name.")
@click.option("--time", "time_", default=None, help="New trigger time (HH:MM).")
@click.option("--days", default=None, help="New weekdays 0-6 (comma-separated).")
@click.option("--timezone", default=None, help="New IANA timezone.")
@click.option(
    "--report-channel",
    "report_channels",
    multiple=True,
    help="Report-channel UUID (repeatable); replaces the check-in's channels.",
)
@click.option(
    "--user", "users", multiple=True, help="Participant user (name, email, or UUID; repeatable)."
)
@click.option("--team", "teams", multiple=True, help="Participant team (name or UUID; repeatable).")
@click.option("--active/--inactive", "is_active", default=None, help="Activate or deactivate.")
@_config_flag_options
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_config(
    followup_uuid: str,
    name: str | None,
    time_: str | None,
    days: str | None,
    timezone: str | None,
    report_channels: tuple[str, ...],
    users: tuple[str, ...],
    teams: tuple[str, ...],
    is_active: bool | None,
    json_mode: bool,
    **config_flags: Any,
) -> None:
    """Edit a check-in's configuration (partial update).

    \b
    Distinct from `checkin edit`, which edits your own response. This edits the
    check-in definition (role-gated server-side). --user/--team replace the
    check-in's participants (a check-in always needs at least one). The
    scheduling/behavior flags (frequency, reminders, timezone mode, submission
    rules, privacy) mirror the web UI; only the flags you pass change.

    \b
    Examples:
      dailybot checkin config <followup_uuid> --time 10:00 --days 1,2,3,4,5
      dailybot checkin config <followup_uuid> --team "Engineering"
      dailybot checkin config <followup_uuid> --reminders 3 --reminder-interval 30
      dailybot checkin config <followup_uuid> --no-past --privacy everyone --inactive
    """
    check_report_channels(report_channels)
    schedule: dict[str, Any] | None = parse_schedule(days=days, time=time_, timezone=timezone)
    config: dict[str, Any] = build_checkin_config(**config_flags)
    if (
        name is None
        and schedule is None
        and not report_channels
        and not users
        and not teams
        and is_active is None
        and not config
    ):
        raise click.UsageError(
            "Nothing to edit. Pass --name, --time/--days/--timezone, --report-channel, "
            "--user/--team, --active/--inactive, or a config flag (see --help)."
        )
    client = require_auth()
    participants: dict[str, Any] = parse_participants(users, teams, client)
    try:
        with console.status("Updating check-in..."):
            result: dict[str, Any] = client.update_checkin_config(
                followup_uuid,
                name=name,
                schedule=schedule,
                report_channels=list(report_channels) if report_channels else None,
                is_active=is_active,
                participants=participants or None,
                config=config or None,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return
    print_success(f"Check-in {followup_uuid} updated.")
    print_checkin_created(result, updated=True)


@checkin.command("archive")
@click.argument("followup_uuid")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_archive(followup_uuid: str, assume_yes: bool, json_mode: bool) -> None:
    """Archive (soft-delete) a check-in.

    \b
    Data is preserved server-side. Distinct from `checkin reset`, which deletes
    your response for a day.

    \b
    Examples:
      dailybot checkin archive <followup_uuid>
      dailybot checkin archive <followup_uuid> --yes
    """
    client = require_auth()
    confirm_write(
        [
            f"Check-in UUID: {followup_uuid}",
            "This will archive (soft-delete) the check-in.",
        ],
        assume_yes,
    )
    try:
        with console.status("Archiving check-in..."):
            client.archive_checkin(followup_uuid)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json({"archived": True, "followup_uuid": followup_uuid})
        return
    print_archived("check-in", followup_uuid)


@checkin.group("questions")
def checkin_questions() -> None:
    """Manage a check-in's questions (add / edit / delete / reorder)."""


@checkin_questions.command("add")
@click.argument("followup_uuid")
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
def checkin_questions_add(
    followup_uuid: str,
    question_type: str,
    question: str,
    options: str | None,
    required: bool,
    is_blocker: bool,
    ai_short_question: bool,
    json_mode: bool,
    **extra_flags: Any,
) -> None:
    """Add a question to a check-in.

    \b
    A report title (--short-question) is required unless you pass
    --ai-short-question to let Dailybot generate it.

    \b
    Examples:
      dailybot checkin questions add <followup_uuid> --type text \\
        --question "What are you working on today?" --short-question "Focus"
      dailybot checkin questions add <followup_uuid> --type boolean \\
        --question "Any blockers?" --blocker --ai-short-question
      dailybot checkin questions add <followup_uuid> --type text \\
        --question "What did you do?" --short-question "Yesterday" \\
        --variation "What did you accomplish?" --jump-if-equals "None" --jump-to -1
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
            result: dict[str, Any] = client.add_checkin_question(followup_uuid, payload)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return
    print_success("Question added.")
    print_question(result)


@checkin_questions.command("edit")
@click.argument("followup_uuid")
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
def checkin_questions_edit(
    followup_uuid: str,
    question_uuid: str,
    question: str | None,
    question_type: str | None,
    options: str | None,
    required: bool | None,
    is_blocker: bool | None,
    json_mode: bool,
    **extra_flags: Any,
) -> None:
    """Update a check-in question's text, type, options, required, blocker, or extras.

    \b
    Extras: --short-question (report title), --variation (repeatable), and logic
    via --logic-file or inline --jump-if-equals/--jump-to.

    \b
    Examples:
      dailybot checkin questions edit <followup_uuid> <question_uuid> \\
        --question "Do you need help today?"
      dailybot checkin questions edit <followup_uuid> <question_uuid> --blocker
      dailybot checkin questions edit <followup_uuid> <question_uuid> \\
        --short-question "Help?" --logic-file branching.json
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
            result: dict[str, Any] = client.update_checkin_question(
                followup_uuid, question_uuid, fields
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return
    print_success("Question updated.")
    print_question(result)


@checkin_questions.command("delete")
@click.argument("followup_uuid")
@click.argument("question_uuid")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_questions_delete(
    followup_uuid: str,
    question_uuid: str,
    assume_yes: bool,
    json_mode: bool,
) -> None:
    """Remove a question from a check-in.

    \b
    Examples:
      dailybot checkin questions delete <followup_uuid> <question_uuid>
    """
    client = require_auth()
    confirm_write(
        [
            f"Check-in UUID: {followup_uuid}",
            f"Question UUID: {question_uuid}",
            "This will permanently remove the question.",
        ],
        assume_yes,
    )
    try:
        with console.status("Deleting question..."):
            client.delete_checkin_question(followup_uuid, question_uuid)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json({"deleted": True, "followup_uuid": followup_uuid, "question_uuid": question_uuid})
        return
    print_success(f"Question {question_uuid} deleted.")


@checkin_questions.command("reorder")
@click.argument("followup_uuid")
@click.argument("question_uuids", nargs=-1, required=True)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_questions_reorder(
    followup_uuid: str,
    question_uuids: tuple[str, ...],
    json_mode: bool,
) -> None:
    """Set a new question order (pass question UUIDs in the desired order).

    \b
    Examples:
      dailybot checkin questions reorder <followup_uuid> <q3> <q1> <q2>
    """
    client = require_auth()
    order: list[str] = list(question_uuids)
    try:
        with console.status("Reordering questions..."):
            client.reorder_checkin_questions(followup_uuid, order)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json({"reordered": True, "followup_uuid": followup_uuid, "order": order})
        return
    print_reordered("check-in", order)
