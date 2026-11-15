"""A `403 sign_in_method_not_allowed` renders cleanly on every CLI sign-in path.

PLAN_015 (CONTRACT_AUTH_WAVE2 §2.6) never refuses a CLI path by design: the emailed
code is the locked `magic_link` method, the device flow inherits the approving web
session's method, and an API key is not a sign-in method. These tests pin the
defensive behaviour if a door ever answers the refusal anyway: the server's message,
a clean exit code, no traceback, and no credential written.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner, Result

from dailybot_cli.commands.public_api_helpers import EXIT_PERMISSION_DENIED
from dailybot_cli.config import load_credentials
from dailybot_cli.main import cli
from tests.wire_fixture_loader import fixture_response

POST: str = "dailybot_cli.api_client.httpx.post"
GET: str = "dailybot_cli.api_client.httpx.get"
SLEEP: str = "dailybot_cli.commands._device_login.time.sleep"
DETAIL: str = "Your organization does not allow this sign-in method."


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DAILYBOT_API_KEY", "DAILYBOT_CLI_TOKEN", "DAILYBOT_API_URL"):
        monkeypatch.delenv(name, raising=False)


def _refusal() -> MagicMock:
    body: dict[str, Any] = {"detail": DETAIL, "code": "sign_in_method_not_allowed"}
    response: MagicMock = MagicMock()
    response.status_code = 403
    response.headers = {}
    response.json.return_value = body
    response.text = json.dumps(body)
    return response


def _assert_clean(result: Result, exit_code: int) -> None:
    assert result.exit_code == exit_code, result.output
    # Only a deliberate SystemExit, never an escaped exception (which CliRunner keeps
    # in `result.exception` and would print as a traceback outside the runner).
    assert isinstance(result.exception, SystemExit)
    assert "Traceback" not in result.output
    assert DETAIL in " ".join(result.output.split())


@pytest.mark.parametrize(
    "args",
    [
        ["login", "--email", "me@example.com"],
        ["login", "--email", "me@example.com", "--code", "123456"],
    ],
    ids=["email-request", "email-verify"],
)
def test_the_email_code_paths(args: list[str]) -> None:
    with patch(POST, return_value=_refusal()):
        result: Result = CliRunner().invoke(cli, args)
    _assert_clean(result, 1)
    assert load_credentials() is None


def test_the_device_start() -> None:
    with patch(POST, return_value=_refusal()), patch(SLEEP):
        result: Result = CliRunner().invoke(cli, ["login", "--device"])
    _assert_clean(result, 1)
    assert load_credentials() is None


def test_the_device_poll() -> None:
    with patch(POST, side_effect=[fixture_response("device_start_200"), _refusal()]), patch(SLEEP):
        result: Result = CliRunner().invoke(cli, ["login", "--device"])
    _assert_clean(result, 1)
    assert load_credentials() is None


def test_an_api_key_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILYBOT_API_KEY", "test-key")
    with patch(GET, return_value=_refusal()):
        result: Result = CliRunner().invoke(cli, ["me"])
    _assert_clean(result, EXIT_PERMISSION_DENIED)
