"""Shared handlers for user-scoped public API commands and interactive mode."""

import json
from datetime import date as date_cls, timedelta
from typing import Any

import click
import questionary

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    EXIT_USAGE_ERROR,
    InteractiveAbort,
    confirm_write,
    emit_json,
    exit_for_api_error,
    find_pending_checkin,
    normalize_checkin_list_json,
    parse_answer_flags,
)
from dailybot_cli.display import (
    console,
    print_checkin_complete_result,
    print_checkin_detail,
    print_checkin_history_table,
    print_checkin_list_overview,
    print_checkin_status_table,
    print_error,
    print_form_submit_result,
    print_forms_table,
    print_info,
    print_pending_checkins,
    print_success,
    print_users_table,
)


def collect_checkin_answers(
    questions: list[dict[str, Any]],
    answer_flags: tuple[str, ...],
    *,
    interactive: bool = False,
) -> list[Any]:
    """Collect answers from flags or interactive prompts."""
    collected: list[Any] = []
    if answer_flags:
        try:
            indexed: dict[int, str] = parse_answer_flags(answer_flags)
        except ValueError as exc:
            print_error(str(exc))
            raise SystemExit(EXIT_USAGE_ERROR) from exc

        for index, question in enumerate(questions):
            if index not in indexed:
                print_error(
                    f'Missing answer for question {index}: "{question.get("question", "")}"'
                )
                raise SystemExit(EXIT_USAGE_ERROR)
            collected.append(indexed[index])
        return collected

    for index, question in enumerate(questions):
        prompt_text: str = str(question.get("question", f"Question {index + 1}"))
        if interactive:
            collected.append(_prompt_form_answer(question, prompt_text, interactive=True))
        else:
            answer: str = click.prompt(prompt_text, type=str)
            collected.append(answer)
    return collected


def build_checkin_responses(
    questions: list[dict[str, Any]],
    answers: list[Any],
) -> list[dict[str, Any]]:
    """Build the POST payload entries for complete_checkin."""
    responses: list[dict[str, Any]] = []
    for index, (question, answer) in enumerate(zip(questions, answers, strict=True)):
        responses.append(
            {
                "uuid": question["uuid"],
                "index": index,
                "response": answer,
            }
        )
    return responses


FORM_QUESTION_TYPES_TEXT: frozenset[str] = frozenset(
    {"text", "text_field", "short_text", "long_text", "textarea", "string"}
)
FORM_QUESTION_TYPES_NUMERIC: frozenset[str] = frozenset(
    {"number", "numeric", "integer", "int", "float", "decimal"}
)
FORM_QUESTION_TYPES_BOOLEAN: frozenset[str] = frozenset(
    {"boolean", "bool", "yes_no", "yes/no", "toggle"}
)
FORM_QUESTION_TYPES_CHOICE: frozenset[str] = frozenset(
    {
        "choice",
        "choices",
        "multiple_choice",
        "single_choice",
        "select",
        "dropdown",
        "radio",
    }
)


def filter_submittable_forms(forms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return forms that have an ID and can be submitted."""
    return [form for form in forms if form.get("id")]


def extract_form_questions(form_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return question definitions from a form detail payload."""
    for key in ("questions", "template_questions", "fields"):
        raw: Any = form_data.get(key)
        if isinstance(raw, list) and raw:
            return raw
    return []


def _form_question_uuid(question: dict[str, Any]) -> str | None:
    for key in ("uuid", "id", "question_uuid"):
        value: Any = question.get(key)
        if value:
            return str(value)
    return None


def _form_question_label(question: dict[str, Any], index: int) -> str:
    for key in ("question", "text", "label", "name", "title"):
        value: Any = question.get(key)
        if value:
            return str(value)
    return f"Question {index + 1}"


def _form_question_choices(question: dict[str, Any]) -> list[str]:
    raw: Any = question.get("choices") or question.get("options") or []
    if not isinstance(raw, list):
        return []

    choices: list[str] = []
    for item in raw:
        if isinstance(item, str):
            choices.append(item)
        elif isinstance(item, dict):
            label: Any = item.get("label") or item.get("text") or item.get("value")
            if label:
                choices.append(str(label))
    return choices


def _classify_form_question_type(question: dict[str, Any]) -> str:
    """Map API question_type values to a supported prompt strategy."""
    raw_type: Any = question.get("question_type") or question.get("type") or ""
    normalized: str = str(raw_type).strip().lower().replace("-", "_").replace(" ", "_")

    if normalized in FORM_QUESTION_TYPES_CHOICE or _form_question_choices(question):
        return "choice"
    if normalized in FORM_QUESTION_TYPES_BOOLEAN:
        return "boolean"
    if normalized in FORM_QUESTION_TYPES_NUMERIC:
        return "numeric"
    return "text"


def _prompt_choice_answer(
    prompt_text: str,
    choices: list[str],
    *,
    interactive: bool = False,
) -> str:
    """Prompt for a single-choice answer."""
    if not choices:
        print_error("Choice question is missing options.")
        raise SystemExit(EXIT_USAGE_ERROR)

    selected: str | None = questionary.select(prompt_text, choices=choices).ask()
    if selected is not None:
        return selected
    if interactive:
        raise InteractiveAbort()

    print_info("Select by number:")
    for index, choice in enumerate(choices, start=1):
        click.echo(f"  {index}. {choice}")

    while True:
        choice_index: int = click.prompt("Number", type=int)
        if 1 <= choice_index <= len(choices):
            return choices[choice_index - 1]
        print_error(f"Enter a number between 1 and {len(choices)}.")


def _prompt_boolean_answer(prompt_text: str, *, interactive: bool = False) -> bool:
    """Prompt for a yes/no answer."""
    selected: bool | None = questionary.confirm(prompt_text, default=False).ask()
    if selected is not None:
        return selected
    if interactive:
        raise InteractiveAbort()

    while True:
        raw: str = click.prompt(f"{prompt_text} (yes/no)", type=str).strip().lower()
        if raw in {"y", "yes", "true", "1"}:
            return True
        if raw in {"n", "no", "false", "0"}:
            return False
        print_error('Enter "yes" or "no".')


def _prompt_numeric_answer(prompt_text: str, *, interactive: bool = False) -> int | float:
    """Prompt for a numeric answer."""
    while True:
        if interactive:
            raw_interactive: str | None = questionary.text(prompt_text).ask()
            if raw_interactive is None:
                raise InteractiveAbort()
            raw = raw_interactive.strip()
        else:
            raw = click.prompt(prompt_text, type=str).strip()
        try:
            if "." in raw:
                return float(raw)
            return int(raw)
        except ValueError:
            print_error("Enter a valid number.")


def _prompt_text_answer(prompt_text: str, *, interactive: bool = False) -> str:
    """Prompt for a free-text answer."""
    if interactive:
        raw: str | None = questionary.text(prompt_text).ask()
        if raw is None:
            raise InteractiveAbort()
        return raw
    return click.prompt(prompt_text, type=str)


def _prompt_form_answer(
    question: dict[str, Any],
    prompt_text: str,
    *,
    interactive: bool = False,
) -> Any:
    """Prompt once for a form question according to its type."""
    question_type: str = _classify_form_question_type(question)

    if question_type == "choice":
        return _prompt_choice_answer(
            prompt_text,
            _form_question_choices(question),
            interactive=interactive,
        )
    if question_type == "boolean":
        return _prompt_boolean_answer(prompt_text, interactive=interactive)
    if question_type == "numeric":
        return _prompt_numeric_answer(prompt_text, interactive=interactive)
    return _prompt_text_answer(prompt_text, interactive=interactive)


def collect_form_answers_by_label(
    questions: list[dict[str, Any]],
    *,
    interactive: bool = False,
) -> dict[str, Any]:
    """Prompt for each form question in order and build the content map."""
    content: dict[str, Any] = {}
    for index, question in enumerate(questions):
        question_uuid: str | None = _form_question_uuid(question)
        if not question_uuid:
            continue

        prompt_text: str = _form_question_label(question, index)
        content[question_uuid] = _prompt_form_answer(
            question,
            prompt_text,
            interactive=interactive,
        )

    if not content:
        print_error("This form has no answerable questions.")
        raise SystemExit(EXIT_USAGE_ERROR)
    return content


def collect_form_content_guided(
    client: DailyBotClient,
    form_uuid: str,
    *,
    interactive: bool = False,
) -> dict[str, Any]:
    """Load form questions from the API and collect answers interactively."""
    try:
        with console.status("Loading form questions..."):
            form_data: dict[str, Any] = client.get_form(form_uuid)
    except APIError as exc:
        if exc.status_code == 404:
            print_error(
                "Form question definitions are not available. "
                "The API must expose GET /v1/forms/{uuid}/ with a questions list."
            )
            raise SystemExit(EXIT_USAGE_ERROR) from exc
        exit_for_api_error(exc, json_mode=False)

    questions: list[dict[str, Any]] = extract_form_questions(form_data)
    if not questions:
        print_error(
            "This form returned no question definitions. "
            "GET /v1/forms/{uuid}/ must include a questions array."
        )
        raise SystemExit(EXIT_USAGE_ERROR)

    return collect_form_answers_by_label(questions, interactive=interactive)


def parse_form_content_json(raw_content: str) -> dict[str, Any]:
    """Parse a --content JSON map."""
    try:
        parsed: Any = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        print_error(f"Invalid JSON for --content: {exc}")
        raise SystemExit(EXIT_USAGE_ERROR) from exc

    if not isinstance(parsed, dict):
        print_error("--content must be a JSON object mapping question UUIDs to answers.")
        raise SystemExit(EXIT_USAGE_ERROR)

    return parsed


def resolve_form_content(
    client: DailyBotClient,
    form_uuid: str,
    raw_content: str | None,
) -> dict[str, Any]:
    """Parse --content JSON or prompt for each question when omitted."""
    if raw_content:
        return parse_form_content_json(raw_content)
    return collect_form_content_guided(client, form_uuid)


def find_form_name(forms: list[dict[str, Any]], form_uuid: str) -> str:
    """Return the display name for a form UUID when known."""
    for form in forms:
        if form.get("id") == form_uuid:
            return str(form.get("name") or form_uuid)
    return form_uuid


def execute_checkin_list(
    client: DailyBotClient,
    *,
    json_mode: bool = False,
) -> dict[str, Any] | None:
    """Fetch and display pending check-ins."""
    try:
        with console.status("Fetching pending check-ins..."):
            data: dict[str, Any] = client.get_status()
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(normalize_checkin_list_json(data))
        return data

    checkins: list[dict[str, Any]] = data.get("pending_checkins", [])
    print_checkin_list_overview(data.get("count", len(checkins)), checkins)
    if checkins:
        print_pending_checkins(checkins)
    return data


def execute_checkin_complete(
    client: DailyBotClient,
    followup_uuid: str,
    *,
    answer_flags: tuple[str, ...] = (),
    response_date: str | None = None,
    assume_yes: bool = False,
    json_mode: bool = False,
    status_data: dict[str, Any] | None = None,
    interactive: bool = False,
) -> None:
    """Complete a pending check-in."""
    if status_data is None:
        try:
            with console.status("Loading check-in questions..."):
                status_data = client.get_status()
        except APIError as exc:
            exit_for_api_error(exc, json_mode)

    checkin_data: dict[str, Any] | None = find_pending_checkin(
        status_data.get("pending_checkins", []),
        followup_uuid,
    )
    if checkin_data is None:
        message: str = (
            f'No pending check-in found for followup "{followup_uuid}". Run: dailybot checkin list'
        )
        if json_mode:
            emit_json({"error": message, "status": 0})
        else:
            print_error(message)
        raise SystemExit(EXIT_USAGE_ERROR)

    questions: list[dict[str, Any]] = checkin_data.get("template_questions", [])
    if not questions:
        print_error("This check-in has no questions to answer.")
        raise SystemExit(EXIT_USAGE_ERROR)

    answers: list[Any] = collect_checkin_answers(
        questions,
        answer_flags,
        interactive=interactive,
    )
    responses: list[dict[str, Any]] = build_checkin_responses(questions, answers)
    last_question_index: int = len(responses) - 1
    followup_name: str = str(checkin_data.get("followup_name", followup_uuid))

    summary_lines: list[str] = [
        f"Check-in: {followup_name}",
        f"Followup UUID: {followup_uuid}",
    ]
    for index, question in enumerate(questions):
        summary_lines.append(f"  Q{index + 1}: {question.get('question', '')}")
        summary_lines.append(f"  A{index + 1}: {answers[index]}")
    if response_date:
        summary_lines.append(f"Response date: {response_date}")

    confirm_write(summary_lines, assume_yes)

    try:
        with console.status("Submitting check-in..."):
            result: dict[str, Any] = client.complete_checkin(
                followup_uuid=followup_uuid,
                responses=responses,
                last_question_index=last_question_index,
                response_date=response_date,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return

    print_checkin_complete_result(followup_name, result)


def execute_form_list(
    client: DailyBotClient,
    *,
    json_mode: bool = False,
) -> list[dict[str, Any]] | None:
    """Fetch and display forms visible to the user (with question counts)."""
    try:
        with console.status("Fetching forms..."):
            forms: list[dict[str, Any]] = client.list_forms(include_questions=True)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(forms)
        return forms

    print_forms_table(filter_submittable_forms(forms))
    return forms


def execute_form_submit(
    client: DailyBotClient,
    form_uuid: str,
    content_map: dict[str, Any],
    *,
    form_name: str | None = None,
    assume_yes: bool = False,
    json_mode: bool = False,
) -> None:
    """Submit a form response."""
    resolved_name: str = form_name or form_uuid
    if form_name is None:
        try:
            with console.status("Looking up form..."):
                forms: list[dict[str, Any]] = client.list_forms()
            resolved_name = find_form_name(forms, form_uuid)
        except APIError:
            resolved_name = form_uuid

    summary_lines: list[str] = [
        f"Form: {resolved_name}",
        f"Form UUID: {form_uuid}",
        "Answers:",
    ]
    for question_uuid, answer in content_map.items():
        summary_lines.append(f"  {question_uuid}: {answer}")

    confirm_write(summary_lines, assume_yes)

    try:
        with console.status("Submitting form response..."):
            result: dict[str, Any] = client.submit_form_response(
                form_uuid=form_uuid,
                content=content_map,
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result)
        return

    print_form_submit_result(resolved_name, result)


def execute_user_list(
    client: DailyBotClient,
    *,
    json_mode: bool = False,
    include_inactive: bool = False,
) -> list[dict[str, Any]] | None:
    """Fetch and display organization members.

    By default only active members are returned; pass ``include_inactive=True``
    to include deactivated accounts.
    """
    try:
        with console.status("Fetching team members..."):
            users: list[dict[str, Any]] = client.list_users(include_inactive=include_inactive)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(users)
        return users

    print_users_table(users)
    return users


def _template_uuid(checkin: dict[str, Any]) -> str:
    """Best-effort template UUID from a check-in detail payload."""
    template: Any = checkin.get("template")
    if isinstance(template, dict):
        return str(template.get("uuid") or template.get("id") or "")
    return str(checkin.get("template_uuid") or template or "")


def execute_checkin_status(
    client: DailyBotClient,
    *,
    date: str | None = None,
    json_mode: bool = False,
) -> None:
    """Show pending/completed state for check-ins on a date (default today)."""
    try:
        with console.status("Fetching check-ins..."):
            checkins: list[dict[str, Any]] = client.list_checkins(date=date, include_summary=True)
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json({"date": date or "today", "count": len(checkins), "checkins": checkins})
        return
    print_checkin_status_table(checkins, date_label=date or "today")


def execute_checkin_show(
    client: DailyBotClient,
    followup_uuid: str,
    *,
    json_mode: bool = False,
) -> None:
    """Show a check-in's configuration and question definitions."""
    try:
        with console.status("Loading check-in..."):
            checkin: dict[str, Any] = client.get_checkin(followup_uuid)
            questions: list[dict[str, Any]] = []
            template_uuid: str = _template_uuid(checkin)
            if template_uuid:
                template: dict[str, Any] = client.get_template(
                    template_uuid, followup_uuid=followup_uuid
                )
                raw_questions: Any = template.get("questions") or template.get("template_questions")
                if isinstance(raw_questions, list):
                    questions = raw_questions
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json({"checkin": checkin, "questions": questions})
        return
    print_checkin_detail(checkin, questions)


def execute_checkin_history(
    client: DailyBotClient,
    followup_uuid: str,
    *,
    days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    json_mode: bool = False,
) -> None:
    """Show a check-in's response history over a date range."""
    date_start: str | None = date_from
    date_end: str | None = date_to
    if days is not None:
        today: date_cls = date_cls.today()
        date_end = today.isoformat()
        date_start = (today - timedelta(days=max(days - 1, 0))).isoformat()
    try:
        with console.status("Fetching response history..."):
            responses: list[dict[str, Any]] = client.list_checkin_responses(
                followup_uuid, date_start=date_start, date_end=date_end
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(
            {
                "count": len(responses),
                "date_start": date_start,
                "date_end": date_end,
                "responses": responses,
            }
        )
        return
    print_checkin_history_table(responses)


def execute_checkin_reset(
    client: DailyBotClient,
    followup_uuid: str,
    *,
    response_date: str | None = None,
    assume_yes: bool = False,
    json_mode: bool = False,
) -> None:
    """Delete (reset) the caller's own check-in response for a date."""
    target: str = response_date or "today"
    if not json_mode:
        confirm_write([f"Delete your check-in response for {target}? This cannot be undone."], assume_yes)
    try:
        with console.status("Deleting response..."):
            result: dict[str, Any] = client.delete_checkin_response(
                followup_uuid, response_date=response_date
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result if isinstance(result, dict) else {"deleted": True})
        return
    deleted_count: Any = result.get("deleted_count") if isinstance(result, dict) else None
    if deleted_count:
        print_success(f"Deleted {deleted_count} response(s) for {target}.")
    else:
        print_success(f"Reset check-in response for {target}.")


def execute_checkin_edit(
    client: DailyBotClient,
    followup_uuid: str,
    *,
    answer_flags: tuple[str, ...] = (),
    response_date: str | None = None,
    assume_yes: bool = False,
    json_mode: bool = False,
    interactive: bool = False,
) -> None:
    """Edit an existing check-in response (override answers, then PUT)."""
    try:
        with console.status("Loading current response..."):
            existing: list[dict[str, Any]] = client.list_checkin_responses(
                followup_uuid, date_start=response_date, date_end=response_date
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if not existing:
        message: str = "No existing response to edit. Use `dailybot checkin complete` to create one."
        if json_mode:
            emit_json({"error": message, "status": 0})
        else:
            print_error(message)
        raise SystemExit(EXIT_USAGE_ERROR)

    answers: list[dict[str, Any]] = existing[0].get("responses") or []
    try:
        overrides: dict[int, str] = parse_answer_flags(answer_flags)
    except ValueError as exc:
        if json_mode:
            emit_json({"error": str(exc), "status": 0})
        else:
            print_error(str(exc))
        raise SystemExit(EXIT_USAGE_ERROR) from exc

    new_responses: list[dict[str, Any]] = []
    for index, answer in enumerate(answers):
        current: Any = answer.get("response")
        if index in overrides:
            value: Any = overrides[index]
        elif interactive and not json_mode:
            prompt: str = str(answer.get("question") or f"Question {index}")
            reply: str | None = questionary.text(f"{prompt}", default=str(current or "")).ask()
            if reply is None:
                raise InteractiveAbort()
            value = reply
        else:
            value = current
        new_responses.append(
            {"uuid": answer.get("uuid"), "index": index, "response": value}
        )

    if not new_responses:
        print_error("This response has no answers to edit.")
        raise SystemExit(EXIT_USAGE_ERROR)

    if not json_mode and not interactive:
        confirm_write([f"Update your check-in response for {response_date or 'today'}?"], assume_yes)

    try:
        with console.status("Updating response..."):
            result: dict[str, Any] = client.update_checkin_response(
                followup_uuid, new_responses, last_question_index=len(new_responses) - 1
            )
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(result if isinstance(result, dict) else {"updated": True})
        return
    print_success(f"Updated check-in response for {response_date or 'today'}.")
