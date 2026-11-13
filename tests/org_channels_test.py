"""`dailybot org` shows the organization's chat platforms (PLAN_002 T-org-channels, L74).

`/v1/organization/` appends `has_external_chat_platform`, `primary_chat_platform` and
`chat_platforms` (ChatPlatformSummary items) only when gated on. Missing keys mean
"unavailable", never "no platforms": the output is then byte-identical to today.
"""

import copy
import json
from typing import Any
from unittest.mock import MagicMock

import click
import pytest
from click.testing import CliRunner, Result

from dailybot_cli.commands.identity import _ORG_FIELDS
from dailybot_cli.display import print_detail_panel
from dailybot_cli.main import cli
from tests.wire_fixture_loader import fixture_body

PLATFORM_KEYS: tuple[str, ...] = (
    "has_external_chat_platform",
    "primary_chat_platform",
    "chat_platforms",
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock: MagicMock = MagicMock()
    monkeypatch.setattr("dailybot_cli.commands.public_api_helpers.get_agent_auth", lambda: "tok")
    monkeypatch.setattr(
        "dailybot_cli.commands.public_api_helpers.DailyBotClient", lambda *a, **k: mock
    )
    return mock


def _todays_rendering(data: dict[str, Any]) -> str:
    @click.command()
    def render() -> None:
        print_detail_panel("Organization", data, _ORG_FIELDS)

    return CliRunner().invoke(render).output


class TestUnavailable:
    def test_a_legacy_payload_renders_byte_identical(self, client: MagicMock) -> None:
        data: dict[str, Any] = fixture_body("organization_legacy_200")
        client.get_organization.return_value = copy.deepcopy(data)
        result: Result = CliRunner().invoke(cli, ["org"])
        assert result.exit_code == 0
        assert result.output == _todays_rendering(data)

    def test_missing_keys_never_say_no_platforms(self, client: MagicMock) -> None:
        client.get_organization.return_value = fixture_body("organization_legacy_200")
        result: Result = CliRunner().invoke(cli, ["org"])
        assert "chat platform" not in result.output.lower()


class TestAvailable:
    def test_a_connected_org_lists_its_platforms(self, client: MagicMock) -> None:
        data: dict[str, Any] = fixture_body("organization_chat_platforms_no_plan_200")
        client.get_organization.return_value = data
        result: Result = CliRunner().invoke(cli, ["org"])
        assert result.exit_code == 0
        summary: dict[str, Any] = data["chat_platforms"][0]
        assert "Chat platforms" in result.output
        assert summary["display_name"] in result.output
        assert "Slack" in result.output
        assert "connected" in result.output
        assert summary["id"] in result.output
        assert "primary" in result.output.lower()
        assert result.output.startswith(_todays_rendering(data))

    def test_a_native_org_says_no_external_platform(self, client: MagicMock) -> None:
        client.get_organization.return_value = fixture_body("organization_native_200")
        result: Result = CliRunner().invoke(cli, ["org"])
        assert result.exit_code == 0
        assert "Dailybot" in result.output
        assert "no external chat platform" in result.output.lower()

    def test_status_needs_reauth_is_shown(self, client: MagicMock) -> None:
        data: dict[str, Any] = copy.deepcopy(
            fixture_body("organization_chat_platforms_no_plan_200")
        )
        data["chat_platforms"][0]["status"] = "needs_reauth"
        client.get_organization.return_value = data
        result: Result = CliRunner().invoke(cli, ["org"])
        assert "needs_reauth" in result.output or "reconnect" in result.output.lower()

    def test_names_are_escaped_and_neutralized(self, client: MagicMock) -> None:
        data: dict[str, Any] = copy.deepcopy(
            fixture_body("organization_chat_platforms_no_plan_200")
        )
        data["chat_platforms"][0]["display_name"] = "[bold red]evil[/bold red]\x1b[2J"
        client.get_organization.return_value = data
        result: Result = CliRunner().invoke(cli, ["org"])
        assert "[bold red]evil[/bold red]" in result.output
        assert "\x1b[2J" not in result.output

    def test_json_passes_the_keys_through(self, client: MagicMock) -> None:
        data: dict[str, Any] = fixture_body("organization_native_200")
        client.get_organization.return_value = copy.deepcopy(data)
        result: Result = CliRunner().invoke(cli, ["org", "--json"])
        assert result.exit_code == 0
        out: dict[str, Any] = json.loads(result.output)
        for key in PLATFORM_KEYS:
            assert out[key] == data[key]
