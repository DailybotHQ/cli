"""Every door the API refuses to an organization API key is refused before the request.

The server's runtime rule has two lists. The 25 `tasks:admin` doors refuse any
organization API key with `403 insufficient_scope`; the scope cannot even be
stored on a key. The 34 person-only doors refuse a key because the answer is
about a person. The CLI mirrors both lists, so a key-only session never spends
a request on a door that cannot succeed. An admin door exits 4, like the
server's 403. A person door exits 3, because the fix is to sign in.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    EXIT_NOT_AUTHENTICATED,
    EXIT_PERMISSION_DENIED,
)
from dailybot_cli.main import cli

B: str = "00000000-0000-0000-0000-000000000001"
P: str = "00000000-0000-0000-0000-000000000002"
G: str = "00000000-0000-0000-0000-000000000003"
U: str = "00000000-0000-0000-0000-000000000004"
S: str = "00000000-0000-0000-0000-000000000005"
S2: str = "00000000-0000-0000-0000-000000000006"
V: str = "00000000-0000-0000-0000-000000000013"
ITEM: str = "00000000-0000-0000-0000-000000000010"
T: str = "ENG-142"

# The 25 `tasks:admin` doors, by the CLI command that reaches each.
# (PATCH boards/{b}/members/{u}/ and PATCH projects/{p}/members/{u}/ have no command.)
ADMIN_COMMANDS: list[list[str]] = [
    ["project", "create", "--name", "X"],
    ["project", "update", P, "--name", "X"],
    ["project", "archive", P, "--yes"],
    ["project", "restore", P],
    ["board", "create", "--name", "X"],
    ["board", "update", B, "--name", "X"],
    ["board", "archive", B, "--yes"],
    ["board", "restore", B],
    ["board", "state", "create", B, "--name", "X", "--category", "todo"],
    ["board", "state", "update", B, S, "--name", "X"],
    ["board", "state", "archive", B, S, "--migrate-to", S2, "--yes"],
    ["board", "state", "restore", B, S],
    ["board", "state", "reorder", B, S, S2],
    ["board", "member", "add", B, U],
    ["board", "member", "remove", B, U, "--yes"],
    ["project", "member", "add", P, "--user", U],
    ["project", "member", "remove", P, U, "--yes"],
    ["goal", "create", "--name", "X", "--period-start", "2026-10-01", "--period-end", "2026-12-31"],
    ["goal", "update", G, "--name", "X"],
    ["goal", "archive", G, "--yes"],
    ["goal", "restore", G],
    ["goal", "link", G, P],
    ["goal", "unlink", G, P, "--yes"],
]

# The person-only doors that have a CLI command.
PERSON_COMMANDS: list[list[str]] = [
    ["board", "views", B],
    ["board", "view", "save", B, "--file", "-", "--if-match", "etag"],
    ["tasks", "view", "get", V],
    ["tasks", "view", "update", V, "--name", "X"],
    ["tasks", "view", "delete", V, "--yes"],
    ["tasks", "mine"],
    ["tasks", "counts"],
    ["tasks", "inbox"],
    ["tasks", "inbox-read-all"],
    ["tasks", "inbox-read", ITEM],
    ["tasks", "inbox-unread"],
    ["board", "mentionables", B],
    ["task", "watch", T],
    ["task", "unwatch", T],
    ["tasks", "cursor"],
    ["tasks", "favorites"],
    ["board", "star", B],
    ["board", "unstar", B],
    ["tasks", "view", "star", V],
    ["tasks", "view", "unstar", V],
    ["board", "labels", B],
    ["board", "label", "create", B, "--name", "bug"],
    ["task", "participants", "list", T],
    ["task", "participants", "add", T, "--user", U],
    ["task", "participants", "remove", T, U, "--yes"],
    ["task", "mute", T],
    ["task", "unmute", T],
    ["project", "views", P],
    ["project", "view", "save", P, "--file", "-", "--if-match", "etag"],
    ["project", "members", P],
]

MODULES: tuple[str, ...] = ("task", "tasks", "board", "project", "goal")


def _invoke_with_key_only(argv: list[str]) -> tuple[Any, MagicMock]:
    client: MagicMock = MagicMock(spec=DailyBotClient)
    patches: list[Any] = []
    for module in MODULES:
        patches.append(patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client))
    patches.append(patch("dailybot_cli.commands._favorites.get_token", return_value=None))
    for module in MODULES:
        target: str = f"dailybot_cli.commands.{module}.get_token"
        patches.append(patch(target, return_value=None, create=True))
    for active in patches:
        active.start()
    try:
        result: Any = CliRunner().invoke(cli, [*argv, "--json"], input="[]")
    finally:
        for active in patches:
            active.stop()
    return result, client


@pytest.mark.parametrize("argv", ADMIN_COMMANDS, ids=lambda a: " ".join(a[:3]))
def test_an_admin_door_refuses_a_key_before_the_request(argv: list[str]) -> None:
    result, client = _invoke_with_key_only(argv)
    assert result.exit_code == EXIT_PERMISSION_DENIED, result.output
    assert client.mock_calls == [], client.mock_calls
    assert json.loads(result.output)["code"] == "insufficient_scope"


@pytest.mark.parametrize("argv", PERSON_COMMANDS, ids=lambda a: " ".join(a[:4]))
def test_a_person_door_refuses_a_key_before_the_request(argv: list[str]) -> None:
    result, client = _invoke_with_key_only(argv)
    assert result.exit_code == EXIT_NOT_AUTHENTICATED, result.output
    assert client.mock_calls == [], client.mock_calls


def test_the_lists_match_the_server_counts() -> None:
    # 25 admin doors, minus the two member-role PATCHes with no command.
    assert len(ADMIN_COMMANDS) == 23
