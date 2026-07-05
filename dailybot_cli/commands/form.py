"""Form commands for the user-scoped public API."""

from typing import Any

import click

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.authoring_helpers import (
    build_question,
    build_question_edit_fields,
    build_questions_interactively,
    parse_options,
    parse_questions_file,
    question_extras_options,
    resolve_question_extras,
)
from dailybot_cli.commands.public_api_helpers import (
    confirm_write,
    emit_json,
    exit_for_api_error,
    require_auth,
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
    print_form_created,
    print_form_detail,
    print_form_response_deleted,
    print_form_response_detail,
    print_form_response_state,
    print_form_responses_table,
    print_question,
    print_questions_table,
    print_reordered,
    print_success,
)


def _maybe_load_form(client: DailyBotClient, form_uuid: str) -> dict[str, Any] | None:
    """Return form metadata if accessible; swallow errors (UI-only enrichment)."""
    try:
        return client.get_form(form_uuid)
    except APIError:
        return None


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
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_list(include_archived: bool, json_mode: bool) -> None:
    """List forms visible to you.

    \b
    Acts as you. You can only see and act on what you could in the webapp.
    Archived forms are hidden unless you pass --include-archived.

    \b
    Examples:
      dailybot form list
      dailybot form list --include-archived
      dailybot form list --json
    """
    client = require_auth()
    execute_form_list(client, json_mode=json_mode, include_archived=include_archived)


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
def form_submit(
    form_uuid: str,
    content: str | None,
    assume_yes: bool,
    json_mode: bool,
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
    """
    client = require_auth()
    content_map = resolve_form_content(client, form_uuid, content)
    execute_form_submit(
        client,
        form_uuid,
        content_map,
        assume_yes=assume_yes,
        json_mode=json_mode,
    )


@form.command("responses")
@click.argument("form_uuid")
@click.option("--state", default=None, help="Filter by current_state (workflow forms only).")
@click.option(
    "--all",
    "all_responses",
    is_flag=True,
    help="List everyone's responses (admin/owner only; a member gets 403).",
)
@click.option("--user", default=None, help="Filter to one user's responses (admin/owner only).")
@click.option(
    "--from", "date_from", default=None, help="Responses on/after this date (YYYY-MM-DD)."
)
@click.option("--to", "date_to", default=None, help="Responses on/before this date (YYYY-MM-DD).")
@click.option(
    "--latest",
    is_flag=True,
    help="Return only the most recent response (continue where you left off).",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_responses(
    form_uuid: str,
    state: str | None,
    all_responses: bool,
    user: str | None,
    date_from: str | None,
    date_to: str | None,
    latest: bool,
    json_mode: bool,
) -> None:
    """List responses on a form.

    \b
    Acts as you. By default the server returns only responses you authored.
    --all / --user surface others' responses and are admin/owner-only
    (server-enforced — a member receives 403). --from / --to narrow the window.

    \b
    Examples:
      dailybot form responses <form_uuid>
      dailybot form responses <form_uuid> --state qa --json
      dailybot form responses <form_uuid> --all --from 2026-01-01 --to 2026-06-30
      dailybot form responses <form_uuid> --user <user_uuid> --json
    """
    client = require_auth()
    try:
        with console.status("Fetching responses..."):
            responses: list[dict[str, Any]] = client.list_form_responses(
                form_uuid,
                state=state,
                all_responses=all_responses,
                user=user,
                date_from=date_from,
                date_to=date_to,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if latest:
        responses = responses[:1] if responses else []

    if json_mode:
        emit_json(responses)
        return

    form_data: dict[str, Any] | None = _maybe_load_form(client, form_uuid)
    print_form_responses_table(form_uuid, responses, form_data)


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
    The form's state_change_permission audience is the sole gate — there is no
    response-author short-circuit. If you're not in the audience the API will
    return 403 / form_response_change_state_forbidden.

    \b
    Examples:
      dailybot form transition <form_uuid> <response_uuid> qa --note "QA assigned"
      dailybot form transition <form_uuid> <response_uuid> released --json
    """
    client = require_auth()

    summary_lines: list[str] = [
        f"Form UUID: {form_uuid}",
        f"Response UUID: {response_uuid}",
        f"To state: {to_state}",
    ]
    if note:
        summary_lines.append(f"Note: {note}")
    confirm_write(summary_lines, assume_yes)

    try:
        with console.status("Transitioning response..."):
            result: dict[str, Any] = client.transition_form_response(
                form_uuid=form_uuid,
                response_uuid=response_uuid,
                to_state=to_state,
                note=note,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return

    print_success(f"Response {response_uuid} transitioned to '{to_state}'.")
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
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_create(
    name: str,
    questions_file: str | None,
    interactive: bool,
    report_channels: tuple[str, ...],
    json_mode: bool,
) -> None:
    """Create a form (optionally seeded with questions).

    \b
    Creating forms is role-gated server-side (admins/managers as applicable).
    Seed questions with --questions-file or --interactive, or add them later via
    `dailybot form questions add`.

    \b
    Examples:
      dailybot form create --name "Sprint Retro"
      dailybot form create -n "Retro" --questions-file questions.json
      dailybot form create -n "Retro" --interactive
      dailybot form create -n "Retro" --report-channel <channel_uuid> --json
    """
    client = require_auth()
    if interactive:
        questions: list[dict[str, Any]] | None = build_questions_interactively()
    elif questions_file:
        questions = parse_questions_file(questions_file)
    else:
        questions = None
    try:
        with console.status("Creating form..."):
            result: dict[str, Any] = client.create_form(
                name,
                questions,
                report_channels=list(report_channels) if report_channels else None,
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
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_questions_add(
    form_uuid: str,
    question_type: str,
    question: str,
    options: str | None,
    required: bool,
    is_blocker: bool,
    json_mode: bool,
    **extra_flags: Any,
) -> None:
    """Add a question to a form.

    \b
    Extras: --short-question (report title), --variation (repeatable), and logic
    via --logic-file or inline --jump-if-equals/--jump-to.

    \b
    Examples:
      dailybot form questions add <form_uuid> --type text --question "What went well?"
      dailybot form questions add <form_uuid> --type multiple_choice \\
        --question "Rating?" --options "Excellent,Good,Average,Poor"
      dailybot form questions add <form_uuid> --type boolean --question "Ship it?" \\
        --short-question "Ship" --jump-if-equals "No" --jump-to 4
    """
    client = require_auth()
    extras: dict[str, Any] = resolve_question_extras(**extra_flags)
    payload: dict[str, Any] = build_question(
        question_type,
        question,
        options=parse_options(options),
        required=required,
        is_blocker=is_blocker,
        **extras,
    )
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
