"""The product is called Plan and lives under /v1/plan/ (no /v1/plan/ fallback)."""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import TASKS_BASE_PATH, DailyBotClient
from dailybot_cli.main import cli

API_URL: str = "https://api.example.test"


def _response(payload: Any) -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = 200
    mock.json.return_value = payload
    mock.headers = {}
    return mock


def test_the_base_path_is_v1_plan() -> None:
    assert TASKS_BASE_PATH == "/v1/plan/"


@pytest.mark.parametrize(
    ("call", "suffix"),
    [
        (lambda c: c.get_task("ENG-1"), "tasks/ENG-1/"),
        (lambda c: c.get_tasks_pulse(), "pulse/"),
        (lambda c: c.get_tasks_timeline(), "timeline/"),
        (lambda c: c.get_notifications_catalog(), "notifications/catalog/"),
        (lambda c: c.get_my_briefing(), "me/briefing/"),
    ],
)
def test_reads_go_to_the_plan_root(call: Any, suffix: str) -> None:
    client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
    with patch("dailybot_cli.api_client.httpx.get", return_value=_response({})) as get:
        call(client)
    assert get.call_args.args[0] == f"{API_URL}/v1/plan/{suffix}"


def test_no_request_is_built_under_the_old_root() -> None:
    client: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
    assert "/v1/" + "tasks/" not in client._tasks_url("tasks/")


def test_the_beta_notice_names_the_product_plan() -> None:
    out: str = CliRunner().invoke(cli, ["plan", "tasks", "--help"]).output
    assert "Dailybot Plan" in out


def test_the_not_enabled_message_names_the_product_plan() -> None:
    from dailybot_cli.api_client import APIError
    from dailybot_cli.commands.public_api_helpers import resolve_error_message

    message: str = resolve_error_message(
        APIError(402, "x", code="plan_upgrade_required"), tasks_surface=True
    )
    assert "Dailybot Plan" in message
