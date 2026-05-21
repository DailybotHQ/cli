"""Form commands for the user-scoped public API."""

import click

from dailybot_cli.commands.public_api_helpers import USER_SCOPED_MODEL_HELP, require_bearer_auth
from dailybot_cli.commands.user_scoped_actions import (
    execute_form_list,
    execute_form_submit,
    parse_form_content,
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
    {help}

    \b
    Examples:
      dailybot form list
      dailybot form list --json
    """.format(help=USER_SCOPED_MODEL_HELP)
    client = require_bearer_auth()
    execute_form_list(client, json_mode=json_mode)


@form.command("submit")
@click.argument("form_uuid")
@click.option(
    "--content",
    "-c",
    default=None,
    help='JSON map of question UUID to answer, e.g. \'{"<uuid>":"Yes"}\'. Prompts when omitted.',
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

    When --content is omitted, the CLI prompts for question UUID and answer pairs.
    For guided prompts per question label, the API must expose form question
    definitions (see GET /v1/forms/{{uuid}}/ in the CLI/API integration notes).

    \b
    Examples:
      dailybot form submit <form_uuid>
      dailybot form submit <form_uuid> --content '{{"<question_uuid>":"Yes"}}'
      dailybot form submit <form_uuid> --content '{{"<uuid>":"Answer"}}' --yes
    """.format(help=USER_SCOPED_MODEL_HELP)
    client = require_bearer_auth()
    content_map = parse_form_content(content)
    execute_form_submit(
        client,
        form_uuid,
        content_map,
        assume_yes=assume_yes,
        json_mode=json_mode,
    )
