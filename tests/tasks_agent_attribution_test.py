"""Agent attribution on Tasks writes — the transport half.

A person's credential authors every write; a named agent may ride along as the
executor companion. The client carries that name and stamps it on Tasks writes
only. Every test patches ``httpx`` at the call site (``AGENTS.md`` rule 7).
"""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli import config
from dailybot_cli.api_client import (
    INVALID_AGENT_ATTRIBUTION_CODE,
    TASKS_AGENT_NAME_BODY_FIELD,
    TASKS_AGENT_NAME_HEADER,
    TASKS_AGENT_NAME_MAX_LENGTH,
    APIError,
    DailyBotClient,
    clean_agent_name,
)
from dailybot_cli.commands.public_api_helpers import ERROR_CODE_MESSAGES
from dailybot_cli.main import cli

TASK_UUID: str = "7f1c2b3a-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def _no_ambient_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DAILYBOT_AGENT_NAME", raising=False)
    monkeypatch.setattr(config, "_agent_name_override", None)


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

    def test_length_is_never_truncated(self) -> None:
        cleaned: str | None = clean_agent_name("a" * (TASKS_AGENT_NAME_MAX_LENGTH + 40))
        assert cleaned is not None
        assert len(cleaned) == TASKS_AGENT_NAME_MAX_LENGTH + 40

    def test_format_characters_go(self) -> None:
        assert clean_agent_name("Claude\u202eCode") == "ClaudeCode"
        assert clean_agent_name("\u200b") is None

    def test_non_ascii_is_kept(self) -> None:
        assert clean_agent_name("Agente Ñandú") == "Agente Ñandú"


class TestTasksWriteStamp:
    def test_no_agent_name_sends_no_stamp(self) -> None:
        with patch("httpx.post", return_value=_response()) as mock_post:
            _client().comment_on_task(TASK_UUID, body="hi")
        assert TASK_UUID in mock_post.call_args.args[0]
        assert TASKS_AGENT_NAME_HEADER not in mock_post.call_args.kwargs["headers"]
        assert TASKS_AGENT_NAME_BODY_FIELD not in mock_post.call_args.kwargs["json"]

    def test_json_write_carries_the_name_in_the_body_only(self) -> None:
        with patch("httpx.post", return_value=_response()) as mock_post:
            _client("Agente Ñandú").comment_on_task(TASK_UUID, body="hi")
        assert mock_post.call_args.kwargs["json"] == {
            "body": "hi",
            TASKS_AGENT_NAME_BODY_FIELD: "Agente Ñandú",
        }
        assert TASKS_AGENT_NAME_HEADER not in mock_post.call_args.kwargs["headers"]

    def test_body_less_write_carries_the_percent_encoded_header(self) -> None:
        with patch("httpx.request", return_value=_response(204)) as mock_request:
            _client("Agente Ñandú").delete_task_comment(TASK_UUID, TASK_UUID)
        headers: dict[str, str] = mock_request.call_args.kwargs["headers"]
        assert headers[TASKS_AGENT_NAME_HEADER] == "Agente %C3%91and%C3%BA"

    def test_a_literal_percent_is_encoded_so_decoding_is_unambiguous(self) -> None:
        with patch("httpx.request", return_value=_response(204)) as mock_request:
            _client("Bot 100%").delete_task_comment(TASK_UUID, TASK_UUID)
        assert mock_request.call_args.kwargs["headers"][TASKS_AGENT_NAME_HEADER] == "Bot 100%25"

    def test_multipart_upload_carries_the_header(self) -> None:
        with patch("httpx.post", return_value=_response()) as mock_post:
            _client("Claude Code").upload_attachment_multipart(
                TASK_UUID, filename="a.txt", content_type="text/plain", data=b"x"
            )
        assert mock_post.call_args.kwargs["headers"][TASKS_AGENT_NAME_HEADER] == "Claude Code"

    def test_too_long_is_refused_locally_without_a_request(self) -> None:
        with patch("httpx.post") as mock_post, pytest.raises(APIError) as caught:
            _client("a" * (TASKS_AGENT_NAME_MAX_LENGTH + 1)).comment_on_task(TASK_UUID, body="hi")
        assert caught.value.code == INVALID_AGENT_ATTRIBUTION_CODE
        mock_post.assert_not_called()

    def test_reads_are_never_stamped(self) -> None:
        with patch("httpx.get", return_value=_response(200, {"uuid": "x"})) as mock_get:
            _client("Claude Code").get_task("ENG-1")
        assert TASKS_AGENT_NAME_HEADER not in mock_get.call_args.kwargs["headers"]

    def test_stamp_does_not_replace_the_person_credential(self) -> None:
        with patch("httpx.post", return_value=_response()) as mock_post:
            _client("Claude Code").comment_on_task(TASK_UUID, body="hi")
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-token"


class TestAgentNameSource:
    def test_env_var_names_the_agent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DAILYBOT_AGENT_NAME", "Codex")
        assert _client().agent_name == "Codex"

    def test_explicit_argument_beats_the_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DAILYBOT_AGENT_NAME", "Codex")
        assert _client("Claude Code").agent_name == "Claude Code"

    def test_root_option_sets_the_agent_for_the_invocation(self) -> None:
        seen: dict[str, str | None] = {}

        def fake_get_task(self: DailyBotClient, task: str) -> dict[str, Any]:
            seen["agent"] = self.agent_name
            return {"uuid": TASK_UUID, "key": "ENG-1", "title": "t"}

        with (
            patch(
                "dailybot_cli.commands.public_api_helpers.get_agent_auth", return_value=("k", "key")
            ),
            patch.object(DailyBotClient, "get_task", fake_get_task),
        ):
            CliRunner().invoke(
                cli, ["--agent-name", "Claude Code", "task", "get", "ENG-1", "--json"]
            )
        assert seen["agent"] == "Claude Code"

    def test_error_code_has_a_user_message(self) -> None:
        assert INVALID_AGENT_ATTRIBUTION_CODE in ERROR_CODE_MESSAGES


@pytest.mark.parametrize("name", ["Claude Code", "  Claude Code  "])
def test_client_stores_the_cleaned_name(name: str) -> None:
    assert _client(name).agent_name == "Claude Code"


class TestAttributionRendering:
    def _render(self, fn: Any, arg: Any) -> str:
        from dailybot_cli.display import console

        with console.capture() as cap:
            fn(arg)
        return cap.get()

    def test_comment_shows_the_person_then_the_agent(self) -> None:
        from dailybot_cli.display import print_task_comments

        out: str = self._render(
            print_task_comments,
            [
                {
                    "uuid": "c1",
                    "author": {"full_name": "Jane Doe"},
                    "executed_by_agent": {"uuid": "a1", "name": "Claude Code", "avatar": 42},
                    "body": "Fixed in PR 812",
                }
            ],
        )
        assert out.index("Jane Doe") < out.index('via "Claude Code"')

    def test_comment_without_agent_has_no_via(self) -> None:
        from dailybot_cli.display import print_task_comments

        out: str = self._render(
            print_task_comments,
            [
                {
                    "uuid": "c1",
                    "author": {"full_name": "Jane Doe"},
                    "executed_by_agent": None,
                    "body": "x",
                }
            ],
        )
        assert "via" not in out

    def test_task_detail_lists_executors_apart_from_the_executor(self) -> None:
        from dailybot_cli.display import print_task_detail

        out: str = self._render(
            print_task_detail,
            {
                "uuid": TASK_UUID,
                "key": "ENG-12",
                "title": "t",
                "executor": None,
                "executors": [
                    {"uuid": "a1", "name": "Claude Code", "avatar": 42},
                    {"uuid": "a2", "name": "Codex", "avatar": None},
                ],
            },
        )
        assert "Agents" in out
        assert '"Claude Code", "Codex"' in out

    def test_agent_names_are_neutralized(self) -> None:
        from dailybot_cli.display import print_task_detail

        out: str = self._render(
            print_task_detail,
            {
                "uuid": TASK_UUID,
                "key": "ENG-1",
                "title": "t",
                "executors": [{"name": "Bot\x1b[31m"}],
            },
        )
        assert "\x1b[31m" not in out


class TestPersonNameShapes:
    """The server's person ref carries `name`; older payloads carried `full_name`."""

    def test_comment_author_by_name(self) -> None:
        from dailybot_cli.display import console, print_task_comments

        with console.capture() as cap:
            print_task_comments(
                [
                    {
                        "uuid": "c1",
                        "author": {"kind": "user", "name": "Emma Watson"},
                        "executed_by_agent": {"name": "Claude Code"},
                        "body": "x",
                    }
                ]
            )
        assert '"Emma Watson" via "Claude Code"' in cap.get()

    def test_owner_by_name_in_the_table(self) -> None:
        from dailybot_cli.display import console, print_tasks_table

        with console.capture() as cap:
            print_tasks_table([{"key": "ENG-1", "title": "t", "owner": {"name": "Emma Watson"}}])
        assert "Emma Watson" in cap.get()


def test_the_refusal_names_every_cause() -> None:
    message: str = ERROR_CODE_MESSAGES[INVALID_AGENT_ATTRIBUTION_CODE]
    assert "128" in message
    assert "letters, numbers, spaces" in message
    assert "deactivated" in message
    assert "agent key" in message


def test_format_characters_are_stripped_from_agent_names() -> None:
    assert clean_agent_name("Claude‮ Code​") == "Claude Code"


def test_a_path_segment_ending_in_newline_is_refused() -> None:
    with pytest.raises(APIError):
        _client().get_task("ENG-1\n")


def test_a_name_of_only_invisible_characters_is_no_agent() -> None:
    assert clean_agent_name("\u202e\u200b\u200d") is None
