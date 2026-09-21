"""What the CLI does when Tasks is switched off for the organization.

Every Tasks door except `entitlements` sits behind a **per-organization rollout**.
Three separate levers can refuse, they mean different things, and telling them
apart is the whole point — a caller who is told to upgrade a plan when the fix is
"a workspace admin enables Tasks" spends money that changes nothing.

| Lever | Status | Code | CLI exit |
| --- | --- | --- | --- |
| Tasks off for the org | 402 | `plan_upgrade_required` | 4 |
| Board cap reached | 402 | `task_boards_limit_reached` | 4 |
| Writes switched off during an incident | 503 | `feature_temporarily_read_only` | 6 |

And permission wins over entitlement: a guest or a scopeless key is refused on
those grounds first, so neither learns the organization's entitlement state.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    EXIT_PERMISSION_DENIED,
    EXIT_RATE_LIMITED,
    resolve_error_message,
)
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


def _tasks_off(**extra: Any) -> APIError:
    return APIError(
        status_code=402,
        detail="Tasks is not enabled for this workspace yet.",
        code="plan_upgrade_required",
        extra=extra or None,
    )


def _invoke(runner: CliRunner, client: MagicMock, argv: list[str], module: str) -> Any:
    lookup: str = "project" if module == "goal" else module
    with (
        patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
        patch(f"dailybot_cli.commands.{lookup}.get_token", return_value="b"),
    ):
        return runner.invoke(cli, argv)


class TestTasksOffIsDiagnosedCorrectly:
    """The gate is a rollout, not a plan scope, and not a credential problem.

    The code is spelled `plan_upgrade_required`, which is misleading: Tasks is
    deliberately absent from the plan's feature set, so upgrading alone may not
    open it. The server's own body names **both** remedies — a workspace admin
    enables it, or the plan is upgraded — and the CLI has to name both too.
    """

    @pytest.mark.parametrize(
        ("argv", "module", "door"),
        [
            (["tasks", "status"], "tasks", "get_tasks_pulse"),
            (["board", "list"], "board", "list_boards"),
            (["task", "list"], "task", "list_tasks"),
            (["project", "list"], "project", "list_projects"),
            (["goal", "list"], "goal", "list_goals"),
        ],
    )
    def test_every_door_refuses_with_the_documented_exit(
        self, runner: CliRunner, client: MagicMock, argv: list[str], module: str, door: str
    ) -> None:
        getattr(client, door).side_effect = _tasks_off()
        result = _invoke(runner, client, argv, module)
        assert result.exit_code == EXIT_PERMISSION_DENIED

    def test_it_names_the_organization_switch(self) -> None:
        message: str = resolve_error_message(_tasks_off(), tasks_surface=True)
        assert "not enabled for this organization" in message

    def test_it_names_both_remedies(self) -> None:
        message: str = resolve_error_message(_tasks_off(), tasks_surface=True)
        assert "workspace admin" in message
        assert "upgrade" in message.lower()

    def test_it_does_not_blame_the_credential(self) -> None:
        # `dailybot login`, another API key and an admin role all change nothing.
        # Saying otherwise sends the reader on a hunt that cannot succeed.
        message: str = resolve_error_message(_tasks_off(), tasks_surface=True)
        assert "signing in again will not change it" in message

    def test_it_points_at_the_door_that_answers(self) -> None:
        message: str = resolve_error_message(_tasks_off(), tasks_surface=True)
        assert "tasks entitlements" in message

    def test_the_upgrade_url_is_surfaced(self) -> None:
        message: str = resolve_error_message(
            _tasks_off(upgrade_url="/settings/billing"), tasks_surface=True
        )
        assert "/settings/billing" in message

    def test_off_the_tasks_surface_the_shared_message_stands(self) -> None:
        # The code is shared with the agent-report surface, where the free-plan
        # allowlist sentence is correct.
        assert "agent reports" in resolve_error_message(_tasks_off())


class TestTheWritesKillSwitchIsTransient:
    """`feature_temporarily_read_only` is an incident lever, not an entitlement.

    Unmapped it exited 1 with the raw server prose — an unknown failure, which is
    the one verdict that invites an agent to retry hard against a system somebody
    has deliberately put into read-only.
    """

    def _switched_off(self) -> APIError:
        return APIError(
            status_code=503,
            detail="Tasks writes are temporarily disabled.",
            code="feature_temporarily_read_only",
        )

    def test_it_exits_with_the_back_off_code(self, runner: CliRunner, client: MagicMock) -> None:
        client.create_board.side_effect = self._switched_off()
        result = _invoke(runner, client, ["board", "create", "-n", "x"], "board")
        assert result.exit_code == EXIT_RATE_LIMITED

    def test_it_does_not_surface_raw_server_prose(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.create_board.side_effect = self._switched_off()
        result = _invoke(runner, client, ["board", "create", "-n", "x"], "board")
        assert "Tasks writes are temporarily disabled." not in result.stderr

    def test_it_says_reads_still_work(self) -> None:
        message: str = resolve_error_message(self._switched_off(), tasks_surface=True)
        assert "Reads still answer" in message

    def test_it_says_not_your_permissions(self) -> None:
        message: str = resolve_error_message(self._switched_off(), tasks_surface=True)
        assert "not your permissions" in message


class TestPermissionWinsOverEntitlement:
    """A guest never learns the organization's entitlement state.

    The server runs permissions before entitlement, so a guest with Tasks also off
    is told `guest_not_allowed`, not `plan_upgrade_required`. The CLI dispatches on
    `code`, so it inherits that ordering — this pins that it does not second-guess
    it by inferring an entitlement problem from the status.
    """

    def test_a_guest_gets_the_role_message(self, runner: CliRunner, client: MagicMock) -> None:
        client.list_boards.side_effect = APIError(
            status_code=403, detail="no", code="guest_not_allowed"
        )
        result = _invoke(runner, client, ["board", "list"], "board")
        collapsed: str = " ".join(result.stderr.split())
        assert "Guest accounts" in collapsed
        assert "not enabled for this organization" not in collapsed

    def test_a_scopeless_key_gets_the_scope_message(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_boards.side_effect = APIError(
            status_code=403,
            detail="no",
            code="insufficient_scope",
            extra={"required_scope": "tasks:read"},
        )
        result = _invoke(runner, client, ["board", "list"], "board")
        collapsed: str = " ".join(result.stderr.split())
        assert "tasks:read" in collapsed
        assert "not enabled for this organization" not in collapsed


class TestEntitlementsIsTheDoorThatAlwaysAnswers:
    """It opts out of the gate, so it reports state instead of refusing.

    That is what makes "check before you try" possible: every other door only
    tells you the gate is closed by closing on you.
    """

    def test_it_reports_disabled_without_failing(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_tasks_entitlements.return_value = {
            "enabled": False,
            "reason": "not rolled out to this organization",
            "boards": {"used": 0, "limit": 0},
            "labels": {"enabled": False},
        }
        with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
            result = runner.invoke(cli, ["tasks", "entitlements"])
        assert result.exit_code == 0
        assert "False" in result.stdout or "false" in result.stdout

    def test_the_reason_reaches_the_reader(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_tasks_entitlements.return_value = {
            "enabled": False,
            "reason": "not rolled out to this organization",
        }
        with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
            result = runner.invoke(cli, ["tasks", "entitlements"])
        assert "rolled out" in " ".join(result.stdout.split())


class TestTheDocumentedContractMatches:
    """The three levers must read the same way in the code and in the reference."""

    def test_the_reference_explains_the_rollout(self) -> None:
        import pathlib

        repo: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent
        text: str = (repo / "docs/API_REFERENCE.md").read_text()
        assert "switched on per organization" in text
        assert "feature_temporarily_read_only" in text
        # The misleading half of the code name is called out explicitly.
        assert "not a plan scope" in text
