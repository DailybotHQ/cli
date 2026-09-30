"""`attachment rename` on task, comment, project and goal attachments (same PATCH door as boards)."""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import DailyBotClient
from dailybot_cli.main import cli

API_URL: str = "http://test-api.example.com"
BASE: str = f"{API_URL}/v1/plan/"
TASK: str = "ENG-142"
COMMENT: str = "00000000-0000-0000-0000-000000000007"
PROJECT: str = "00000000-0000-0000-0000-000000000002"
GOAL: str = "00000000-0000-0000-0000-000000000003"
ATT: str = "00000000-0000-0000-0000-000000000009"

CASES: list[tuple[str, str, tuple[str, ...], list[str], str]] = [
    (
        "task",
        "rename_task_attachment",
        (TASK, ATT),
        ["task", "attachment", "rename", TASK, ATT],
        f"tasks/{TASK}",
    ),
    (
        "task",
        "rename_comment_attachment",
        (TASK, COMMENT, ATT),
        ["task", "comment-attachment", "rename", TASK, COMMENT, ATT],
        f"tasks/{TASK}/comments/{COMMENT}",
    ),
    (
        "project",
        "rename_project_attachment",
        (PROJECT, ATT),
        ["project", "attachment", "rename", PROJECT, ATT],
        f"projects/{PROJECT}",
    ),
    (
        "goal",
        "rename_goal_attachment",
        (GOAL, ATT),
        ["goal", "attachment", "rename", GOAL, ATT],
        f"goals/{GOAL}",
    ),
]


def _response(payload: Any) -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = 200
    mock.json.return_value = payload
    mock.headers = {}
    mock.content = b""
    return mock


@pytest.mark.parametrize(("module", "method", "ids", "argv", "parent"), CASES)
def test_the_client_patches_the_attachment(
    module: str, method: str, ids: tuple[str, ...], argv: list[str], parent: str
) -> None:
    real: DailyBotClient = DailyBotClient(api_url=API_URL, token="test-token")
    with patch(
        "dailybot_cli.api_client.httpx.patch", return_value=_response({"uuid": ATT})
    ) as patched:
        getattr(real, method)(*ids, filename="b.txt")
    assert patched.call_args.args[0] == f"{BASE}{parent}/attachments/{ATT}/"
    assert patched.call_args.kwargs["json"] == {"filename": "b.txt"}


@pytest.mark.parametrize(("module", "method", "ids", "argv", "parent"), CASES)
def test_the_command_sends_the_new_name(
    module: str, method: str, ids: tuple[str, ...], argv: list[str], parent: str
) -> None:
    client: MagicMock = MagicMock(spec=DailyBotClient)
    getattr(client, method).return_value = {"uuid": ATT, "filename": "b.txt"}
    with patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client):
        result = CliRunner().invoke(cli, ["plan", *argv, "b.txt", "--json"])
    assert result.exit_code == 0, result.output
    getattr(client, method).assert_called_once_with(*ids, filename="b.txt")
