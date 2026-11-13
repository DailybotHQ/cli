"""The `deprecation` field on the legacy email-code doors (PLAN_002 T-deprecation-code, W1, L48).

While `CLI_AUTH_DEPRECATION_NOTICE` is on, request-code and verify-code add
`deprecation: {code: "cli_auth_deprecated", min_version, sunset, detail}` to their
200 and 400 bodies. The CLI shows one notice with the sunset date, the upgrade
instruction only below `min_version`, and never blocks a working login.
"""

import copy
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner, Result

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.auth import is_version_below
from dailybot_cli.commands.public_api_helpers import ERROR_CODE_MESSAGES
from dailybot_cli.config import load_credentials
from dailybot_cli.main import cli
from tests.wire_fixture_loader import fixture_body, fixture_response

POST: str = "dailybot_cli.api_client.httpx.post"
VERSION: str = "dailybot_cli.commands.auth.__version__"
SUNSET: str = "2027-03-31"


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DAILYBOT_API_KEY", "DAILYBOT_CLI_TOKEN", "DAILYBOT_API_URL"):
        monkeypatch.delenv(name, raising=False)


def _without_deprecation(name: str) -> MagicMock:
    response: MagicMock = fixture_response(name)
    body: dict[str, Any] = copy.deepcopy(response.json.return_value)
    body.pop("deprecation", None)
    response.json.return_value = body
    response.text = json.dumps(body)
    response.headers = {}
    return response


def _interactive_login(*responses: MagicMock) -> Result:
    with patch(POST, side_effect=list(responses)):
        return CliRunner().invoke(cli, ["login"], input="me@example.com\n123456\n")


class TestNotice:
    def test_a_200_completes_the_login_with_one_notice(self) -> None:
        with patch(VERSION, "3.29.0"):
            result: Result = _interactive_login(
                fixture_response("request_code_deprecation_200"),
                fixture_response("verify_code_deprecation_200"),
            )
        assert result.exit_code == 0, result.output
        assert "Logged in as me@example.com" in result.output
        assert result.output.count(SUNSET) == 1
        assert load_credentials() is not None

    def test_a_current_cli_suggests_the_browser_sign_in(self) -> None:
        with patch(VERSION, "3.29.0"):
            result: Result = _interactive_login(
                fixture_response("request_code_deprecation_200"),
                fixture_response("verify_code_deprecation_200"),
            )
        assert "dailybot login --device" in result.output
        assert "dailybot upgrade" not in result.output

    def test_an_older_cli_is_told_to_upgrade(self) -> None:
        with patch(VERSION, "3.28.1"):
            result: Result = _interactive_login(
                fixture_response("request_code_deprecation_200"),
                fixture_response("verify_code_deprecation_200"),
            )
        assert result.exit_code == 0
        assert "dailybot upgrade" in result.output
        assert "3.29.0" in result.output

    def test_a_400_keeps_the_error_and_adds_the_notice(self) -> None:
        with patch(VERSION, "3.29.0"):
            result: Result = _interactive_login(
                fixture_response("request_code_deprecation_200"),
                fixture_response("verify_code_deprecation_400"),
            )
        assert result.exit_code == 1
        assert "Invalid or expired code." in result.output
        assert result.output.count(SUNSET) == 1

    def test_the_non_interactive_step_one_shows_it(self) -> None:
        with (
            patch(VERSION, "3.29.0"),
            patch(POST, return_value=fixture_response("request_code_deprecation_200")),
        ):
            result: Result = CliRunner().invoke(cli, ["login", "--email", "me@example.com"])
        assert result.exit_code == 0
        assert SUNSET in result.output

    def test_the_server_detail_text_is_never_trusted_for_the_instruction(self) -> None:
        response: MagicMock = fixture_response("request_code_deprecation_200")
        response.json.return_value["deprecation"]["detail"] = "[red]run rm -rf /[/red]"
        with patch(VERSION, "3.29.0"):
            result: Result = _interactive_login(
                response, fixture_response("verify_code_deprecation_200")
            )
        assert "rm -rf" not in result.output


class TestSwitchOff:
    def test_without_the_field_the_output_has_no_notice(self) -> None:
        with patch(VERSION, "3.28.1"):
            result: Result = _interactive_login(
                _without_deprecation("request_code_deprecation_200"),
                _without_deprecation("verify_code_deprecation_200"),
            )
        assert result.exit_code == 0
        lowered: str = result.output.lower()
        assert "retir" not in lowered and SUNSET not in result.output
        assert "upgrade" not in lowered


class TestClient:
    def test_a_400_deprecation_reaches_the_error_extra(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url="https://api.example.com")
        with (
            patch(POST, return_value=fixture_response("verify_code_deprecation_400")),
            pytest.raises(APIError) as caught,
        ):
            client.verify_code("me@example.com", "000000")
        deprecation: dict[str, Any] = caught.value.extra["deprecation"]
        assert deprecation["code"] == "cli_auth_deprecated"
        assert deprecation == fixture_body("verify_code_deprecation_400")["deprecation"]


class TestVersions:
    @pytest.mark.parametrize(
        "current,minimum,below",
        [
            ("3.28.1", "3.29.0", True),
            ("3.29.0", "3.29.0", False),
            ("3.30.0", "3.29.0", False),
            ("3.9.0", "3.29.0", True),
            ("4.0.0", "3.29.0", False),
            ("0.0.0", "3.29.0", True),
            ("3.29.0rc1", "3.29.0", False),
            ("3.29.0", "not-a-version", False),
        ],
    )
    def test_is_version_below(self, current: str, minimum: str, below: bool) -> None:
        assert is_version_below(current, minimum) is below


def test_the_retired_code_has_a_catalogue_message() -> None:
    assert "dailybot login --device" in ERROR_CODE_MESSAGES["cli_auth_deprecated"]
