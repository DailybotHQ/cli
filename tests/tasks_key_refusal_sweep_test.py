"""No Tasks door is refused before the request because the credential is a key.

A personal API key (bound to a person) is that person on every Tasks door,
structure and membership included, exactly like a login session. Only the
server can tell a personal key from an agent or organization key, so the CLI
sends the request and renders the server's answer: `actor_required` exits 3,
`insufficient_scope` / `guest_not_allowed` exit 4.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import DailyBotClient
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

# The 25 `tasks:admin` doors (structure and membership), by the CLI command that
# reaches each. A personal API key holds `tasks:admin` like its person's session.
# (PATCH boards/{b}/members/{u}/ and PATCH projects/{p}/members/{u}/ have no command.)
ADMIN_COMMANDS: list[list[str]] = [
    ["plan", "project", "create", "--name", "X"],
    ["plan", "project", "update", P, "--name", "X"],
    ["plan", "project", "archive", P, "--yes"],
    ["plan", "project", "restore", P],
    [
        "plan",
        "board",
        "create",
        "--project",
        "00000000-0000-0000-0000-000000000002",
        "--key",
        "DSN",
        "--name",
        "X",
    ],
    ["plan", "board", "update", B, "--name", "X"],
    ["plan", "board", "archive", B, "--yes"],
    ["plan", "board", "restore", B],
    ["plan", "board", "state", "create", B, "--name", "X", "--category", "todo"],
    ["plan", "board", "state", "update", B, S, "--name", "X"],
    ["plan", "board", "state", "archive", B, S, "--migrate-to", S2, "--yes"],
    ["plan", "board", "state", "restore", B, S],
    ["plan", "board", "state", "reorder", B, S, S2],
    ["plan", "board", "member", "add", B, U],
    ["plan", "board", "member", "remove", B, U, "--yes"],
    ["plan", "project", "member", "add", P, "--user", U],
    ["plan", "project", "member", "remove", P, U, "--yes"],
    [
        "plan",
        "goal",
        "create",
        "--name",
        "X",
        "--period-start",
        "2026-10-01",
        "--period-end",
        "2026-12-31",
    ],
    ["plan", "goal", "update", G, "--name", "X"],
    ["plan", "goal", "archive", G, "--yes"],
    ["plan", "goal", "restore", G],
    ["plan", "goal", "link", G, P],
    ["plan", "goal", "unlink", G, P, "--yes"],
    ["plan", "project", "attach", P, __file__],
    ["plan", "project", "attachment", "delete", P, S, "--yes"],
    ["plan", "goal", "attach", G, __file__],
    ["plan", "goal", "attachment", "delete", G, S, "--yes"],
]

# Person doors that change who is notified or read a project's saved views. A
# personal API key is its person here too; only the server refuses a key.
PERSON_COMMANDS: list[list[str]] = [
    ["plan", "task", "participants", "add", T, "--user", U],
    ["plan", "task", "participants", "remove", T, U, "--yes"],
    ["plan", "task", "mute", T],
    ["plan", "task", "unmute", T],
    ["plan", "project", "views", P],
    ["plan", "project", "view", "save", P, "--file", "-", "--if-match", "etag"],
]

# The remaining person-shaped doors ("my X", pins, views, labels, watch).
OPEN_TO_PERSONAL_KEY_COMMANDS: list[list[str]] = [
    ["plan", "board", "views", B],
    ["plan", "board", "view", "save", B, "--file", "-", "--if-match", "etag"],
    ["plan", "tasks", "view", "get", V],
    ["plan", "tasks", "view", "update", V, "--name", "X"],
    ["plan", "tasks", "view", "delete", V, "--yes"],
    ["plan", "tasks", "mine"],
    ["plan", "tasks", "counts"],
    ["plan", "tasks", "inbox"],
    ["plan", "tasks", "inbox-read-all"],
    ["plan", "tasks", "inbox-read", ITEM],
    ["plan", "tasks", "inbox-unread"],
    ["plan", "board", "mentionables", B],
    ["plan", "task", "watch", T],
    ["plan", "task", "unwatch", T],
    ["plan", "tasks", "cursor"],
    ["plan", "tasks", "favorites"],
    ["plan", "board", "star", B],
    ["plan", "board", "unstar", B],
    ["plan", "tasks", "view", "star", V],
    ["plan", "tasks", "view", "unstar", V],
    ["plan", "board", "labels", B],
    ["plan", "board", "label", "create", B, "--name", "bug"],
    ["plan", "task", "participants", "list", T],
    ["plan", "project", "members", P],
]

MODULES: tuple[str, ...] = ("task", "tasks", "board", "project", "goal")


def _invoke_with_key_only(argv: list[str]) -> tuple[Any, MagicMock]:
    client: MagicMock = MagicMock(spec=DailyBotClient)
    patches: list[Any] = []
    for module in MODULES:
        patches.append(patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client))
    for module in MODULES:
        target: str = f"dailybot_cli.commands.{module}.get_person_token"
        patches.append(patch(target, return_value=None, create=True))
    for active in patches:
        active.start()
    try:
        result: Any = CliRunner().invoke(cli, [*argv, "--json"], input="[]")
    finally:
        for active in patches:
            active.stop()
    return result, client


@pytest.mark.parametrize(
    "argv",
    ADMIN_COMMANDS + PERSON_COMMANDS + OPEN_TO_PERSONAL_KEY_COMMANDS,
    ids=lambda a: " ".join(a[:4]),
)
def test_every_door_sends_the_request_for_a_key(argv: list[str]) -> None:
    # A personal API key is its person on every Tasks door; the server alone
    # tells it from an agent or organization key, so the CLI never refuses first.
    _result, client = _invoke_with_key_only(argv)
    assert client.mock_calls != [], argv


def test_the_lists_match_the_server_counts() -> None:
    # 29 admin doors (25, plus attach / delete on projects and goals), minus the two
    # member-role PATCHes that have no command.
    assert len(ADMIN_COMMANDS) == 27
