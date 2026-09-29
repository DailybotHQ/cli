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
    ["project", "create", "--name", "X"],
    ["project", "update", P, "--name", "X"],
    ["project", "archive", P, "--yes"],
    ["project", "restore", P],
    [
        "board",
        "create",
        "--project",
        "00000000-0000-0000-0000-000000000002",
        "--key",
        "DSN",
        "--name",
        "X",
    ],
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
    ["project", "attach", P, __file__],
    ["project", "attachment", "delete", P, S, "--yes"],
    ["goal", "attach", G, __file__],
    ["goal", "attachment", "delete", G, S, "--yes"],
]

# Person doors that change who is notified or read a project's saved views. A
# personal API key is its person here too; only the server refuses a key.
PERSON_COMMANDS: list[list[str]] = [
    ["task", "participants", "add", T, "--user", U],
    ["task", "participants", "remove", T, U, "--yes"],
    ["task", "mute", T],
    ["task", "unmute", T],
    ["project", "views", P],
    ["project", "view", "save", P, "--file", "-", "--if-match", "etag"],
]

# The remaining person-shaped doors ("my X", pins, views, labels, watch).
OPEN_TO_PERSONAL_KEY_COMMANDS: list[list[str]] = [
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
    ["project", "members", P],
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
