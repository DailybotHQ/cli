"""Attach, session, device and channel-reference codes (PLAN_002 T-error-catalogue).

The CLI dispatches on `code`, never on `detail` prose (AGENTS.md Rule 10). Each new
code has a catalogue message; the exit code follows the status as for every other
code; an unknown code still falls back to the server detail.
"""

import json

import pytest

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import (
    ERROR_CODE_MESSAGES,
    EXIT_NOT_AUTHENTICATED,
    EXIT_PERMISSION_DENIED,
    EXIT_USAGE_ERROR,
    exit_for_api_error,
)

# (code, the status its door answers with, the exit code that status maps to)
NEW_CODES: list[tuple[str, int, int]] = [
    ("tenant_already_bound", 409, 1),
    ("pending_link", 409, 1),
    ("channel_write_forbidden", 400, EXIT_USAGE_ERROR),
    ("tenant_ambiguous", 409, 1),
    ("channel_attach_unsupported", 409, 1),
    ("attach_forbidden", 403, EXIT_PERMISSION_DENIED),
    ("feature_not_available", 403, EXIT_PERMISSION_DENIED),
    ("session_revoked", 401, EXIT_NOT_AUTHENTICATED),
    ("session_migrated", 401, EXIT_NOT_AUTHENTICATED),
    ("refresh_token_expired", 401, EXIT_NOT_AUTHENTICATED),
    ("access_token_expired", 401, EXIT_NOT_AUTHENTICATED),
    ("user_disabled", 401, EXIT_NOT_AUTHENTICATED),
    ("invalid_grant", 400, EXIT_USAGE_ERROR),
    ("invalid_client", 400, EXIT_USAGE_ERROR),
    ("authorization_pending", 400, EXIT_USAGE_ERROR),
    ("slow_down", 400, EXIT_USAGE_ERROR),
    ("access_denied", 400, EXIT_USAGE_ERROR),
    ("expired_token", 400, EXIT_USAGE_ERROR),
    ("channel_reference_ambiguous", 409, 1),
    ("channel_reference_unknown", 400, EXIT_USAGE_ERROR),
]
DETAIL: str = "server prose that must not be shown when a code maps"


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize("code,status,exit_code", NEW_CODES, ids=[c[0] for c in NEW_CODES])
def test_each_code_renders_its_message_and_exit_code(
    code: str, status: int, exit_code: int, capsys: pytest.CaptureFixture[str]
) -> None:
    assert ERROR_CODE_MESSAGES[code]
    with pytest.raises(SystemExit) as caught:
        exit_for_api_error(APIError(status, DETAIL, code=code), json_mode=False)
    assert caught.value.code == exit_code
    err: str = _flat(capsys.readouterr().err)
    assert _flat(ERROR_CODE_MESSAGES[code]) in err
    assert DETAIL not in err


@pytest.mark.parametrize("code,status,exit_code", NEW_CODES, ids=[c[0] for c in NEW_CODES])
def test_json_mode_keeps_the_code(
    code: str, status: int, exit_code: int, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        exit_for_api_error(APIError(status, DETAIL, code=code), json_mode=True)
    payload: dict[str, object] = json.loads(capsys.readouterr().out)
    assert payload["code"] == code
    assert payload["status"] == status


@pytest.mark.parametrize("code", [c[0] for c in NEW_CODES])
def test_messages_use_the_brand_spelling(code: str) -> None:
    assert "DailyBot" not in ERROR_CODE_MESSAGES[code]


def test_an_unknown_code_still_falls_back_to_the_detail(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        exit_for_api_error(APIError(409, "Some new conflict.", code="brand_new_code"), False)
    assert caught.value.code == 1
    assert "Some new conflict." in capsys.readouterr().err


def test_an_existing_401_code_keeps_the_session_expired_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        exit_for_api_error(APIError(401, "x", code="invalid_credentials"), False)
    assert caught.value.code == EXIT_NOT_AUTHENTICATED
    assert "Session expired. Run: dailybot login" in capsys.readouterr().err


def test_a_401_without_a_code_keeps_the_session_expired_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        exit_for_api_error(APIError(401, "x"), False)
    assert "Session expired. Run: dailybot login" in capsys.readouterr().err


def test_qualified_reference_hints_name_the_forms() -> None:
    ambiguous: str = ERROR_CODE_MESSAGES["channel_reference_ambiguous"]
    assert "slack:" in ambiguous and "dailybot org" in ambiguous
    assert "dailybot org" in ERROR_CODE_MESSAGES["channel_reference_unknown"]
