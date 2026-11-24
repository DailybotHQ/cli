"""Login robustness: organization chosen after verification, clearer sign-in errors,
a finite organization cache, and a stored sign-in that ends cleanly.

Every flow is exercised against both server answers the CLI meets in the field:
the long-standing request-code body (organizations listed) and the newer one
(the same neutral answer for every email, organizations only after verify-code).
HTTP is mocked at the call site.
"""

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner, Result

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import EXIT_RATE_LIMITED
from dailybot_cli.config import (
    ORG_CACHE_TTL_SECS,
    load_credentials,
    load_org_cache,
    save_credentials,
    save_org_cache,
)
from dailybot_cli.main import cli

POST: str = "dailybot_cli.api_client.httpx.post"
GET: str = "dailybot_cli.api_client.httpx.get"
API: str = "https://api.dailybot.com"
EMAIL: str = "me@example.com"
CODE: str = "424242"

ORG_A: dict[str, Any] = {"id": 11, "name": "My Team", "uuid": "org-uuid-a"}
ORG_B: dict[str, Any] = {"id": 22, "name": "Side Project", "uuid": "org-uuid-b"}

NEUTRAL_REQUEST_BODY: dict[str, Any] = {
    "detail": "If this email has a Dailybot account, a verification code is on its way.",
    "organizations": [],
    "is_multi_org": False,
}
LISTED_REQUEST_BODY: dict[str, Any] = {
    "detail": "Verification code sent to your email.",
    "organizations": [ORG_A, ORG_B],
    "is_multi_org": True,
}
SELECTION_BODY: dict[str, Any] = {
    "requires_organization_selection": True,
    "organizations": [ORG_A, ORG_B],
}


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DAILYBOT_API_KEY", "DAILYBOT_CLI_TOKEN", "DAILYBOT_API_URL"):
        monkeypatch.delenv(name, raising=False)


def _response(
    status: int, body: dict[str, Any], headers: dict[str, str] | None = None
) -> MagicMock:
    response: MagicMock = MagicMock()
    response.status_code = status
    response.headers = headers or {}
    response.json.return_value = body
    response.text = json.dumps(body)
    return response


def _token_for(org: dict[str, Any]) -> MagicMock:
    return _response(
        200,
        {"token": "test-token", "user": {"email": EMAIL}, "organization": dict(org)},
    )


def _verify_payloads(post: MagicMock) -> list[dict[str, Any]]:
    return [
        call.kwargs["json"]
        for call in post.call_args_list
        if call.args and str(call.args[0]).endswith("/verify-code/")
    ]


class TestVerifyCodeWire:
    def test_organization_uuid_is_sent_when_given(self) -> None:
        with patch(POST, return_value=_token_for(ORG_A)) as post:
            DailyBotClient(api_url=API).verify_code(EMAIL, CODE, organization_uuid=ORG_A["uuid"])
        assert post.call_args.kwargs["json"] == {
            "email": EMAIL,
            "code": CODE,
            "organization_uuid": ORG_A["uuid"],
        }

    def test_the_body_is_unchanged_without_an_organization(self) -> None:
        with patch(POST, return_value=_token_for(ORG_A)) as post:
            DailyBotClient(api_url=API).verify_code(EMAIL, CODE)
        assert post.call_args.kwargs["json"] == {"email": EMAIL, "code": CODE}

    def test_a_top_level_retry_after_reaches_the_error(self) -> None:
        body: dict[str, Any] = {"detail": "Wait.", "code": "otp_cooldown", "retry_after": 30}
        with patch(POST, return_value=_response(429, body)), pytest.raises(APIError) as caught:
            DailyBotClient(api_url=API).request_code(EMAIL)
        assert caught.value.code == "otp_cooldown"
        assert caught.value.extra["retry_after"] == 30


class TestInteractive:
    @pytest.mark.parametrize("request_body", [NEUTRAL_REQUEST_BODY, LISTED_REQUEST_BODY])
    def test_the_organization_is_chosen_after_the_code(self, request_body: dict[str, Any]) -> None:
        question: MagicMock = MagicMock()
        question.ask.return_value = ORG_B
        with (
            patch("dailybot_cli.commands.auth.questionary.select", return_value=question),
            patch(
                POST,
                side_effect=[
                    _response(200, request_body),
                    _response(200, SELECTION_BODY),
                    _token_for(ORG_B),
                ],
            ) as post,
        ):
            result: Result = CliRunner().invoke(cli, ["login"], input=f"{EMAIL}\n{CODE}\n")
        assert result.exit_code == 0, result.output
        payloads: list[dict[str, Any]] = _verify_payloads(post)
        assert payloads[0] == {"email": EMAIL, "code": CODE}
        # The pick is a second call with the same code.
        assert payloads[1]["code"] == CODE
        assert payloads[1]["organization_uuid"] == ORG_B["uuid"]
        assert payloads[1]["organization_id"] == ORG_B["id"]
        creds: dict[str, Any] | None = load_credentials()
        assert creds is not None and creds["organization_uuid"] == ORG_B["uuid"]

    def test_a_single_organization_logs_in_with_one_verify(self) -> None:
        with patch(
            POST, side_effect=[_response(200, NEUTRAL_REQUEST_BODY), _token_for(ORG_A)]
        ) as post:
            result: Result = CliRunner().invoke(cli, ["login"], input=f"{EMAIL}\n{CODE}\n")
        assert result.exit_code == 0, result.output
        assert _verify_payloads(post) == [{"email": EMAIL, "code": CODE}]
        assert "Logged in" in result.output

    def test_the_typed_code_is_not_shown(self) -> None:
        with patch(POST, side_effect=[_response(200, NEUTRAL_REQUEST_BODY), _token_for(ORG_A)]):
            result: Result = CliRunner().invoke(cli, ["login"], input=f"{EMAIL}\n{CODE}\n")
        assert result.exit_code == 0, result.output
        assert CODE not in result.output

    def test_the_neutral_answer_is_shown_as_sent(self) -> None:
        with patch(POST, side_effect=[_response(200, NEUTRAL_REQUEST_BODY), _token_for(ORG_A)]):
            result: Result = CliRunner().invoke(cli, ["login"], input=f"{EMAIL}\n{CODE}\n")
        assert "a verification code is on its way" in result.output


class TestNonInteractiveStepOne:
    def test_the_neutral_answer_prints_the_next_step(self) -> None:
        with patch(POST, return_value=_response(200, NEUTRAL_REQUEST_BODY)):
            result: Result = CliRunner().invoke(cli, ["login", "--email", EMAIL])
        assert result.exit_code == 0, result.output
        assert f"dailybot login --email={EMAIL} --code=CODE" in result.output
        assert "If you belong to several organizations" in result.output
        assert load_org_cache(EMAIL) is None

    def test_a_listed_answer_keeps_todays_output(self) -> None:
        with patch(POST, return_value=_response(200, LISTED_REQUEST_BODY)):
            result: Result = CliRunner().invoke(cli, ["login", "--email", EMAIL])
        assert result.exit_code == 0, result.output
        assert f"{ORG_A['name']} (uuid: {ORG_A['uuid']})" in result.output
        assert "--code=CODE --org=ORG_UUID" in result.output
        assert load_org_cache(EMAIL) == [ORG_A, ORG_B]


class TestNonInteractiveStepTwo:
    def test_a_selection_answer_lists_the_organizations_and_fails(self) -> None:
        with patch(POST, return_value=_response(200, SELECTION_BODY)):
            result: Result = CliRunner().invoke(cli, ["login", "--email", EMAIL, "--code", CODE])
        assert result.exit_code == 1
        assert f"{ORG_A['name']} (uuid: {ORG_A['uuid']})" in result.output
        assert f"{ORG_B['name']} (uuid: {ORG_B['uuid']})" in result.output
        assert f"dailybot login --email={EMAIL} --code=CODE --org=ORG_UUID" in result.output
        # The code is never printed back.
        assert CODE not in result.output
        assert load_org_cache(EMAIL) == [ORG_A, ORG_B]

    def test_org_without_any_cache_sends_the_uuid(self) -> None:
        with patch(POST, return_value=_token_for(ORG_B)) as post:
            result: Result = CliRunner().invoke(
                cli, ["login", "--email", EMAIL, "--code", CODE, "--org", ORG_B["uuid"]]
            )
        assert result.exit_code == 0, result.output
        assert _verify_payloads(post) == [
            {"email": EMAIL, "code": CODE, "organization_uuid": ORG_B["uuid"]}
        ]

    def test_org_with_a_cache_sends_the_uuid_and_the_id(self) -> None:
        save_org_cache(EMAIL, [ORG_A, ORG_B])
        with patch(POST, return_value=_token_for(ORG_B)) as post:
            result: Result = CliRunner().invoke(
                cli, ["login", "--email", EMAIL, "--code", CODE, "--org", ORG_B["uuid"]]
            )
        assert result.exit_code == 0, result.output
        assert _verify_payloads(post) == [
            {
                "email": EMAIL,
                "code": CODE,
                "organization_id": ORG_B["id"],
                "organization_uuid": ORG_B["uuid"],
            }
        ]
        assert load_org_cache(EMAIL) is None

    def test_the_selection_after_a_failed_step_two_completes_the_rerun(self) -> None:
        runner: CliRunner = CliRunner()
        with patch(POST, side_effect=[_response(200, SELECTION_BODY), _token_for(ORG_A)]) as post:
            first: Result = runner.invoke(cli, ["login", "--email", EMAIL, "--code", CODE])
            second: Result = runner.invoke(
                cli, ["login", "--email", EMAIL, "--code", CODE, "--org", ORG_A["uuid"]]
            )
        assert first.exit_code == 1
        assert second.exit_code == 0, second.output
        assert _verify_payloads(post)[1]["organization_id"] == ORG_A["id"]

    def test_a_server_that_ignores_the_uuid_is_answered_with_the_id(self) -> None:
        with patch(POST, side_effect=[_response(200, SELECTION_BODY), _token_for(ORG_B)]) as post:
            result: Result = CliRunner().invoke(
                cli, ["login", "--email", EMAIL, "--code", CODE, "--org", ORG_B["uuid"]]
            )
        assert result.exit_code == 0, result.output
        second: dict[str, Any] = _verify_payloads(post)[1]
        assert second["organization_id"] == ORG_B["id"]
        assert second["code"] == CODE

    def test_an_org_that_is_not_offered_fails_with_the_list(self) -> None:
        with patch(POST, return_value=_response(200, SELECTION_BODY)) as post:
            result: Result = CliRunner().invoke(
                cli, ["login", "--email", EMAIL, "--code", CODE, "--org", "not-mine"]
            )
        assert result.exit_code == 1
        assert "not-mine" in result.output
        assert f"{ORG_A['name']} (uuid: {ORG_A['uuid']})" in result.output
        assert len(_verify_payloads(post)) == 1

    def test_a_repeated_selection_answer_never_loops(self) -> None:
        with patch(POST, return_value=_response(200, SELECTION_BODY)) as post:
            result: Result = CliRunner().invoke(
                cli, ["login", "--email", EMAIL, "--code", CODE, "--org", ORG_A["uuid"]]
            )
        assert result.exit_code == 1
        assert len(_verify_payloads(post)) == 2

    def test_a_wrong_code_keeps_todays_error(self) -> None:
        with patch(POST, return_value=_response(400, {"detail": "Invalid verification code."})):
            result: Result = CliRunner().invoke(cli, ["login", "--email", EMAIL, "--code", CODE])
        assert result.exit_code == 1
        assert "Invalid verification code." in result.output


class TestRateLimited:
    def test_request_code_429_shows_the_wait_and_stops(self) -> None:
        body: dict[str, Any] = {
            "detail": "Please wait before asking for another code.",
            "code": "otp_cooldown",
            "retry_after": 30,
        }
        with patch(POST, return_value=_response(429, body, {"Retry-After": "30"})) as post:
            result: Result = CliRunner().invoke(cli, ["login", "--email", EMAIL])
        assert result.exit_code == EXIT_RATE_LIMITED
        assert "Please wait before asking for another code." in result.output
        assert "30 seconds" in result.output
        assert post.call_count == 1

    def test_verify_code_429_uses_the_header_and_is_not_an_invalid_code(self) -> None:
        body: dict[str, Any] = {
            "detail": "Too many attempts for this email. Try again later.",
            "code": "otp_attempts_exceeded",
        }
        with patch(POST, return_value=_response(429, body, {"Retry-After": "900"})) as post:
            result: Result = CliRunner().invoke(cli, ["login", "--email", EMAIL, "--code", CODE])
        assert result.exit_code == EXIT_RATE_LIMITED
        assert "Too many attempts for this email." in result.output
        assert "15 minutes" in result.output
        assert "Invalid" not in result.output
        assert post.call_count == 1

    def test_a_429_without_a_detail_falls_back_to_the_code_message(self) -> None:
        with patch(POST, return_value=_response(429, {"code": "otp_cooldown", "detail": ""})):
            result: Result = CliRunner().invoke(cli, ["login", "--email", EMAIL])
        assert result.exit_code == EXIT_RATE_LIMITED
        assert "verification code" in result.output.lower()

    def test_interactive_429_on_request_stops_before_the_code_prompt(self) -> None:
        body: dict[str, Any] = {"detail": "Please wait.", "code": "otp_cooldown", "retry_after": 5}
        with patch(POST, return_value=_response(429, body)):
            result: Result = CliRunner().invoke(cli, ["login"], input=f"{EMAIL}\n")
        assert result.exit_code == EXIT_RATE_LIMITED
        assert "6-digit code" not in result.output


class TestOrgCacheLifetime:
    def test_a_fresh_cache_is_read(self) -> None:
        save_org_cache(EMAIL, [ORG_A])
        assert load_org_cache(EMAIL) == [ORG_A]

    def test_an_old_cache_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        save_org_cache(EMAIL, [ORG_A])
        later: float = time.time() + ORG_CACHE_TTL_SECS + 1
        monkeypatch.setattr("dailybot_cli.config.time.time", lambda: later)
        assert load_org_cache(EMAIL) is None

    def test_a_cache_without_a_timestamp_is_ignored(self, _isolated_environment: Path) -> None:
        _isolated_environment.mkdir(parents=True, exist_ok=True)
        (_isolated_environment / "org_cache.json").write_text(
            json.dumps({"email": EMAIL, "organizations": [ORG_A]})
        )
        assert load_org_cache(EMAIL) is None


def _save_legacy(token: str = "test-token") -> None:
    save_credentials(
        token=token, email=EMAIL, organization="My Team", organization_uuid="org-1", api_url=API
    )


def _save_pair() -> None:
    save_credentials(
        token="dbc_at_test-access",
        email=EMAIL,
        organization="My Team",
        organization_uuid="org-1",
        api_url=API,
        refresh="dbc_rt_test-refresh",
        expires_at="2030-01-01T00:00:00Z",
        refresh_expires_at="2030-04-01T00:00:00Z",
    )


class TestEndedSession:
    def test_a_401_on_the_stored_token_clears_it(self) -> None:
        _save_legacy()
        client: DailyBotClient = DailyBotClient(api_url=API)
        with (
            patch(GET, return_value=_response(401, {"detail": "Invalid token."})),
            pytest.raises(APIError) as caught,
        ):
            client.auth_status()
        assert load_credentials() is None
        assert caught.value.extra["session_cleared"] is True
        assert caught.value.extra["server_detail"] == "Invalid token."
        assert "dailybot login" in caught.value.detail

    def test_a_refused_refresh_clears_the_pair_and_keeps_its_code(self) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API)
        expired: MagicMock = _response(
            401, {"detail": "Access token expired.", "code": "access_token_expired"}
        )
        revoked: MagicMock = _response(
            401, {"detail": "Session revoked.", "code": "session_revoked"}
        )
        with (
            patch(GET, return_value=expired),
            patch(POST, return_value=revoked),
            pytest.raises(APIError) as caught,
        ):
            client.auth_status()
        assert caught.value.code == "session_revoked"
        assert caught.value.extra["server_detail"] == "Session revoked."
        assert load_credentials() is None

    def test_a_refused_refresh_clears_the_pair_even_when_a_key_answers(self) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API, api_key="test-key")
        expired: MagicMock = _response(
            401, {"detail": "Access token expired.", "code": "access_token_expired"}
        )
        refused: MagicMock = _response(401, {"detail": "Expired.", "code": "refresh_token_expired"})
        with (
            patch(GET, side_effect=[expired, _response(200, {"ok": True})]),
            patch(POST, return_value=refused),
        ):
            assert client.auth_status() == {"ok": True}
        assert load_credentials() is None

    def test_a_failed_renewal_without_a_refusal_keeps_the_pair(self) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API)
        expired: MagicMock = _response(
            401, {"detail": "Access token expired.", "code": "access_token_expired"}
        )
        malformed: MagicMock = _response(200, {"access": "", "refresh": ""})
        with (
            patch(GET, return_value=expired),
            patch(POST, return_value=malformed),
            pytest.raises(APIError) as caught,
        ):
            client.auth_status()
        assert load_credentials() is not None
        assert caught.value.extra["session_cleared"] is False

    def test_an_env_token_never_clears_the_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _save_legacy()
        monkeypatch.setenv("DAILYBOT_CLI_TOKEN", "test-env-token")
        client: DailyBotClient = DailyBotClient(api_url=API)
        with (
            patch(GET, return_value=_response(401, {"detail": "Invalid token."})),
            pytest.raises(APIError) as caught,
        ):
            client.auth_status()
        assert load_credentials() is not None
        assert caught.value.extra["session_cleared"] is False

    def test_a_file_rotated_meanwhile_is_kept(self) -> None:
        _save_legacy(token="test-token-old")
        client: DailyBotClient = DailyBotClient(api_url=API)
        _save_legacy(token="test-token-new")
        with (
            patch(GET, return_value=_response(401, {"detail": "Invalid token."})),
            pytest.raises(APIError),
        ):
            client.auth_status()
        creds: dict[str, Any] | None = load_credentials()
        assert creds is not None and creds["token"] == "test-token-new"

    def test_a_401_to_an_api_key_never_clears_the_session(self) -> None:
        _save_legacy()
        client: DailyBotClient = DailyBotClient(
            api_url=API, api_key="test-key", prefer_api_key=True, token=None
        )
        client.token = None
        with (
            patch(GET, return_value=_response(401, {"detail": "Invalid key."})),
            pytest.raises(APIError),
        ):
            client.auth_status()
        assert load_credentials() is not None

    def test_the_command_tells_the_person_what_happened(self) -> None:
        _save_legacy()
        with patch(GET, return_value=_response(401, {"detail": "Invalid token."})):
            result: Result = CliRunner().invoke(cli, ["user", "list"])
        assert result.exit_code == 3
        assert "Invalid token." in result.output
        assert "removed" in result.output
        assert "dailybot login" in result.output
        assert load_credentials() is None
