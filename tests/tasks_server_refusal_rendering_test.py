"""The server alone refuses a credential on Tasks; the CLI renders its answer.

A personal API key is its person on every door, so the CLI never refuses a key
before the request. When the server refuses an agent or organization key, or a
guest, the exit code and the `--json` envelope must still tell the caller which
fix applies. All HTTP is mocked (rule 7).
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    EXIT_NOT_AUTHENTICATED,
    EXIT_PERMISSION_DENIED,
)
from dailybot_cli.main import cli

PROJECT: str = "00000000-0000-0000-0000-000000000002"


def _invoke(module: str, argv: list[str], exc: APIError) -> Any:
    client: MagicMock = MagicMock(spec=DailyBotClient)
    client.create_project.side_effect = exc
    with (
        patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
        patch("dailybot_cli.commands.public_api_helpers.get_person_token", return_value=None),
    ):
        return CliRunner().invoke(cli, argv)


class TestAnAgentKeyRefusedByTheServer:
    def test_structure_write_exits_four_with_person_guidance(self) -> None:
        exc = APIError(
            403, "no", code="insufficient_scope", extra={"required_scope": "tasks:admin"}
        )
        result = _invoke("project", ["project", "create", "--name", "X", "--json"], exc)
        assert result.exit_code == EXIT_PERMISSION_DENIED, result.output
        body: dict[str, Any] = json.loads(result.output)
        assert body["code"] == "insufficient_scope"
        flat: str = " ".join(body["message"].lower().split())
        assert "personal api key" in flat
        assert "grant" not in flat

    def test_person_door_exits_three(self) -> None:
        exc = APIError(400, "no", code="actor_required")
        result = _invoke("project", ["project", "create", "--name", "X", "--json"], exc)
        assert result.exit_code == EXIT_NOT_AUTHENTICATED, result.output
        assert "personal API key" in " ".join(json.loads(result.output)["message"].split())


class TestAGuestRefusedByTheServer:
    @pytest.mark.parametrize("argv", [["project", "create", "--name", "X", "--json"]])
    def test_guest_is_a_role_limit(self, argv: list[str]) -> None:
        exc = APIError(403, "no", code="guest_not_allowed")
        result = _invoke("project", argv, exc)
        assert result.exit_code == EXIT_PERMISSION_DENIED, result.output
        assert "role" in json.loads(result.output)["message"].lower()
