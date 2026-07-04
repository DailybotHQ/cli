"""Check-in commands for the user-scoped public API."""

import sys
from typing import Any

import click

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.authoring_helpers import (
    build_question,
    build_question_edit_fields,
    parse_options,
    parse_participants,
    parse_questions_file,
    parse_schedule,
)
from dailybot_cli.commands.public_api_helpers import (
    confirm_write,
    emit_json,
    exit_for_api_error,
    require_auth,
)
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
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_history(
    followup_uuid: str,
    days: int | None,
    date_from: str | None,
    date_to: str | None,
    json_mode: bool,
) -> None:
    """Show your response history for a check-in.

    \b
    Examples:
      dailybot checkin history <followup_uuid> --days 7
      dailybot checkin history <followup_uuid> --from 2026-06-01 --to 2026-06-30 --json
    """
    client = require_auth()
    execute_checkin_history(
        client,
        followup_uuid,
        days=days,
        date_from=date_from,
        date_to=date_to,
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
@click.option("--user", "users", multiple=True, help="Participant user (name or UUID; repeatable).")
@click.option("--team", "teams", multiple=True, help="Participant team (name or UUID; repeatable).")
@click.option("--questions-file", default=None, help="Path to a JSON array of question objects.")
@click.option(
    "--report-channel",
    "report_channels",
    multiple=True,
    help="Report-channel UUID (repeatable). See `dailybot channels list`.",
)
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
    report_channels: tuple[str, ...],
    json_mode: bool,
) -> None:
    """Create a check-in with a schedule, participants, and questions.

    \b
    Creating check-ins is role-gated server-side (admins/managers). Add questions
    via --questions-file, or later with `dailybot checkin questions add`.

    \b
    Examples:
      dailybot checkin create -n "Daily Standup" --time 09:00 --days 1,2,3,4,5 \\
        --timezone America/New_York --questions-file questions.json
      dailybot checkin create -n "Standup" --user "Jane Doe" --team "Eng" --json
    """
    client = require_auth()
    schedule: dict[str, Any] | None = parse_schedule(
        days=days, time=time_, timezone=timezone, schedule_file=schedule_file
    )
    participants: dict[str, Any] = parse_participants(users, teams, client)
    questions: list[dict[str, Any]] | None = (
        parse_questions_file(questions_file) if questions_file else None
    )
    try:
        with console.status("Creating check-in..."):
            result: dict[str, Any] = client.create_checkin(
                name,
                schedule=schedule,
                participants=participants or None,
                questions=questions,
                report_channels=list(report_channels) if report_channels else None,
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
@click.option("--active/--inactive", "is_active", default=None, help="Activate or deactivate.")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_config(
    followup_uuid: str,
    name: str | None,
    time_: str | None,
    days: str | None,
    timezone: str | None,
    report_channels: tuple[str, ...],
    is_active: bool | None,
    json_mode: bool,
) -> None:
    """Edit a check-in's configuration (name, schedule, channels, active state).

    \b
    Distinct from `checkin edit`, which edits your own response. This edits the
    check-in definition (role-gated server-side).

    \b
    Examples:
      dailybot checkin config <followup_uuid> --time 10:00 --days 1,2,3,4,5
      dailybot checkin config <followup_uuid> --inactive
    """
    schedule: dict[str, Any] | None = parse_schedule(days=days, time=time_, timezone=timezone)
    if name is None and schedule is None and not report_channels and is_active is None:
        raise click.UsageError(
            "Nothing to edit. Pass --name, --time/--days/--timezone, "
            "--report-channel, or --active/--inactive."
        )
    client = require_auth()
    try:
        with console.status("Updating check-in..."):
            result: dict[str, Any] = client.update_checkin_config(
                followup_uuid,
                name=name,
                schedule=schedule,
                report_channels=list(report_channels) if report_channels else None,
                is_active=is_active,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return
    print_success(f"Check-in {followup_uuid} updated.")
    print_checkin_created(result)


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
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_questions_add(
    followup_uuid: str,
    question_type: str,
    question: str,
    options: str | None,
    required: bool,
    json_mode: bool,
) -> None:
    """Add a question to a check-in.

    \b
    Examples:
      dailybot checkin questions add <followup_uuid> --type text \\
        --question "What are you working on today?"
    """
    client = require_auth()
    payload: dict[str, Any] = build_question(
        question_type, question, options=parse_options(options), required=required
    )
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
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def checkin_questions_edit(
    followup_uuid: str,
    question_uuid: str,
    question: str | None,
    question_type: str | None,
    options: str | None,
    required: bool | None,
    json_mode: bool,
) -> None:
    """Update a check-in question's text, type, options, or required flag.

    \b
    Examples:
      dailybot checkin questions edit <followup_uuid> <question_uuid> \\
        --question "Do you need help today?"
    """
    fields: dict[str, Any] = build_question_edit_fields(question, question_type, options, required)
    if not fields:
        raise click.UsageError(
            "Nothing to edit. Pass --question, --type, --options, or --required."
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
