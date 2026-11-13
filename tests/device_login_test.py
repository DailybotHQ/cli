"""`dailybot login --device`: the RFC 8628 browser sign-in (PLAN_002 T-device-login).

HTTP is mocked at the call site with the recorded fixtures, so the real
DailyBotClient builds every request. Sleeping is patched out.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner, Result

from dailybot_cli.commands import _device_login
from dailybot_cli.config import get_org_plan, load_credentials
from dailybot_cli.main import cli
from tests.wire_fixture_loader import fixture_body, fixture_response

POST: str = "dailybot_cli.api_client.httpx.post"
SLEEP: str = "dailybot_cli.commands._device_login.time.sleep"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def sleeps() -> Any:
    with patch(SLEEP) as sleep:
        yield sleep


def _login(runner: CliRunner, *args: str, input: str | None = None) -> Result:
    return runner.invoke(cli, ["login", "--device", *args], input=input)


def _credentials_file(config_dir: Path) -> Path:
    return config_dir / "credentials.json"


class TestHappyPath:
    def test_prints_the_link_and_code_then_saves_the_pair(
        self, runner: CliRunner, sleeps: MagicMock, _isolated_environment: Path
    ) -> None:
        responses: list[MagicMock] = [
            fixture_response("device_start_200"),
            fixture_response("device_token_success_200"),
        ]
        with patch(POST, side_effect=responses):
            result: Result = _login(runner)
        assert result.exit_code == 0, result.output
        start: dict[str, Any] = fixture_body("device_start_200")
        assert start["verification_uri_complete"] in result.output
        assert start["user_code"] in result.output
        assert "Logged in as me@example.com (My Team)" in result.output

        creds: dict[str, Any] | None = load_credentials()
        token: dict[str, Any] = fixture_body("device_token_success_200")
        assert creds is not None
        assert creds["token"] == token["access"]
        assert creds["refresh"] == token["refresh"]
        assert creds["expires_at"] == token["expires_at"]
        assert creds["refresh_expires_at"] == token["refresh_expires_at"]
        assert creds["auth_method"] == "device"
        assert creds["email"] == "me@example.com"
        assert creds["organization"] == "My Team"
        assert creds["organization_uuid"] == token["organization"]["uuid"]

    def test_caches_the_effective_tier(self, runner: CliRunner, sleeps: MagicMock) -> None:
        with patch(
            POST,
            side_effect=[
                fixture_response("device_start_200"),
                fixture_response("device_token_success_200"),
            ],
        ):
            _login(runner)
        org: dict[str, Any] = fixture_body("device_token_success_200")["organization"]
        assert get_org_plan(org["uuid"]) == org["plan"]["effective_tier"] == "startup"

    def test_the_tokens_never_reach_the_output(self, runner: CliRunner, sleeps: MagicMock) -> None:
        with patch(
            POST,
            side_effect=[
                fixture_response("device_start_200"),
                fixture_response("device_token_success_200"),
            ],
        ):
            result: Result = _login(runner)
        token: dict[str, Any] = fixture_body("device_token_success_200")
        assert token["access"] not in result.output
        assert token["refresh"] not in result.output
        assert fixture_body("device_start_200")["device_code"] not in result.output


class TestPolling:
    def test_pending_then_success_waits_the_server_interval(
        self, runner: CliRunner, sleeps: MagicMock
    ) -> None:
        with patch(
            POST,
            side_effect=[
                fixture_response("device_start_200"),
                fixture_response("device_token_authorization_pending_400"),
                fixture_response("device_token_authorization_pending_400"),
                fixture_response("device_token_success_200"),
            ],
        ) as post:
            result: Result = _login(runner)
        assert result.exit_code == 0, result.output
        assert post.call_count == 4
        assert [c.args[0] for c in sleeps.call_args_list] == [5, 5, 5]

    def test_slow_down_adopts_the_body_interval(self, runner: CliRunner, sleeps: MagicMock) -> None:
        with patch(
            POST,
            side_effect=[
                fixture_response("device_start_200"),
                fixture_response("device_token_slow_down_400"),
                fixture_response("device_token_authorization_pending_400"),
                fixture_response("device_token_success_200"),
            ],
        ):
            result: Result = _login(runner)
        assert result.exit_code == 0, result.output
        assert [c.args[0] for c in sleeps.call_args_list] == [5, 10, 10]

    def test_slow_down_without_an_interval_adds_five_and_caps_at_thirty(self) -> None:
        assert _device_login.next_interval(5, None) == 10
        assert _device_login.next_interval(28, None) == 30
        assert _device_login.next_interval(5, 120) == 30
        assert _device_login.next_interval(5, 0) == 10

    def test_a_transport_failure_keeps_polling(self, runner: CliRunner, sleeps: MagicMock) -> None:
        import httpx

        with patch(
            POST,
            side_effect=[
                fixture_response("device_start_200"),
                httpx.ConnectError("offline"),
                fixture_response("device_token_success_200"),
            ],
        ):
            result: Result = _login(runner)
        assert result.exit_code == 0, result.output
        assert load_credentials() is not None

    def test_the_local_deadline_stops_a_silent_server(
        self, runner: CliRunner, sleeps: MagicMock
    ) -> None:
        clock: list[float] = [0.0]

        def tick(seconds: float) -> None:
            clock[0] += seconds

        sleeps.side_effect = tick
        pending: list[MagicMock] = [
            fixture_response("device_token_authorization_pending_400") for _ in range(200)
        ]
        with (
            patch(
                "dailybot_cli.commands._device_login.time.monotonic", side_effect=lambda: clock[0]
            ),
            patch(POST, side_effect=[fixture_response("device_start_200"), *pending]),
        ):
            result: Result = _login(runner)
        assert result.exit_code == 1
        assert "expired" in result.output.lower()
        assert clock[0] <= 600 + 5
        assert load_credentials() is None


class TestTerminalStates:
    @pytest.mark.parametrize(
        "code,phrase",
        [
            ("access_denied", "denied"),
            ("expired_token", "expired"),
            ("invalid_grant", "no longer valid"),
            ("invalid_client", "update the dailybot cli"),
        ],
    )
    def test_each_stops_without_writing_credentials(
        self, runner: CliRunner, sleeps: MagicMock, code: str, phrase: str
    ) -> None:
        with patch(
            POST,
            side_effect=[
                fixture_response("device_start_200"),
                fixture_response(f"device_token_{code}_400"),
            ],
        ) as post:
            result: Result = _login(runner)
        assert result.exit_code == 1
        assert phrase in result.output.lower()
        assert post.call_count == 2
        assert load_credentials() is None

    def test_ctrl_c_aborts_without_writing_credentials(
        self, runner: CliRunner, sleeps: MagicMock
    ) -> None:
        sleeps.side_effect = KeyboardInterrupt
        with patch(POST, side_effect=[fixture_response("device_start_200")]):
            result: Result = _login(runner)
        assert result.exit_code != 0
        assert load_credentials() is None


class TestOldServerFallback:
    @pytest.mark.parametrize(
        "name", ["device_start_not_found_404", "device_start_method_not_allowed_405"]
    )
    def test_falls_back_to_the_email_code(
        self, runner: CliRunner, sleeps: MagicMock, name: str
    ) -> None:
        with patch(
            POST,
            side_effect=[
                fixture_response(name),
                fixture_response("request_code_deprecation_200"),
                fixture_response("verify_code_legacy_200"),
            ],
        ) as post:
            result: Result = _login(runner, input="me@example.com\n123456\n")
        assert result.exit_code == 0, result.output
        assert "email" in result.output.lower()
        urls: list[str] = [c.args[0] for c in post.call_args_list]
        assert urls[0].endswith("/v1/cli/auth/device/")
        assert urls[1].endswith("/v1/cli/auth/request-code/")
        assert urls[2].endswith("/v1/cli/auth/verify-code/")
        creds: dict[str, Any] | None = load_credentials()
        assert creds is not None
        assert creds["token"] == "legacy-test-token"
        assert "auth_method" not in creds

    def test_a_server_error_on_start_is_not_a_fallback(
        self, runner: CliRunner, sleeps: MagicMock
    ) -> None:
        with patch(POST, side_effect=[fixture_response("device_start_invalid_client_400")]) as post:
            result: Result = _login(runner)
        assert result.exit_code == 1
        assert post.call_count == 1


class TestFlags:
    def test_device_with_code_is_a_usage_error(self, runner: CliRunner) -> None:
        result: Result = runner.invoke(cli, ["login", "--device", "--code", "123456"])
        assert result.exit_code == 2

    def test_device_login_is_opt_in_until_the_api_doors_are_live(self) -> None:
        # Hand-off T31: the device flow stays opt-in. Flipping this constant makes a
        # bare `dailybot login` start the browser flow (with the 404/405 fallback).
        assert _device_login.DEVICE_LOGIN_IS_DEFAULT is False

    def test_bare_login_keeps_the_email_code_by_default(
        self, runner: CliRunner, sleeps: MagicMock
    ) -> None:
        with patch(
            POST,
            side_effect=[
                fixture_response("request_code_deprecation_200"),
                fixture_response("verify_code_legacy_200"),
            ],
        ) as post:
            result: Result = runner.invoke(cli, ["login"], input="me@example.com\n123456\n")
        assert result.exit_code == 0, result.output
        assert post.call_args_list[0].args[0].endswith("/v1/cli/auth/request-code/")

    def test_when_the_default_flips_a_bare_login_uses_the_browser(
        self, runner: CliRunner, sleeps: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_device_login, "DEVICE_LOGIN_IS_DEFAULT", True)
        with patch(
            POST,
            side_effect=[
                fixture_response("device_start_200"),
                fixture_response("device_token_success_200"),
            ],
        ) as post:
            result: Result = runner.invoke(cli, ["login"])
        assert result.exit_code == 0, result.output
        assert post.call_args_list[0].args[0].endswith("/v1/cli/auth/device/")

    def test_when_the_default_flips_an_explicit_email_keeps_the_code_path(
        self, runner: CliRunner, sleeps: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_device_login, "DEVICE_LOGIN_IS_DEFAULT", True)
        with patch(POST, side_effect=[fixture_response("request_code_deprecation_200")]) as post:
            result: Result = runner.invoke(cli, ["login", "--email", "me@example.com"])
        assert result.exit_code == 0, result.output
        assert post.call_args_list[0].args[0].endswith("/v1/cli/auth/request-code/")


def test_a_legacy_login_still_writes_exactly_the_legacy_keys(
    runner: CliRunner, _isolated_environment: Path
) -> None:
    with patch(POST, side_effect=[fixture_response("verify_code_legacy_200")]):
        result: Result = runner.invoke(
            cli, ["login", "--email", "me@example.com", "--code", "123456"]
        )
    assert result.exit_code == 0, result.output
    raw: dict[str, Any] = json.loads(_credentials_file(_isolated_environment).read_text())
    assert set(raw) == {"token", "email", "organization", "organization_uuid", "api_url"}
