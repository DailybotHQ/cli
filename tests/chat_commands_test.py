"""Tests for the `dailybot chat` command group and payload builder."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.chat import ChatPayloadError, build_chat_payload
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# --- build_chat_payload (pure helper) ---


class TestBuildChatPayload:
    def test_minimal_channel_message(self) -> None:
        payload = build_chat_payload(text="hi", channels=["C0"])
        assert payload == {"message": "hi", "target_channels": ["C0"]}

    def test_users_and_teams(self) -> None:
        payload = build_chat_payload(text="hi", users=["a@co.com"], teams=["uuid-1"])
        assert payload["target_users"] == ["a@co.com"]
        assert payload["target_teams"] == ["uuid-1"]

    def test_channel_object_when_thread_given(self) -> None:
        payload = build_chat_payload(text="hi", channels=["C0"], thread="123.45")
        assert payload["target_channels"] == [{"id": "C0", "thread": "123.45"}]

    def test_channel_object_with_type(self) -> None:
        payload = build_chat_payload(text="hi", channels=["C0"], channel_type="private_channel")
        assert payload["target_channels"] == [{"id": "C0", "channel_type": "private_channel"}]

    def test_buttons(self) -> None:
        payload = build_chat_payload(
            text="hi",
            channels=["C0"],
            link_buttons=[("Open", "https://x.com")],
            action_buttons=[("Approve", "approve")],
        )
        assert payload["buttons"] == [
            {"label": "Open", "button_type": "link", "url": "https://x.com"},
            {"label": "Approve", "button_type": "interactive", "value": "approve"},
        ]

    def test_platform_settings_identity(self) -> None:
        payload = build_chat_payload(
            text="hi", channels=["C0"], bot_name="Release Bot", bot_icon_emoji=":rocket:"
        )
        assert payload["platform_settings"] == {
            "bot_username": "Release Bot",
            "bot_icon_emoji": ":rocket:",
        }

    def test_ephemeral_and_skip_time_off(self) -> None:
        payload = build_chat_payload(
            text="hi", users=["a@co.com"], ephemeral=True, skip_time_off=True
        )
        assert payload["platform_settings"]["is_ephemeral"] is True
        assert payload["skip_users_on_time_off"] is True

    def test_no_target_raises(self) -> None:
        with pytest.raises(ChatPayloadError, match="At least one target"):
            build_chat_payload(text="hi")

    def test_icon_mutual_exclusivity(self) -> None:
        with pytest.raises(ChatPayloadError, match="mutually exclusive"):
            build_chat_payload(
                text="hi",
                channels=["C0"],
                bot_icon_url="https://x/y.png",
                bot_icon_emoji=":x:",
            )

    def test_icon_url_must_be_https(self) -> None:
        with pytest.raises(ChatPayloadError, match="https://"):
            build_chat_payload(text="hi", channels=["C0"], bot_icon_url="http://x/y.png")

    def test_bot_name_length(self) -> None:
        with pytest.raises(ChatPayloadError, match="at most 80"):
            build_chat_payload(text="hi", channels=["C0"], bot_name="x" * 81)

    def test_invalid_channel_type(self) -> None:
        with pytest.raises(ChatPayloadError, match="Invalid --channel-type"):
            build_chat_payload(text="hi", channels=["C0"], channel_type="bogus")

    def test_bot_message_id_included(self) -> None:
        payload = build_chat_payload(text="x", channels=["C0"], bot_message_id="m1")
        assert payload["bot_message_id"] == "m1"

    def test_thread_responses_included(self) -> None:
        payload = build_chat_payload(
            text="headline",
            channels=["C0"],
            thread_responses=[{"message": "detail 1"}, {"message": "detail 2"}],
        )
        assert payload["thread_responses"] == [
            {"message": "detail 1"},
            {"message": "detail 2"},
        ]

    def test_too_many_thread_responses_raises(self) -> None:
        with pytest.raises(ChatPayloadError, match="At most 10"):
            build_chat_payload(
                text="x",
                channels=["C0"],
                thread_responses=[{"message": str(i)} for i in range(11)],
            )

    def test_extra_buttons_passthrough_new_keys(self) -> None:
        raw = [
            {
                "label": "Yes",
                "button_type": "interactive",
                "value": "approve",
                "callback_url": "https://hooks.example.com/x",
                "label_after_click": "Approved",
                "response": {"message": "Got it", "ephemeral": True},
                "callback_auth": {"type": "bearer", "token": "tok"},
                "future_field": {"kept": True},
            }
        ]
        payload = build_chat_payload(text="hi", channels=["C0"], extra_buttons=raw)
        assert payload["buttons"][0]["callback_url"] == "https://hooks.example.com/x"
        assert payload["buttons"][0]["future_field"] == {"kept": True}
        assert payload["buttons"][0]["callback_auth"]["token"] == "tok"

    def test_callback_exclusivity_prevalidation(self) -> None:
        with pytest.raises(ChatPayloadError, match="more than one callback"):
            build_chat_payload(
                text="hi",
                channels=["C0"],
                extra_buttons=[
                    {
                        "label": "Go",
                        "button_type": "interactive",
                        "value": "go",
                        "callback_url": "https://x.example/a",
                        "callback_prompt": "Summarize",
                    }
                ],
            )

    def test_buttons_cap_prevalidation(self) -> None:
        with pytest.raises(ChatPayloadError, match="At most 25"):
            build_chat_payload(
                text="hi",
                channels=["C0"],
                extra_buttons=[
                    {"label": f"B{i}", "button_type": "interactive", "value": str(i)}
                    for i in range(26)
                ],
            )

    def test_missing_label_prevalidation(self) -> None:
        with pytest.raises(ChatPayloadError, match="required 'label'"):
            build_chat_payload(
                text="hi",
                channels=["C0"],
                extra_buttons=[{"button_type": "interactive", "value": "x"}],
            )


# --- chat send / update commands ---


def _mock_resolve(mock_resolve: MagicMock) -> MagicMock:
    client: MagicMock = MagicMock()
    client.send_chat_message.return_value = {"bot_message_id": "999"}
    mock_resolve.return_value = ("CLI Agent", client, {})
    return client


class TestChatSendCommand:
    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_send_to_channel(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        client = _mock_resolve(mock_resolve)
        result = runner.invoke(cli, ["chat", "send", "-c", "C0", "-m", "Deploy done"])
        assert result.exit_code == 0
        client.send_chat_message.assert_called_once_with(
            {"message": "Deploy done", "target_channels": ["C0"]}
        )
        assert "Message Sent" in result.output

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_send_to_user(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        client = _mock_resolve(mock_resolve)
        result = runner.invoke(cli, ["chat", "send", "-u", "ana@co.com", "-m", "Standup"])
        assert result.exit_code == 0
        assert client.send_chat_message.call_args[0][0]["target_users"] == ["ana@co.com"]

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_send_json_mode_emits_id(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        _mock_resolve(mock_resolve)
        result = runner.invoke(cli, ["chat", "send", "-c", "C0", "-m", "hi", "--json"])
        assert result.exit_code == 0
        assert '"bot_message_id": "999"' in result.output

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_send_identity_and_button(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        client = _mock_resolve(mock_resolve)
        result = runner.invoke(
            cli,
            [
                "chat",
                "send",
                "-c",
                "C0",
                "-m",
                "x",
                "--bot-name",
                "Release Bot",
                "--link-button",
                "Open::https://app/r",
            ],
        )
        assert result.exit_code == 0
        sent = client.send_chat_message.call_args[0][0]
        assert sent["platform_settings"]["bot_username"] == "Release Bot"
        assert sent["buttons"][0]["url"] == "https://app/r"

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_send_payload_json_passthrough(
        self, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        client = _mock_resolve(mock_resolve)
        result = runner.invoke(
            cli,
            [
                "chat",
                "send",
                "--payload-json",
                '{"target_channels":["C0"],"messages":[{"message":"a"}]}',
            ],
        )
        assert result.exit_code == 0
        sent = client.send_chat_message.call_args[0][0]
        assert sent["messages"] == [{"message": "a"}]

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_send_no_target_fails(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        _mock_resolve(mock_resolve)
        result = runner.invoke(cli, ["chat", "send", "-m", "orphan"])
        assert result.exit_code == 1
        assert "At least one target" in result.output

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_send_bad_button_fails(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        _mock_resolve(mock_resolve)
        result = runner.invoke(
            cli, ["chat", "send", "-c", "C0", "-m", "x", "--link-button", "no-separator"]
        )
        assert result.exit_code == 1
        assert "Invalid link button" in result.output

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_send_auth_error_hints_api_key(
        self, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        client = _mock_resolve(mock_resolve)
        client.send_chat_message.side_effect = APIError(status_code=403, detail="API Key Not Valid")
        result = runner.invoke(cli, ["chat", "send", "-c", "C0", "-m", "x"])
        # Code-less 403 must match exit_for_api_error → EXIT_PERMISSION_DENIED.
        assert result.exit_code == 4
        # Rich may hard-wrap the hint; collapse whitespace before asserting.
        assert "dailybot config" in result.output.replace("\n", " ")
        assert "key=" in result.output

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_ephemeral_channel_only_warns(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        _mock_resolve(mock_resolve)
        result = runner.invoke(cli, ["chat", "send", "-c", "C0", "-m", "x", "--ephemeral"])
        assert result.exit_code == 0
        assert "Ephemeral" in result.output

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_send_with_thread_messages(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        client = _mock_resolve(mock_resolve)
        client.send_chat_message.return_value = {
            "bot_message_id": "parent-id",
            "thread_responses": ["$db/r1", "$db/r2"],
        }
        result = runner.invoke(
            cli,
            [
                "chat",
                "send",
                "-c",
                "C0",
                "-m",
                "Headline",
                "--thread-message",
                "detail 1",
                "--thread-message",
                "detail 2",
            ],
        )
        assert result.exit_code == 0
        sent = client.send_chat_message.call_args[0][0]
        assert sent["thread_responses"] == [{"message": "detail 1"}, {"message": "detail 2"}]
        # Reply ids are surfaced so they can be edited.
        assert "$db/r1" in result.output
        assert "$db/r2" in result.output

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_too_many_thread_messages_fails(
        self, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        _mock_resolve(mock_resolve)
        args = ["chat", "send", "-c", "C0", "-m", "x"]
        for i in range(11):
            args += ["--thread-message", f"r{i}"]
        result = runner.invoke(cli, args)
        assert result.exit_code == 1
        assert "At most 10" in result.output

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_role_scope_error(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        client = _mock_resolve(mock_resolve)
        client.send_chat_message.side_effect = APIError(
            status_code=403, detail="Not allowed", code="cli_send_message_target_not_allowed"
        )
        result = runner.invoke(cli, ["chat", "send", "-c", "C0", "-m", "x"])
        assert result.exit_code == 4
        assert "role can only reach" in result.output

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_rate_limit_error(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        client = _mock_resolve(mock_resolve)
        client.send_chat_message.side_effect = APIError(status_code=429, detail="too many")
        result = runner.invoke(cli, ["chat", "send", "-c", "C0", "-m", "x"])
        assert result.exit_code == 1
        assert "Rate limit" in result.output

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_approve_reject_callback_buttons(
        self, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        client = _mock_resolve(mock_resolve)
        result = runner.invoke(
            cli,
            [
                "chat",
                "send",
                "-u",
                "ana@co.com",
                "-m",
                "Deploy?",
                "--approve-button",
                "Yes=approve",
                "--reject-button",
                "No=deny",
                "--callback-url",
                "https://hooks.example.com/req42",
                "--callback-bearer",
                "secret-token",
            ],
        )
        assert result.exit_code == 0
        buttons = client.send_chat_message.call_args[0][0]["buttons"]
        assert buttons[0]["callback_url"] == "https://hooks.example.com/req42"
        assert buttons[0]["value"] == "approve"
        assert buttons[0]["callback_auth"] == {"type": "bearer", "token": "secret-token"}
        assert buttons[1]["value"] == "deny"
        assert buttons[1]["callback_auth"]["type"] == "bearer"

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_workflow_button(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        client = _mock_resolve(mock_resolve)
        wf = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        result = runner.invoke(
            cli,
            [
                "chat",
                "send",
                "-c",
                "C0",
                "-m",
                "Ready?",
                "--workflow-button",
                f"Run release={wf}",
            ],
        )
        assert result.exit_code == 0
        button = client.send_chat_message.call_args[0][0]["buttons"][0]
        assert button["label"] == "Run release"
        assert button["callback_workflow"] == wf
        assert button["value"] == wf

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_buttons_json_passthrough(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        client = _mock_resolve(mock_resolve)
        buttons_json = (
            '[{"label":"Ask","button_type":"interactive","value":"ask",'
            '"callback_prompt":"Summarize incidents","response":{"message":"On it"}}]'
        )
        result = runner.invoke(
            cli, ["chat", "send", "-c", "C0", "-m", "x", "--buttons", buttons_json]
        )
        assert result.exit_code == 0
        button = client.send_chat_message.call_args[0][0]["buttons"][0]
        assert button["callback_prompt"] == "Summarize incidents"
        assert button["response"]["message"] == "On it"

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_callback_exclusivity_fails_cli(
        self, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        _mock_resolve(mock_resolve)
        buttons_json = (
            '[{"label":"X","button_type":"interactive","value":"x",'
            '"callback_url":"https://a.example","callback_form":"form-uuid"}]'
        )
        result = runner.invoke(
            cli, ["chat", "send", "-c", "C0", "-m", "x", "--buttons", buttons_json]
        )
        assert result.exit_code == 1
        assert "more than one callback" in result.output

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_button_server_error_json_passthrough(
        self, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        client = _mock_resolve(mock_resolve)
        client.send_chat_message.side_effect = APIError(
            status_code=400,
            detail="modal needs callback_url",
            code="button_modal_body_invalid",
        )
        result = runner.invoke(cli, ["chat", "send", "-c", "C0", "-m", "x", "--json"])
        assert result.exit_code == 2
        assert '"code": "button_modal_body_invalid"' in result.output
        assert "modal needs callback_url" in result.output

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_update_with_buttons_json(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        client = _mock_resolve(mock_resolve)
        result = runner.invoke(
            cli,
            [
                "chat",
                "update",
                "m-123",
                "-c",
                "C0",
                "-m",
                "Updated",
                "--buttons",
                '[{"label":"Ok","button_type":"interactive","value":"ok",'
                '"callback_command":"help"}]',
            ],
        )
        assert result.exit_code == 0
        sent = client.send_chat_message.call_args[0][0]
        assert sent["bot_message_id"] == "m-123"
        assert sent["buttons"][0]["callback_command"] == "help"


class TestChatUpdateCommand:
    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_update_includes_message_id(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        client = _mock_resolve(mock_resolve)
        result = runner.invoke(cli, ["chat", "update", "m-123", "-c", "C0", "-m", "DONE"])
        assert result.exit_code == 0
        sent = client.send_chat_message.call_args[0][0]
        assert sent["bot_message_id"] == "m-123"
        assert "Message Updated" in result.output

    @patch("dailybot_cli.commands.chat._resolve_agent_context")
    def test_update_a_thread_reply_id(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        # A reply id from thread_responses is just a bot_message_id — editable too.
        client = _mock_resolve(mock_resolve)
        result = runner.invoke(cli, ["chat", "update", "$db/r2", "-c", "C0", "-m", "rolled back"])
        assert result.exit_code == 0
        assert client.send_chat_message.call_args[0][0]["bot_message_id"] == "$db/r2"


VALID_UUID = "646b2982-93ef-4b9f-be44-5f0a39e9f8ef"


class TestSendAsUser:
    """Task 12: send_as_user identity on chat send."""

    def test_payload_includes_send_as_user(self) -> None:
        payload = build_chat_payload(text="hi", channels=["C0"], send_as_user=VALID_UUID)
        assert payload["send_as_user"] == VALID_UUID

    def test_omitting_send_as_user_is_unchanged(self) -> None:
        payload = build_chat_payload(text="hi", channels=["C0"])
        assert "send_as_user" not in payload

    def test_conflict_with_bot_name_raises(self) -> None:
        with pytest.raises(ChatPayloadError):
            build_chat_payload(
                text="hi", channels=["C0"], send_as_user=VALID_UUID, bot_name="Release Bot"
            )

    def test_invalid_uuid_raises(self) -> None:
        with pytest.raises(ChatPayloadError):
            build_chat_payload(text="hi", channels=["C0"], send_as_user="not-a-uuid")

    def test_send_as_me_resolves_current_user(self) -> None:
        with (
            patch("dailybot_cli.commands.chat._resolved_client") as mock_resolved,
            patch("dailybot_cli.commands.chat.get_current_user_uuid", return_value=VALID_UUID),
            patch("dailybot_cli.commands.chat._send") as mock_send,
        ):
            mock_resolved.return_value = (MagicMock(), {})
            result = CliRunner().invoke(
                cli, ["chat", "send", "-c", "C0", "-m", "hi", "--send-as-me"]
            )
        assert result.exit_code == 0
        payload = mock_send.call_args[0][1]
        assert payload["send_as_user"] == VALID_UUID

    def test_send_as_user_and_send_as_me_conflict(self) -> None:
        with patch("dailybot_cli.commands.chat._resolved_client") as mock_resolved:
            mock_resolved.return_value = (MagicMock(), {})
            result = CliRunner().invoke(
                cli,
                [
                    "chat",
                    "send",
                    "-c",
                    "C0",
                    "-m",
                    "hi",
                    "--send-as-me",
                    "--send-as-user",
                    VALID_UUID,
                ],
            )
        assert result.exit_code != 0

    def test_org_admin_required_message(self) -> None:
        from dailybot_cli.commands.public_api_helpers import ERROR_CODE_MESSAGES

        # Now fires on every admin-only endpoint, so the shared message is generic
        # (chat send overrides it with the --send-as-user hint at the call site).
        assert "admin" in ERROR_CODE_MESSAGES["org_admin_required"].lower()
        assert "send_as_user_not_found" in ERROR_CODE_MESSAGES
