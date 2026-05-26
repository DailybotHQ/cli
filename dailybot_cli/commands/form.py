"""Form commands for the user-scoped public API."""

from typing import Any

import click

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    confirm_write,
    emit_json,
    exit_for_api_error,
    require_bearer_auth,
)
from dailybot_cli.commands.user_scoped_actions import (
    execute_form_list,
    execute_form_submit,
    parse_form_content_json,
    resolve_form_content,
)
from dailybot_cli.display import (
    console,
    print_form_detail,
    print_form_response_deleted,
    print_form_response_detail,
    print_form_response_state,
    print_form_responses_table,
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
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_list(json_mode: bool) -> None:
    """List forms visible to you.

    \b
    Acts as you. You can only see and act on what you could in the webapp.

    \b
    Examples:
      dailybot form list
      dailybot form list --json
    """
    client = require_bearer_auth()
    execute_form_list(client, json_mode=json_mode)


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
    client = require_bearer_auth()
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
    client = require_bearer_auth()
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
    "--latest",
    is_flag=True,
    help="Return only the most recent response (continue where you left off).",
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable JSON to stdout.")
def form_responses(
    form_uuid: str,
    state: str | None,
    latest: bool,
    json_mode: bool,
) -> None:
    """List your own responses on a form.

    \b
    Acts as you. The server returns only responses you authored.

    \b
    Examples:
      dailybot form responses <form_uuid>
      dailybot form responses <form_uuid> --state qa --json
      dailybot form responses <form_uuid> --latest --json
    """
    client = require_bearer_auth()
    try:
        with console.status("Fetching responses..."):
            responses: list[dict[str, Any]] = client.list_form_responses(form_uuid, state=state)
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
    client = require_bearer_auth()
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
    """Patch new answers into one of your own in-progress responses.

    \b
    Own-only. Admins are NOT elevated to other users' responses here.

    \b
    Examples:
      dailybot form update <form_uuid> <response_uuid> \\
        --content '{"<question_uuid>": "PR #4242"}'
      dailybot form update <form_uuid> <response_uuid> -c '{...}' --yes --json
    """
    client = require_bearer_auth()
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
    client = require_bearer_auth()

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
    client = require_bearer_auth()

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
