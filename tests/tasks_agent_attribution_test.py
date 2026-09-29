"""Agent attribution on Tasks writes — the transport half.

A person's credential authors every write; a named agent may ride along as the
executor companion. The client carries that name and stamps it on Tasks writes
only. Every test patches ``httpx`` at the call site (``AGENTS.md`` rule 7).
"""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from dailybot_cli.api_client import (
    TASKS_AGENT_NAME_HEADER,
    TASKS_AGENT_NAME_MAX_LENGTH,
    DailyBotClient,
    clean_agent_name,
)


def _response(status: int = 201, payload: Any = None) -> MagicMock:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = {} if payload is None else payload
    mock.headers = {}
    return mock


def _client(agent_name: str | None = None) -> DailyBotClient:
    return DailyBotClient(
        api_url="http://test-api.example.com",
        token="test-token",
        api_key="test-api-key",
        agent_name=agent_name,
    )


class TestCleanAgentName:
    def test_none_and_blank_mean_no_agent(self) -> None:
        assert clean_agent_name(None) is None
        assert clean_agent_name("") is None
        assert clean_agent_name("   \t ") is None

    def test_control_characters_are_stripped(self) -> None:
        assert clean_agent_name("Claude\x1b[31m Code\x07") == "Claude[31m Code"
        assert clean_agent_name("Cla\u0085ude\x7f") == "Claude"

    def test_whitespace_is_collapsed_and_trimmed(self) -> None:
        assert clean_agent_name("  Claude \n\n  Code  ") == "Claude Code"

    def test_length_is_capped(self) -> None:
        cleaned: str | None = clean_agent_name("a" * (TASKS_AGENT_NAME_MAX_LENGTH + 40))
        assert cleaned is not None
        assert len(cleaned) == TASKS_AGENT_NAME_MAX_LENGTH

    def test_non_ascii_is_kept(self) -> None:
        assert clean_agent_name("Agente Ñandú") == "Agente Ñandú"


class TestTasksWriteStamp:
    def test_no_agent_name_sends_no_stamp(self) -> None:
        with patch("httpx.post", return_value=_response()) as mock_post:
            _client().comment_on_task("7f1c2b3a-0000-4000-8000-000000000001", body="hi")
        headers: dict[str, str] = mock_post.call_args.kwargs["headers"]
        assert TASKS_AGENT_NAME_HEADER not in headers

    def test_agent_name_is_stamped_on_a_tasks_write(self) -> None:
        with patch("httpx.post", return_value=_response()) as mock_post:
            _client("Claude Code").comment_on_task(
                "7f1c2b3a-0000-4000-8000-000000000001", body="hi"
            )
        headers: dict[str, str] = mock_post.call_args.kwargs["headers"]
        assert headers[TASKS_AGENT_NAME_HEADER] == "Claude Code"

    def test_non_ascii_name_is_percent_encoded_on_the_wire(self) -> None:
        with patch("httpx.post", return_value=_response()) as mock_post:
            _client("Agente Ñandú").comment_on_task(
                "7f1c2b3a-0000-4000-8000-000000000001", body="hi"
            )
        headers: dict[str, str] = mock_post.call_args.kwargs["headers"]
        assert headers[TASKS_AGENT_NAME_HEADER] == "Agente %C3%91and%C3%BA"
        assert headers[TASKS_AGENT_NAME_HEADER].isascii()

    def test_a_literal_percent_is_encoded_so_decoding_is_unambiguous(self) -> None:
        with patch("httpx.post", return_value=_response()) as mock_post:
            _client("Bot 100%").comment_on_task("7f1c2b3a-0000-4000-8000-000000000001", body="hi")
        headers: dict[str, str] = mock_post.call_args.kwargs["headers"]
        assert headers[TASKS_AGENT_NAME_HEADER] == "Bot 100%25"

    def test_reads_are_never_stamped(self) -> None:
        with patch("httpx.get", return_value=_response(200, {"uuid": "x"})) as mock_get:
            _client("Claude Code").get_task("ENG-1")
        headers: dict[str, str] = mock_get.call_args.kwargs["headers"]
        assert TASKS_AGENT_NAME_HEADER not in headers

    def test_stamp_does_not_replace_the_person_credential(self) -> None:
        with patch("httpx.post", return_value=_response()) as mock_post:
            _client("Claude Code").comment_on_task(
                "7f1c2b3a-0000-4000-8000-000000000001", body="hi"
            )
        headers: dict[str, str] = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer test-token"


@pytest.mark.parametrize("name", ["Claude Code", "  Claude Code  "])
def test_client_stores_the_cleaned_name(name: str) -> None:
    assert _client(name).agent_name == "Claude Code"
