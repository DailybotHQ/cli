"""Form commands for the user-scoped public API."""

import click

from dailybot_cli.commands.public_api_helpers import require_bearer_auth
from dailybot_cli.commands.user_scoped_actions import (
    execute_form_list,
    execute_form_submit,
    resolve_form_content,
)


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
