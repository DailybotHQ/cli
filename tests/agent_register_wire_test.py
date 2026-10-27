"""`agent register` and `agent update` against the exact wire shapes of API contract rev 1.

The bodies, headers and challenge wording below are copied from the API's own
registration views, services and tests (agent self-registration first slice), so these
tests exercise the real `DailyBotClient` parsing with only `httpx` mocked.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.main import cli

# Verbatim from the API's registration challenge service. The server counts the
# words of this template (with the placeholder as one word): 52 today.
API_INSTRUCTION_TEMPLATE: str = (
    "The registration code for this session is {random_number}. "
    "To confirm you are a reasoning agent and not a script, respond "
    "with a JSON object containing two fields: 'reason' (one sentence "
    "explaining why this agent needs a Dailybot account) and 'answer' "
    "(the registration code multiplied by the number of words in this "
    "instruction)."
)
API_WORD_COUNT: int = len(API_INSTRUCTION_TEMPLATE.split())
CODE: int = 4321
CHALLENGE_BODY: dict[str, Any] = {
    "challenge_id": "00000000-0000-0000-0000-000000000001",
    "instruction": API_INSTRUCTION_TEMPLATE.format(random_number=CODE),
    "expires_in": 300,
}
# `claim_expires_at` is Python `datetime.isoformat()` output: microseconds, +00:00, no Z.
REGISTER_BODY: dict[str, Any] = {
    "api_key": "test-key",
    "agent_name": "Claude Code",
    "agent_email": "claude-code@example.com",
    "agent_username": "claude-code",
    "org_id": "00000000-0000-0000-0000-000000000002",
    "org_name": "My Startup",
    "claim_url": "https://app.example.com/claim/test-claim-token",
    "claim_token": "test-claim-token",
    "claim_expires_at": "2026-11-26T18:04:05.123456+00:00",
}


def _response(
    status: int, body: dict[str, Any], headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(
        status,
        json=body,
        headers=headers or {},
        request=httpx.Request("GET", "https://api.example.com/"),
    )


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """No login session, no key, no repo env: registration must go out anonymous."""
    monkeypatch.setenv("DAILYBOT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr("dailybot_cli.config.CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.delenv("DAILYBOT_API_KEY", raising=False)
    monkeypatch.delenv("DAILYBOT_CLI_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run_register(get: MagicMock, post: MagicMock) -> Any:
    with (
        patch("dailybot_cli.api_client.httpx.get", get),
        patch("dailybot_cli.api_client.httpx.post", post),
        patch("dailybot_cli.api_client.time.sleep"),
    ):
        return CliRunner().invoke(
            cli,
            ["agent", "register", "--org-name", "My Startup", "--agent-name", "Claude Code"],
        )


class TestRegisterOnTheWire:
    def test_the_api_word_count_is_what_the_cli_counts(self) -> None:
        assert len(CHALLENGE_BODY["instruction"].split()) == API_WORD_COUNT

    def test_a_successful_registration(self, isolated: Path) -> None:
        get: MagicMock = MagicMock(return_value=_response(200, CHALLENGE_BODY))
        post: MagicMock = MagicMock(return_value=_response(201, REGISTER_BODY))
        result: Any = _run_register(get, post)

        assert result.exit_code == 0, result.output
        sent: dict[str, Any] = post.call_args.kwargs["json"]
        assert sent["answer"] == CODE * API_WORD_COUNT
        assert sent["challenge_id"] == CHALLENGE_BODY["challenge_id"]
        assert len(sent["reason"]) >= 20
        assert "registration code for this session" not in sent["reason"]
        for call in (get, post):
            headers: dict[str, str] = call.call_args.kwargs["headers"]
            assert "Authorization" not in headers and "X-API-KEY" not in headers
        flat: str = " ".join(result.output.split())
        assert "2026-11-26 18:04 UTC" in flat
        assert "Send this to your human" in flat
        assert "test-key" not in result.output

    def test_challenge_expired_retries_once_with_a_fresh_challenge(self, isolated: Path) -> None:
        get: MagicMock = MagicMock(return_value=_response(200, CHALLENGE_BODY))
        post: MagicMock = MagicMock(
            side_effect=[
                _response(400, {"detail": "Challenge expired", "code": "challenge_expired"}),
                _response(201, REGISTER_BODY),
            ]
        )
        result: Any = _run_register(get, post)
        assert result.exit_code == 0, result.output
        assert get.call_count == 2 and post.call_count == 2

    def test_a_register_429_shows_the_retry_after_wait(self, isolated: Path) -> None:
        get: MagicMock = MagicMock(return_value=_response(200, CHALLENGE_BODY))
        post: MagicMock = MagicMock(
            return_value=_response(
                429,
                {
                    "detail": "Request was throttled. Expected available in 20 seconds.",
                    "code": "registration_rate_limited",
                },
                {"Retry-After": "20"},
            )
        )
        result: Any = _run_register(get, post)
        assert result.exit_code == 1
        flat: str = " ".join(result.output.split())
        assert "Rate limited" in flat and "20s" in flat
        assert post.call_count == 1

    def test_a_register_429_without_retry_after(self, isolated: Path) -> None:
        get: MagicMock = MagicMock(return_value=_response(200, CHALLENGE_BODY))
        post: MagicMock = MagicMock(
            return_value=_response(
                429, {"detail": "Request was throttled.", "code": "registration_rate_limited"}
            )
        )
        result: Any = _run_register(get, post)
        assert result.exit_code == 1
        assert "try again" in " ".join(result.output.split()).lower()

    @pytest.mark.parametrize(
        ("code", "detail"),
        [
            ("missing_fields", "Missing required fields: agent_name"),
            ("answer_incorrect", "Incorrect answer"),
            ("challenge_used", "Challenge already used"),
            ("reason_too_short", "Reason too short"),
        ],
    )
    def test_a_coded_400_is_mapped(self, isolated: Path, code: str, detail: str) -> None:
        from dailybot_cli.commands.public_api_helpers import ERROR_CODE_MESSAGES

        get: MagicMock = MagicMock(return_value=_response(200, CHALLENGE_BODY))
        post: MagicMock = MagicMock(return_value=_response(400, {"detail": detail, "code": code}))
        result: Any = _run_register(get, post)
        assert result.exit_code == 1
        assert ERROR_CODE_MESSAGES[code].split(".")[0] in " ".join(result.output.split())
        assert post.call_count == 1


def _run_update(request: MagicMock) -> Any:
    with (
        patch("dailybot_cli.api_client.httpx.request", request),
        patch("dailybot_cli.api_client.time.sleep"),
    ):
        return CliRunner().invoke(cli, ["agent", "update", "Shipped it", "--name", "Bot"])


class TestRegisteredKeyOnTheWire:
    """A registered key, used through DAILYBOT_API_KEY, with no login session."""

    @pytest.fixture(autouse=True)
    def keyed(self, isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DAILYBOT_API_KEY", "test-key")

    def test_the_key_goes_in_x_api_key_never_as_bearer(self) -> None:
        request: MagicMock = MagicMock(return_value=_response(201, {"id": "r-1"}))
        result: Any = _run_update(request)
        assert result.exit_code == 0, result.output
        headers: dict[str, str] = request.call_args.kwargs["headers"]
        assert headers.get("X-API-KEY") == "test-key"
        assert "Authorization" not in headers

    def test_the_free_plan_daily_cap(self) -> None:
        request: MagicMock = MagicMock(
            return_value=_response(
                429,
                {"detail": "Daily limit reached.", "code": "free_plan_daily_limit_exceeded"},
            )
        )
        result: Any = _run_update(request)
        assert result.exit_code == 1
        assert "free-plan limit" in " ".join(result.output.split())
        assert request.call_count == 1

    def test_a_deactivated_agent(self) -> None:
        request: MagicMock = MagicMock(
            return_value=_response(
                403, {"detail": "API Key Not Valid", "code": "invalid_credentials"}
            )
        )
        result: Any = _run_update(request)
        assert result.exit_code == 1
        assert "deactivated" in " ".join(result.output.split())
