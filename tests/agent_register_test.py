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

    def test_a_coded_429_without_retry_after_still_gives_a_wait_hint(
        self, runner: CliRunner
    ) -> None:
        # The server's throttle can omit Retry-After in an edge case (no computable wait).
        client: MagicMock = _client(
            register_agent=[APIError(429, "Too many requests.", code="registration_rate_limited")]
        )
        result: Any = _register(runner, client)
        assert result.exit_code == 1
        flat: str = " ".join(result.output.split())
        assert "Rate limited" in flat
        assert "try again" in flat.lower()
        assert "Nones" not in flat

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


class TestRegistrationOutput:
    def test_the_claim_expiry_comes_from_the_server(self, runner: CliRunner) -> None:
        result: Any = _register(runner, _client(register_agent=REGISTERED))
        assert result.exit_code == 0, result.output
        assert "Send this to your human" in result.output
        assert "https://app.example.com/claim/abc" in result.output
        assert "2026-11-25 12:00 UTC" in result.output
        assert "30 days" not in result.output

    def test_without_claim_expires_at_it_points_to_the_claim_page(self, runner: CliRunner) -> None:
        legacy: dict[str, Any] = {k: v for k, v in REGISTERED.items() if k != "claim_expires_at"}
        result: Any = _register(runner, _client(register_agent=legacy))
        assert result.exit_code == 0, result.output
        assert "see the claim page" in result.output.lower()
        assert "30 days" not in result.output

    def test_an_unparseable_expiry_is_shown_as_sent(self, runner: CliRunner) -> None:
        odd: dict[str, Any] = {**REGISTERED, "claim_expires_at": "soon"}
        result: Any = _register(runner, _client(register_agent=odd))
        assert result.exit_code == 0, result.output
        assert "soon" in result.output

    def test_the_api_key_is_saved_but_never_printed(self, runner: CliRunner) -> None:
        result: Any = _register(
            runner, _client(register_agent={**REGISTERED, "api_key": "sk-live-abcdef123456"})
        )
        assert result.exit_code == 0, result.output
        assert "sk-live-abcdef123456" not in result.output
        assert result.save.call_args.kwargs["api_key"] == "sk-live-abcdef123456"

    def test_server_text_cannot_inject_terminal_markup(self, runner: CliRunner) -> None:
        injected: dict[str, Any] = {**REGISTERED, "org_name": "[red]Pwned[/red]"}
        result: Any = _register(runner, _client(register_agent=injected))
        assert result.exit_code == 0, result.output
        assert "[red]Pwned[/red]" in result.output


def test_no_hardcoded_claim_lifetime_remains_in_the_package() -> None:
    from pathlib import Path

    import dailybot_cli

    root: Path = Path(dailybot_cli.__file__).parent
    hits: list[str] = [
        str(path) for path in root.rglob("*.py") if "30 days" in path.read_text(encoding="utf-8")
    ]
    assert hits == []


REV1_REGISTRATION_CODES: list[str] = [
    "missing_fields",
    "invalid_answer",
    "challenge_invalid",
    "challenge_used",
    "challenge_expired",
    "answer_incorrect",
    "reason_too_short",
    "reason_echoes_instruction",
    "registration_rate_limited",
    "claim_token_unavailable",
]


class TestRev1ErrorCodes:
    def test_every_rev1_code_has_a_message(self) -> None:
        from dailybot_cli.commands.public_api_helpers import ERROR_CODE_MESSAGES

        missing: list[str] = [c for c in REV1_REGISTRATION_CODES if c not in ERROR_CODE_MESSAGES]
        assert missing == []

    @pytest.mark.parametrize(
        "code",
        [
            c
            for c in REV1_REGISTRATION_CODES
            if c not in ("challenge_expired", "registration_rate_limited")
        ],
    )
    def test_a_registration_400_shows_the_code_message_not_the_detail(
        self, runner: CliRunner, code: str
    ) -> None:
        from dailybot_cli.commands.public_api_helpers import ERROR_CODE_MESSAGES

        client: MagicMock = _client(register_agent=[APIError(400, "server prose", code=code)])
        result: Any = _register(runner, client)
        assert result.exit_code == 1
        assert ERROR_CODE_MESSAGES[code].split(".")[0] in " ".join(result.output.split())
        assert client.register_agent.call_count == 1

    def test_an_unknown_code_falls_back_to_the_detail(self, runner: CliRunner) -> None:
        client: MagicMock = _client(
            register_agent=[APIError(400, "Something new went wrong.", code="brand_new_code")]
        )
        result: Any = _register(runner, client)
        assert result.exit_code == 1
        assert "Something new went wrong." in result.output

    def test_a_wrong_answer_suggests_upgrading(self, runner: CliRunner) -> None:
        client: MagicMock = _client(
            register_agent=[APIError(400, "Wrong.", code="answer_incorrect")]
        )
        result: Any = _register(runner, client)
        assert "dailybot upgrade" in result.output


def _agent_cmd(runner: CliRunner, client: MagicMock, args: list[str]) -> Any:
    with (
        patch("dailybot_cli.commands.agent.DailyBotClient", return_value=client),
        patch("dailybot_cli.commands.agent.get_default_profile", return_value=None),
        patch("dailybot_cli.commands.agent.get_agent_auth", return_value="api_key"),
    ):
        return runner.invoke(cli, ["agent", *args])


class TestAgentKeyScope:
    def test_a_registered_key_out_of_scope_explains_the_scope_and_the_upgrade(
        self, runner: CliRunner
    ) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.send_agent_email.side_effect = APIError(
            403,
            "Upgrade required.",
            code="plan_upgrade_required",
            extra={"upgrade_url": "https://app.example.com/billing"},
        )
        result: Any = _agent_cmd(
            runner,
            client,
            [
                "email",
                "send",
                "--to",
                "me@example.com",
                "--subject",
                "s",
                "--body-html",
                "<p>b</p>",
            ],
        )
        assert result.exit_code == 1
        flat: str = " ".join(result.output.split())
        assert "agent reports" in flat
        assert "https://app.example.com/billing" in flat

    def test_a_free_plan_daily_cap_on_a_report_uses_the_code_message(
        self, runner: CliRunner
    ) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.submit_agent_report.side_effect = APIError(
            429, "Daily limit.", code="free_plan_daily_limit_exceeded"
        )
        result: Any = _agent_cmd(runner, client, ["update", "Shipped it"])
        assert result.exit_code == 1
        assert "free-plan limit" in " ".join(result.output.split())

    def test_a_deactivated_agent_key_says_so(self, runner: CliRunner) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.submit_agent_report.side_effect = APIError(
            403, "Invalid credentials.", code="invalid_credentials"
        )
        result: Any = _agent_cmd(runner, client, ["update", "Shipped it"])
        assert result.exit_code == 1
        assert "deactivated" in " ".join(result.output.split())

    def test_an_error_without_a_code_still_shows_the_detail(self, runner: CliRunner) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.submit_agent_report.side_effect = APIError(400, "Content is required.")
        result: Any = _agent_cmd(runner, client, ["update", "Shipped it"])
        assert result.exit_code == 1
        assert "Content is required." in result.output


class TestConfigureAcceptsAScopedKey:
    def test_plan_upgrade_required_means_the_key_is_valid(
        self, runner: CliRunner, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.get_agent_health.side_effect = APIError(
            403, "Upgrade required.", code="plan_upgrade_required"
        )
        with (
            patch("dailybot_cli.commands.agent.DailyBotClient", return_value=client),
            patch("dailybot_cli.commands.agent.save_agent_profile") as save,
        ):
            result: Any = runner.invoke(
                cli, ["agent", "configure", "--name", "Bot", "--key", "test-key"]
            )
        assert result.exit_code == 0, result.output
        save.assert_called_once()

    def test_an_invalid_key_is_still_refused(self, runner: CliRunner) -> None:
        client: MagicMock = MagicMock(spec=DailyBotClient)
        client.get_agent_health.side_effect = APIError(
            403, "Invalid credentials.", code="invalid_credentials"
        )
        with (
            patch("dailybot_cli.commands.agent.DailyBotClient", return_value=client),
            patch("dailybot_cli.commands.agent.save_agent_profile") as save,
        ):
            result: Any = runner.invoke(
                cli, ["agent", "configure", "--name", "Bot", "--key", "test-key"]
            )
        assert result.exit_code == 1
        save.assert_not_called()
