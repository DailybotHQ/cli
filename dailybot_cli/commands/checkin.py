"""Check-in commands for the user-scoped public API."""

from typing import Any

import click

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import (
    USER_SCOPED_MODEL_HELP,
    confirm_write,
    emit_json,
    exit_for_api_error,
    find_pending_checkin,
    normalize_checkin_list_json,
    parse_answer_flags,
    require_bearer_auth,
    EXIT_USAGE_ERROR,
)
from dailybot_cli.display import (
    console,
    print_checkin_complete_result,
    print_checkin_list_overview,
    print_error,
    print_pending_checkins,
)


def _collect_answers(
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

    answers = []
    for index, question in enumerate(questions):
        prompt_text: str = str(question.get("question", f"Question {index + 1}"))
        answer: str = click.prompt(prompt_text, type=str)
        answers.append(answer)
    return answers


def _build_checkin_responses(
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
    {help}

    \b
    Examples:
      dailybot checkin list
      dailybot checkin list --json
    """.format(help=USER_SCOPED_MODEL_HELP)
    client = require_bearer_auth()
    try:
        with console.status("Fetching pending check-ins..."):
            data: dict[str, Any] = client.get_status()
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(normalize_checkin_list_json(data))
        return

    checkins: list[dict[str, Any]] = data.get("pending_checkins", [])
    print_checkin_list_overview(data.get("count", len(checkins)), checkins)
    print_pending_checkins(checkins)


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
    {help}

    \b
    Examples:
      dailybot checkin complete <followup_uuid>
      dailybot checkin complete <followup_uuid> -a 0="Shipped auth" -a 1="Reviewing migrations"
      dailybot checkin complete <followup_uuid> --yes
    """.format(help=USER_SCOPED_MODEL_HELP)
    client = require_bearer_auth()

    try:
        with console.status("Loading check-in questions..."):
            status_data: dict[str, Any] = client.get_status()
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

    answers: list[Any] = _collect_answers(questions, answer)
    responses: list[dict[str, Any]] = _build_checkin_responses(questions, answers)
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
