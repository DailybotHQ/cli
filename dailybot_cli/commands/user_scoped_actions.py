"""Shared handlers for user-scoped public API commands and interactive mode."""

import json
from typing import Any

import click

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    confirm_write,
    emit_json,
    exit_for_api_error,
    find_pending_checkin,
    normalize_checkin_list_json,
    parse_answer_flags,
    EXIT_USAGE_ERROR,
)
from dailybot_cli.display import (
    console,
    print_checkin_complete_result,
    print_checkin_list_overview,
    print_error,
    print_form_submit_result,
    print_forms_table,
    print_info,
    print_pending_checkins,
    print_users_table,
)


def collect_checkin_answers(
    questions: list[dict[str, Any]],
    answer_flags: tuple[str, ...],
) -> list[Any]:
    """Collect answers from flags or interactive prompts."""
    if answer_flags:
        try:
            indexed: dict[int, str] = parse_answer_flags(answer_flags)
        except ValueError as exc:
            print_error(str(exc))
            raise SystemExit(EXIT_USAGE_ERROR) from exc

        answers: list[Any] = []
        for index, question in enumerate(questions):
            if index not in indexed:
                print_error(
                    f'Missing answer for question {index}: "{question.get("question", "")}"'
                )
                raise SystemExit(EXIT_USAGE_ERROR)
            answers.append(indexed[index])
        return answers

    answers: list[Any] = []
    for index, question in enumerate(questions):
        prompt_text: str = str(question.get("question", f"Question {index + 1}"))
        answer: str = click.prompt(prompt_text, type=str)
        answers.append(answer)
    return answers


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


def collect_form_content_interactive() -> dict[str, Any]:
    """Collect question UUID → answer pairs via prompts."""
    print_info("Enter answers as question UUID → value pairs. Leave UUID empty when done.")
    content: dict[str, Any] = {}
    while True:
        question_uuid: str = click.prompt(
            "Question UUID",
            default="",
            show_default=False,
        ).strip()
        if not question_uuid:
            break
        answer: str = click.prompt("Answer", type=str)
        content[question_uuid] = answer

    if not content:
        print_error("No answers provided.")
        raise SystemExit(EXIT_USAGE_ERROR)
    return content


def parse_form_content(raw_content: str | None) -> dict[str, Any]:
    """Parse --content JSON or prompt interactively when omitted."""
    if not raw_content:
        return collect_form_content_interactive()

    try:
        parsed: Any = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        print_error(f"Invalid JSON for --content: {exc}")
        raise SystemExit(EXIT_USAGE_ERROR) from exc

    if not isinstance(parsed, dict):
        print_error("--content must be a JSON object mapping question UUIDs to answers.")
        raise SystemExit(EXIT_USAGE_ERROR)

    return parsed


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
            f'No pending check-in found for followup "{followup_uuid}". '
            "Run: dailybot checkin list"
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

    answers: list[Any] = collect_checkin_answers(questions, answer_flags)
    responses: list[dict[str, Any]] = build_checkin_responses(questions, answers)
    last_question_index: int = len(responses) - 1
    followup_name: str = str(checkin_data.get("followup_name", followup_uuid))

    summary_lines: list[str] = [
        f"Check-in: {followup_name}",
        f"Followup UUID: {followup_uuid}",
    ]
    for index, question in enumerate(questions):
        summary_lines.append(f'  Q{index + 1}: {question.get("question", "")}')
        summary_lines.append(f'  A{index + 1}: {answers[index]}')
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
    """Fetch and display forms visible to the user."""
    try:
        with console.status("Fetching forms..."):
            forms: list[dict[str, Any]] = client.list_forms()
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(forms)
        return forms

    print_forms_table(forms)
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
) -> list[dict[str, Any]] | None:
    """Fetch and display organization members."""
    try:
        with console.status("Fetching team members..."):
            users: list[dict[str, Any]] = client.list_users()
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(users)
        return users

    print_users_table(users)
    return users
