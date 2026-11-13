"""Qualified channel references (PLAN_002 T-qualified-channels, W2 grammar, L44, L74).

Forms: raw (today's ids and names), platform-qualified `slack|msteams|discord|hangouts:<id>`
split on the first colon, and installation-qualified `<ChatPlatformSummary.id>:<id>`.
A Teams id `19:…` stays raw; `dailybot:` is not a chat send destination; qualified
forms are sent only when `/v1/organization/` serves `chat_platforms`.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner, Result

from dailybot_cli.api_client import APIError, DailyBotClient, PaginatedResult
from dailybot_cli.commands._channels import (
    ChannelReference,
    check_chat_channel_references,
    parse_channel_reference,
    resolve_channel,
)
from dailybot_cli.main import cli
from tests.wire_fixture_loader import fixture_body, fixture_response

PLATFORM_ID: str = fixture_body("organization_chat_platforms_no_plan_200")["chat_platforms"][0][
    "id"
]


class TestGrammar:
    @pytest.mark.parametrize(
        "reference,kind,qualifier,channel_id",
        [
            ("C024BE91L", "raw", None, "C024BE91L"),
            ("19:abc@thread.tacv2", "raw", None, "19:abc@thread.tacv2"),
            ("general", "raw", None, "general"),
            ("slack:C024BE91L", "platform", "slack", "C024BE91L"),
            ("msteams:19:abc@thread.tacv2", "platform", "msteams", "19:abc@thread.tacv2"),
            ("discord:123456789012345678", "platform", "discord", "123456789012345678"),
            ("hangouts:spaces/AAAA", "platform", "hangouts", "spaces/AAAA"),
            (f"{PLATFORM_ID}:C024BE91L", "installation", PLATFORM_ID, "C024BE91L"),
            ("dailybot:C1", "dailybot", "dailybot", "C1"),
            ("Slack:C1", "raw", None, "Slack:C1"),
            ("slack:", "raw", None, "slack:"),
            (
                "00000000-0000-4000-8000-00000000002G:C1",
                "raw",
                None,
                "00000000-0000-4000-8000-00000000002G:C1",
            ),
        ],
    )
    def test_the_frozen_forms(
        self, reference: str, kind: str, qualifier: str | None, channel_id: str
    ) -> None:
        parsed: ChannelReference = parse_channel_reference(reference)
        assert parsed.kind == kind
        assert parsed.qualifier == qualifier
        assert parsed.channel_id == channel_id
        assert parsed.original == reference


def _org_client(body_name: str | None) -> MagicMock:
    client: MagicMock = MagicMock(spec=DailyBotClient)
    if body_name is None:
        client.get_organization.side_effect = APIError(500, "boom")
    else:
        client.get_organization.return_value = fixture_body(body_name)
    return client


class TestChatTargets:
    def test_raw_targets_never_read_the_organization(self) -> None:
        client: MagicMock = _org_client("organization_legacy_200")
        payload: dict[str, Any] = {"target_channels": ["C0", "19:abc@thread.tacv2"]}
        check_chat_channel_references(client, payload)
        client.get_organization.assert_not_called()
        assert payload == {"target_channels": ["C0", "19:abc@thread.tacv2"]}

    def test_qualified_targets_pass_when_platforms_are_served(self) -> None:
        client: MagicMock = _org_client("organization_chat_platforms_no_plan_200")
        payload: dict[str, Any] = {
            "target_channels": ["slack:C0", {"id": f"{PLATFORM_ID}:C1", "thread": "1.2"}]
        }
        check_chat_channel_references(client, payload)
        assert payload["target_channels"] == [
            "slack:C0",
            {"id": f"{PLATFORM_ID}:C1", "thread": "1.2"},
        ]
        client.get_organization.assert_called_once()

    def test_qualified_targets_stop_when_platforms_are_not_served(self) -> None:
        client: MagicMock = _org_client("organization_legacy_200")
        with pytest.raises(click.UsageError) as caught:
            check_chat_channel_references(client, {"target_channels": ["slack:C0"]})
        assert "C0" in str(caught.value.message)

    def test_an_unreadable_organization_leaves_the_decision_to_the_server(self) -> None:
        client: MagicMock = _org_client(None)
        payload: dict[str, Any] = {"target_channels": ["slack:C0"]}
        check_chat_channel_references(client, payload)
        assert payload["target_channels"] == ["slack:C0"]

    def test_dailybot_is_not_a_chat_send_destination(self) -> None:
        client: MagicMock = _org_client("organization_native_200")
        with pytest.raises(click.UsageError) as caught:
            check_chat_channel_references(client, {"target_channels": ["dailybot:C1"]})
        assert "Dailybot Chat" in str(caught.value.message)
        client.get_organization.assert_not_called()


class TestChatSendCommand:
    @staticmethod
    def _send(*args: str, org: str) -> tuple[Result, MagicMock]:
        client: DailyBotClient = DailyBotClient(
            api_url="https://api.example.com", api_key="test-key"
        )
        sent: MagicMock = MagicMock()
        sent.status_code = 200
        sent.headers = {}
        sent.json.return_value = {"bot_message_id": "1"}
        with (
            patch(
                "dailybot_cli.commands.chat._resolve_agent_context", return_value=("A", client, {})
            ),
            patch("dailybot_cli.api_client.httpx.get", return_value=fixture_response(org)),
            patch("dailybot_cli.api_client.httpx.request", return_value=sent) as request,
        ):
            result: Result = CliRunner().invoke(cli, ["chat", "send", *args, "-m", "hi"])
        return result, request

    def test_a_qualified_channel_is_sent_verbatim(self) -> None:
        result, request = self._send(
            "-c", "msteams:19:abc@thread.tacv2", org="organization_chat_platforms_no_plan_200"
        )
        assert result.exit_code == 0, result.output
        assert request.call_args.kwargs["json"]["target_channels"] == [
            "msteams:19:abc@thread.tacv2"
        ]

    def test_a_raw_teams_id_is_sent_unchanged(self) -> None:
        result, request = self._send("-c", "19:abc@thread.tacv2", org="organization_legacy_200")
        assert result.exit_code == 0, result.output
        assert request.call_args.kwargs["json"]["target_channels"] == ["19:abc@thread.tacv2"]

    def test_a_qualified_channel_on_an_org_without_platforms_is_refused_locally(self) -> None:
        result, request = self._send("-c", "slack:C0", org="organization_legacy_200")
        assert result.exit_code == 2
        request.assert_not_called()

    def test_dailybot_prefix_is_refused(self) -> None:
        result, request = self._send("-c", "dailybot:C0", org="organization_native_200")
        assert result.exit_code == 2
        request.assert_not_called()

    @pytest.mark.parametrize(
        "fixture,code,exit_code",
        [
            ("channel_reference_ambiguous_409", "channel_reference_ambiguous", 1),
            ("channel_reference_unknown_400", "channel_reference_unknown", 2),
        ],
    )
    def test_the_server_codes_render_by_code(self, fixture: str, code: str, exit_code: int) -> None:
        client: DailyBotClient = DailyBotClient(
            api_url="https://api.example.com", api_key="test-key"
        )
        with (
            patch(
                "dailybot_cli.commands.chat._resolve_agent_context", return_value=("A", client, {})
            ),
            patch("dailybot_cli.api_client.httpx.request", return_value=fixture_response(fixture)),
        ):
            result: Result = CliRunner().invoke(cli, ["chat", "send", "-c", "C0", "-m", "hi"])
        assert result.exit_code == exit_code
        assert "dailybot org" in " ".join(result.output.split())


class TestTasksResolver:
    @staticmethod
    def _client(org: str | None, channels: list[dict[str, Any]]) -> MagicMock:
        client: MagicMock = _org_client(org)
        client.search_channels.return_value = PaginatedResult(
            results=channels, count=len(channels), next=None, previous=None
        )
        return client

    def test_a_raw_id_resolves_as_today(self) -> None:
        client: MagicMock = self._client(
            "organization_legacy_200", [{"external_id": "C0", "name": "general", "type": "channel"}]
        )
        assert resolve_channel(client, "C0") == {
            "external_id": "C0",
            "name": "general",
            "type": "channel",
        }
        client.get_organization.assert_not_called()

    def test_a_qualified_id_keeps_its_qualifier(self) -> None:
        client: MagicMock = self._client(
            "organization_chat_platforms_no_plan_200",
            [{"external_id": "C0", "name": "general", "type": "channel"}],
        )
        assert resolve_channel(client, "slack:C0") == {
            "external_id": "slack:C0",
            "name": "general",
            "type": "channel",
        }

    def test_a_qualified_id_the_list_does_not_show_goes_to_the_server(self) -> None:
        client: MagicMock = self._client("organization_chat_platforms_no_plan_200", [])
        resolved: dict[str, str] = resolve_channel(client, f"{PLATFORM_ID}:C9")
        assert resolved["external_id"] == f"{PLATFORM_ID}:C9"

    def test_a_qualified_id_without_platforms_is_refused(self) -> None:
        client: MagicMock = self._client("organization_legacy_200", [])
        with pytest.raises(click.UsageError):
            resolve_channel(client, "slack:C0")


def test_resolve_channel_refuses_dailybot_like_chat_send() -> None:
    """AI review fp=d08a1001: routes, reports and notifications refuse `dailybot:` too."""
    client: MagicMock = _org_client("organization_native_200")
    with pytest.raises(click.UsageError) as from_resolver:
        resolve_channel(client, "dailybot:C1")
    with pytest.raises(click.UsageError) as from_chat:
        check_chat_channel_references(client, {"target_channels": ["dailybot:C1"]})
    assert from_resolver.value.message == from_chat.value.message
    client.search_channels.assert_not_called()
