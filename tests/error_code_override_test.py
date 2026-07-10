"""A single error `code` can mean different things in different commands.

`invalid_workflow_state` is returned both by form authoring (a malformed
`--state "Label:#color"`) and by the responses listing (`--state <key>` used on
a form that has no workflow). The shared table cannot say both, so a command may
override the message for the codes it can disambiguate.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import ERROR_CODE_MESSAGES, exit_for_api_error
from dailybot_cli.main import cli

FORM_UUID: str = "76174afc-490b-489b-b5cf-e9f84e000001"


def test_shared_table_message_is_used_by_default(capsys) -> None:
    exc = APIError(400, "bad", code="invalid_workflow_state")
    with pytest.raises(SystemExit):
        exit_for_api_error(exc, json_mode=False)
    assert "Label:#color" in capsys.readouterr().err


def test_override_replaces_the_message_for_that_code(capsys) -> None:
    exc = APIError(400, "bad", code="invalid_workflow_state")
    with pytest.raises(SystemExit):
        exit_for_api_error(
            exc, json_mode=False, code_overrides={"invalid_workflow_state": "no workflow here"}
        )
    err = capsys.readouterr().err
    assert "no workflow here" in err
    assert "Label:#color" not in err


def test_override_ignores_other_codes(capsys) -> None:
    exc = APIError(400, "bad", code="invalid_date_range")
    with pytest.raises(SystemExit):
        exit_for_api_error(
            exc, json_mode=False, code_overrides={"invalid_workflow_state": "unused"}
        )
    err = capsys.readouterr().err
    # Rich wraps the long shared message across lines, so match its opening words.
    assert ERROR_CODE_MESSAGES["invalid_date_range"][:20] in err
    assert "unused" not in err


def test_json_mode_carries_the_overridden_message() -> None:
    exc = APIError(400, "bad", code="invalid_workflow_state")
    with pytest.raises(SystemExit):
        exit_for_api_error(
            exc, json_mode=True, code_overrides={"invalid_workflow_state": "no workflow here"}
        )


@patch("dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value="tok")
@patch("dailybot_cli.commands.public_api_helpers.DailyBotClient")
def test_form_responses_explains_a_form_without_a_workflow(
    mock_client_cls: MagicMock, _auth: MagicMock
) -> None:
    client = mock_client_cls.return_value
    client.list_form_responses.side_effect = APIError(
        400,
        "This form does not have a workflow. The 'state' filter is not applicable.",
        code="invalid_workflow_state",
    )
    result = CliRunner().invoke(cli, ["form", "responses", FORM_UUID, "--state", "draft"])
    assert result.exit_code != 0
    assert "workflow" in result.output.lower()
    assert "Label:#color" not in result.output
