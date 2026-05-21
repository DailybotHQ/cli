"""Form commands for the user-scoped public API."""

import json
from typing import Any

import click

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import (
    USER_SCOPED_MODEL_HELP,
    confirm_write,
    emit_json,
    exit_for_api_error,
    require_bearer_auth,
    EXIT_USAGE_ERROR,
)
from dailybot_cli.display import (
    console,
    print_error,
    print_form_submit_result,
    print_forms_table,
)


def _parse_content_flag(raw_content: str | None) -> dict[str, Any]:
    """Parse the --content JSON map flag."""
    if not raw_content:
        print_error(
            "Missing --content. Provide a JSON map of question UUID to answer, "
            'e.g. --content \'{"<question_uuid>":"Yes"}\''
        )
        raise SystemExit(EXIT_USAGE_ERROR)

    try:
        parsed: Any = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        print_error(f"Invalid JSON for --content: {exc}")
        raise SystemExit(EXIT_USAGE_ERROR) from exc

    if not isinstance(parsed, dict):
        print_error("--content must be a JSON object mapping question UUIDs to answers.")
        raise SystemExit(EXIT_USAGE_ERROR)

    return parsed


def _find_form_name(forms: list[dict[str, Any]], form_uuid: str) -> str:
    """Return the display name for a form UUID when known."""
    for form in forms:
        if form.get("id") == form_uuid:
            return str(form.get("name") or form_uuid)
    return form_uuid


@click.group()
def form() -> None:
    """Manage forms with your Dailybot session.

    \b
    Acts as you — visibility and permissions match the webapp for your account.
    """


@form.command("list")
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_list(json_mode: bool) -> None:
    """List forms visible to you.

    \b
    {help}

    \b
    Examples:
      dailybot form list
      dailybot form list --json
    """.format(help=USER_SCOPED_MODEL_HELP)
    client = require_bearer_auth()
    try:
        with console.status("Fetching forms..."):
            forms: list[dict[str, Any]] = client.list_forms()
    except APIError as exc:
        exit_for_api_error(exc, json_mode)

    if json_mode:
        emit_json(forms)
        return

    print_forms_table(forms)


@form.command("submit")
@click.argument("form_uuid")
@click.option(
    "--content",
    "-c",
    default=None,
    help='JSON map of question UUID to answer, e.g. \'{"<uuid>":"Yes"}\'.',
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
    {help}

    Question UUIDs are keys in the content map. The form list endpoint does not
    include question definitions — use UUIDs you already know.

    \b
    Examples:
      dailybot form submit <form_uuid> --content '{{"<question_uuid>":"Yes"}}'
      dailybot form submit <form_uuid> --content '{{"<uuid>":"Answer"}}' --yes
    """.format(help=USER_SCOPED_MODEL_HELP)
    client = require_bearer_auth()
    content_map: dict[str, Any] = _parse_content_flag(content)

    form_name: str = form_uuid
    try:
        with console.status("Looking up form..."):
            forms: list[dict[str, Any]] = client.list_forms()
        form_name = _find_form_name(forms, form_uuid)
    except APIError:
        form_name = form_uuid

    summary_lines: list[str] = [
        f"Form: {form_name}",
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

    print_form_submit_result(form_name, result)
