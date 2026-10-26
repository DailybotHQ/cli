"""`dailybot agent register` against API contract rev 1 (agent self-registration, first slice).

The challenge is a compatibility speed bump, not a security control: the answer is the
session code times the number of words in the instruction. The CLI counts the words
instead of hardcoding today's count, so the server can vary the wording without
breaking new clients.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.agent import (
    _CHALLENGE_LEGACY_WORD_COUNT,
    _solve_challenge,
)
from dailybot_cli.main import cli

API_URL: str = "https://api.example.com"

# Today's server wording: 52 words.
TODAY_INSTRUCTION: str = (
    "The registration code for this session is 1234. To confirm you are a reasoning agent "
    "and not a script, respond with a JSON object containing two fields: 'reason' (one "
    "sentence explaining why this agent needs a DailyBot account) and 'answer' (the "
    "registration code multiplied by the number of words in this instruction)."
)
SHORT_INSTRUCTION: str = (
    "The registration code for this session is 77. Multiply it by the word count."
)

REGISTERED: dict[str, Any] = {
    "api_key": "test-key",
    "agent_name": "Claude Code",
    "agent_email": "claude-code@mail.example.com",
    "agent_username": "claude-code",
    "org_id": 1,
    "org_name": "My Startup",
    "claim_url": "https://app.example.com/claim/abc",
    "claim_token": "abc",
    "claim_expires_at": "2026-11-25T12:00:00Z",
}


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _challenge(instruction: str = TODAY_INSTRUCTION, cid: str = "ch-1") -> dict[str, Any]:
    return {"challenge_id": cid, "instruction": instruction, "expires_in": 300}


def _register(runner: CliRunner, client: MagicMock, *extra: str) -> Any:
    with (
        patch("dailybot_cli.commands.agent.DailyBotClient", return_value=client),
        patch("dailybot_cli.commands.agent.save_agent_profile") as save,
    ):
        result: Any = runner.invoke(
            cli,
            [
                "agent",
                "register",
                "--org-name",
                "My Startup",
                "--agent-name",
                "Claude Code",
                *extra,
            ],
        )
    result.save = save
    return result


def _client(**kwargs: Any) -> MagicMock:
    client: MagicMock = MagicMock(spec=DailyBotClient)
    client.get_registration_challenge.return_value = kwargs.pop("challenge", _challenge())
    for name, value in kwargs.items():
        setattr(
            getattr(client, name),
            "side_effect" if isinstance(value, list) else "return_value",
            value,
        )
    return client


class TestSolveChallenge:
    def test_todays_wording_still_gives_the_legacy_answer(self) -> None:
        assert len(TODAY_INSTRUCTION.split()) == _CHALLENGE_LEGACY_WORD_COUNT
        assert _solve_challenge(TODAY_INSTRUCTION) == 1234 * 52

    def test_a_different_wording_is_solved_by_its_own_word_count(self) -> None:
        assert _solve_challenge(SHORT_INSTRUCTION) == 77 * len(SHORT_INSTRUCTION.split())
        assert len(SHORT_INSTRUCTION.split()) != _CHALLENGE_LEGACY_WORD_COUNT

    def test_an_unreadable_instruction_says_to_upgrade(self, runner: CliRunner) -> None:
        client: MagicMock = _client(challenge=_challenge("Solve the riddle of the sphinx."))
        result: Any = _register(runner, client)
        assert result.exit_code == 1
        assert "dailybot upgrade" in result.output
        client.register_agent.assert_not_called()


class TestChallengeExpiry:
    def test_the_challenge_expired_code_retries_once_with_a_fresh_challenge(
        self, runner: CliRunner
    ) -> None:
        client: MagicMock = _client(
            register_agent=[
                APIError(400, "This challenge is no longer valid.", code="challenge_expired"),
                REGISTERED,
            ]
        )
        client.get_registration_challenge.side_effect = [
            _challenge(cid="ch-1"),
            _challenge(cid="ch-2"),
        ]
        result: Any = _register(runner, client)
        assert result.exit_code == 0, result.output
        ids: list[str] = [c.kwargs["challenge_id"] for c in client.register_agent.call_args_list]
        assert ids == ["ch-1", "ch-2"]

    def test_an_old_server_without_a_code_still_retries_on_the_word_expired(
        self, runner: CliRunner
    ) -> None:
        client: MagicMock = _client(register_agent=[APIError(400, "Challenge expired"), REGISTERED])
        result: Any = _register(runner, client)
        assert result.exit_code == 0, result.output
        assert client.register_agent.call_count == 2

    def test_it_retries_only_once(self, runner: CliRunner) -> None:
        expired: APIError = APIError(400, "Challenge expired.", code="challenge_expired")
        client: MagicMock = _client(register_agent=[expired, expired])
        result: Any = _register(runner, client)
        assert result.exit_code == 1
        assert client.register_agent.call_count == 2

    def test_another_code_whose_detail_says_expired_is_not_retried(self, runner: CliRunner) -> None:
        client: MagicMock = _client(
            register_agent=[
                APIError(400, "Your answer expired our patience.", code="answer_incorrect")
            ]
        )
        result: Any = _register(runner, client)
        assert result.exit_code == 1
        assert client.register_agent.call_count == 1


class TestRegistrationRateLimit:
    def test_the_wait_comes_from_retry_after(self, runner: CliRunner) -> None:
        client: MagicMock = _client(
            register_agent=[
                APIError(
                    429, "Too many requests.", code="registration_rate_limited", retry_after=120
                )
            ]
        )
        result: Any = _register(runner, client)
        assert result.exit_code == 1
        assert "Rate limited" in result.output
        assert "120s" in result.output
        assert client.register_agent.call_count == 1

    def test_without_retry_after_it_says_a_few_minutes(self, runner: CliRunner) -> None:
        client: MagicMock = _client(register_agent=[APIError(429, "Too many requests.")])
        result: Any = _register(runner, client)
        assert result.exit_code == 1
        assert "few minutes" in result.output


def _http(status: int, body: Any, headers: dict[str, str] | None = None) -> Any:
    response: MagicMock = MagicMock(spec=httpx.Response)
    response.status_code = status
    response.headers = headers or {}
    response.json.return_value = body
    response.text = str(body)
    return response


class TestChallengeGetBackoff:
    def test_a_short_retry_after_is_waited_out(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL)
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                side_effect=[
                    _http(
                        429,
                        {"detail": "slow", "code": "registration_rate_limited"},
                        {"Retry-After": "2"},
                    ),
                    _http(200, _challenge()),
                ],
            ) as get,
            patch("dailybot_cli.api_client.time.sleep") as sleep,
        ):
            result: dict[str, Any] = client.get_registration_challenge()
        assert result["challenge_id"] == "ch-1"
        assert get.call_count == 2
        sleep.assert_called_once_with(2.0)

    def test_a_long_retry_after_is_not_slept_through(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL)
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                return_value=_http(
                    429,
                    {"detail": "slow", "code": "registration_rate_limited"},
                    {"Retry-After": "3600"},
                ),
            ) as get,
            patch("dailybot_cli.api_client.time.sleep") as sleep,
            pytest.raises(APIError) as caught,
        ):
            client.get_registration_challenge()
        assert get.call_count == 1
        sleep.assert_not_called()
        assert caught.value.code == "registration_rate_limited"
        assert caught.value.retry_after == 3600.0

    def test_registration_itself_is_never_auto_retried(self) -> None:
        client: DailyBotClient = DailyBotClient(api_url=API_URL)
        with (
            patch(
                "dailybot_cli.api_client.httpx.post",
                return_value=_http(
                    429,
                    {"detail": "slow", "code": "registration_rate_limited"},
                    {"Retry-After": "1"},
                ),
            ) as post,
            pytest.raises(APIError),
        ):
            client.register_agent(
                challenge_id="c", answer=1, reason="r" * 20, org_name="o", agent_name="a"
            )
        # Every attempt consumes the challenge: a blind re-POST could never succeed.
        assert post.call_count == 1
