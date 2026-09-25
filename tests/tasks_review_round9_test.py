"""Regression tests for the CI AI review's ninth pass on PR #85.

Seven findings, and the sharpest one is about round 8 itself: the Tasks-specific
`plan_upgrade_required` message was gated on a `door` argument that **only three
commands in the whole CLI pass**, so the misdirection it was written to fix still
reached every other Tasks door. A fix that does not fire is not a fix, and nothing
in the round-8 suite noticed because its own test supplied the `door`.

Two others are the by-now-familiar shape — round 8's idempotency-key fix applied
to `task` and not to `board` / `project` / `goal`, and the escaping rule applied
twice on the same string. Both are now structural: one reporter, one escape.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import IDEMPOTENCY_KEY_SENT_KEY, APIError, DailyBotClient
from dailybot_cli.commands._writes import IDEMPOTENCY_TTL_HOURS
from dailybot_cli.commands.public_api_helpers import resolve_error_message
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


@pytest.fixture
def real_client() -> DailyBotClient:
    return DailyBotClient(api_url="http://t.example.com", token="t", api_key="k")


def _token_patch(module: str) -> Any:
    """Patch the module's own `get_token`, where it has one.

    `goal.py` reuses `project`'s pre-flight and imports no token lookup of its own, so
    the name to patch for a goal command is `project.get_token`. Patching
    `goal.get_token` raises; patching the wrong module's would silently do nothing.
    """
    lookup: str = "project" if module == "goal" else module
    return patch(f"dailybot_cli.commands.{lookup}.get_token", return_value="b")


def _plan_refusal() -> APIError:
    return APIError(status_code=403, detail="paid plan", code="plan_upgrade_required")


class TestThePlanMessageFiresWhereItMatters:
    """Finding 1: round 8's fix was gated on an argument production rarely passes.

    Only `tasks inbox` / `mine` / `counts` pass `door=`. Every other Tasks refusal
    — `board list`, `task list`, `tasks status`, the destructive preview — reached
    `resolve_error_message` with `door=None` and got the free-plan **agent-report**
    allowlist sentence while the caller was trying to list boards.
    """

    @pytest.mark.parametrize(
        ("argv", "module", "door"),
        [
            (["board", "list"], "board", "list_boards"),
            (["task", "list"], "task", "list_tasks"),
            (["tasks", "status"], "tasks", "get_tasks_pulse"),
            (["project", "list"], "project", "list_projects"),
        ],
    )
    def test_a_tasks_door_names_tasks(
        self, runner: CliRunner, client: MagicMock, argv: list[str], module: str, door: str
    ) -> None:
        getattr(client, door).side_effect = _plan_refusal()
        with (
            patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
            _token_patch(module),
        ):
            result = runner.invoke(cli, argv)
        collapsed: str = " ".join(result.stderr.split())
        assert "Tasks" in collapsed
        assert "agent reports" not in collapsed

    def test_the_destructive_preview_path_too(self, runner: CliRunner, client: MagicMock) -> None:
        client.archive_task.side_effect = _plan_refusal()
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(cli, ["task", "archive", "t-1", "--yes"])
        assert "agent reports" not in " ".join(result.stderr.split())

    def test_off_the_tasks_surface_the_shared_message_stands(self) -> None:
        # The code is shared. Outside Tasks the agent-allowlist sentence is correct
        # and must not be replaced.
        assert "agent reports" in resolve_error_message(_plan_refusal())


class TestEveryCreateSurfacesItsKey:
    """Finding 2: round 8 taught `task` to echo the key; the containers never learned.

    `board create` minted a uuid4, printed nothing, and left the caller unable to
    perform the safe retry `docs/API_REFERENCE.md` describes. There is now one
    reporter, so a fourth copy cannot drift again.
    """

    @pytest.mark.parametrize(
        ("argv", "module", "door"),
        [
            (["board", "create", "-n", "B"], "board", "create_board"),
            (["project", "create", "-n", "P"], "project", "create_project"),
            (
                [
                    "goal",
                    "create",
                    "-n",
                    "G",
                    "--period-start",
                    "2026-10-01",
                    "--period-end",
                    "2026-12-31",
                ],
                "goal",
                "create_goal",
            ),
            (["task", "create", "-t", "T"], "task", "create_task"),
        ],
    )
    def test_the_key_is_printed(
        self, runner: CliRunner, client: MagicMock, argv: list[str], module: str, door: str
    ) -> None:
        getattr(client, door).return_value = {
            "uuid": "x",
            "name": "B",
            "title": "T",
            "_idempotency_replayed": False,
            IDEMPOTENCY_KEY_SENT_KEY: "key-123",
        }
        with (
            patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
            _token_patch(module),
        ):
            result = runner.invoke(cli, argv)
        assert "key-123" in result.stdout
        assert "--idempotency-key" in result.stdout

    def test_the_ttl_is_not_hardcoded(self, runner: CliRunner, client: MagicMock) -> None:
        client.create_board.return_value = {
            "uuid": "x",
            "name": "B",
            "_idempotency_replayed": False,
            IDEMPOTENCY_KEY_SENT_KEY: "key-123",
        }
        with (
            patch("dailybot_cli.commands.board.require_auth", return_value=client),
            patch("dailybot_cli.commands.board.get_token", return_value="b"),
        ):
            result = runner.invoke(cli, ["board", "create", "-n", "B"])
        assert f"{IDEMPOTENCY_TTL_HOURS}h" in result.stdout


class TestAPreviewCarriesNoIdempotencyKey:
    """Finding 3: dry runs sent and returned a key they have no use for.

    A preview writes nothing, so there is nothing to make idempotent. Worse, an
    agent that captured the preview's key and reused it for the real archive would
    hit `idempotency_key_payload_mismatch` — the two payloads differ.
    """

    def _ok(self) -> MagicMock:
        mock: MagicMock = MagicMock(spec=httpx.Response)
        mock.status_code = 200
        mock.json.return_value = {"operation": "task.archive", "reversible": True}
        mock.headers = {}
        return mock

    def test_no_header_is_sent(self, real_client: DailyBotClient) -> None:
        with patch("httpx.post", return_value=self._ok()) as mock_post:
            real_client.archive_task("t-1", dry_run=True)
        assert "Idempotency-Key" not in mock_post.call_args[1]["headers"]

    def test_no_key_comes_back(self, real_client: DailyBotClient) -> None:
        with patch("httpx.post", return_value=self._ok()):
            result: dict[str, Any] = real_client.archive_task("t-1", dry_run=True)
        assert IDEMPOTENCY_KEY_SENT_KEY not in result

    def test_the_real_write_still_carries_one(self, real_client: DailyBotClient) -> None:
        with patch("httpx.post", return_value=self._ok()) as mock_post:
            result = real_client.archive_task("t-1", dry_run=False)
        assert "Idempotency-Key" in mock_post.call_args[1]["headers"]
        assert result[IDEMPOTENCY_KEY_SENT_KEY]


class TestPagingDefaultFollowsTheDecorator:
    """Finding 4: `@query_options` Tasks lists returned one page and advertised --all.

    Everywhere else in the CLI — kudos, workflow, forms — "no paging flags" means
    walk every page. These commands declare `--all` but passed `spec.fetch_all`, so
    an agent that treats `board list --json` like every other list door and ignores
    `next` inventories a partial workspace.
    """

    @pytest.mark.parametrize(
        ("argv", "module", "door"),
        [
            (["board", "list"], "board", "list_boards"),
            (["project", "list"], "project", "list_projects"),
            (["goal", "list"], "goal", "list_goals"),
            (["tasks", "activity"], "tasks", "list_tasks_activity"),
            (["project", "milestones"], "project", "list_milestones"),
            (["task", "comments", "t-1"], "task", "list_task_comments"),
        ],
    )
    def test_no_flags_walks_every_page(
        self, runner: CliRunner, client: MagicMock, argv: list[str], module: str, door: str
    ) -> None:
        from dailybot_cli.api_client import PaginatedResult

        getattr(client, door).return_value = PaginatedResult(
            results=[], count=0, next=None, previous=None
        )
        with (
            patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
            _token_patch(module),
        ):
            runner.invoke(cli, argv)
        assert getattr(client, door).call_args[1]["fetch_all"] is True, argv

    @pytest.mark.parametrize(
        ("argv", "module", "door"),
        [
            (["task", "list"], "task", "list_tasks"),
            (["tasks", "search", "-q", "x"], "tasks", "search_tasks"),
            (["tasks", "inbox"], "tasks", "list_tasks_inbox"),
            (["tasks", "mine"], "tasks", "list_my_tasks"),
        ],
    )
    def test_paging_only_commands_stay_bounded(
        self, runner: CliRunner, client: MagicMock, argv: list[str], module: str, door: str
    ) -> None:
        # Their help says "one page per call". The code has to agree with it.
        from dailybot_cli.api_client import PaginatedResult

        getattr(client, door).return_value = PaginatedResult(
            results=[], count=0, next=None, previous=None
        )
        with (
            patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
            _token_patch(module),
        ):
            runner.invoke(cli, argv)
        assert getattr(client, door).call_args[1]["fetch_all"] is False, argv

    def test_an_explicit_page_still_bounds_a_walking_command(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        from dailybot_cli.api_client import PaginatedResult

        client.list_boards.return_value = PaginatedResult(
            results=[], count=0, next=None, previous=None
        )
        with patch("dailybot_cli.commands.board.require_auth", return_value=client):
            runner.invoke(cli, ["board", "list", "--page", "2"])
        assert client.list_boards.call_args[1]["fetch_all"] is False


class TestUntrustedTextIsEscapedExactlyOnce:
    """Finding 5: `present_untrusted` escaped, then `print_success` escaped again.

    A board named `x[y]` reached the terminal with visible backslashes — the data
    was reported wrong in the act of reporting it safely.
    """

    @pytest.mark.parametrize(
        ("argv", "module", "door", "field"),
        [
            (["board", "create", "-n", "x[y]"], "board", "create_board", "name"),
            (["project", "create", "-n", "x[y]"], "project", "create_project", "name"),
            (
                [
                    "goal",
                    "create",
                    "-n",
                    "x[y]",
                    "--period-start",
                    "2026-10-01",
                    "--period-end",
                    "2026-12-31",
                ],
                "goal",
                "create_goal",
                "name",
            ),
            (["task", "create", "-t", "x[y]"], "task", "create_task", "title"),
        ],
    )
    def test_no_stray_backslash(
        self,
        runner: CliRunner,
        client: MagicMock,
        argv: list[str],
        module: str,
        door: str,
        field: str,
    ) -> None:
        getattr(client, door).return_value = {field: "x[y]", "_idempotency_replayed": False}
        with (
            patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client),
            _token_patch(module),
        ):
            result = runner.invoke(cli, argv)
        assert "x[y]" in result.stdout
        assert "\\[" not in result.stdout

    def test_markup_is_still_neutralised(self, runner: CliRunner, client: MagicMock) -> None:
        # Escaping once is the requirement; escaping zero times is the other bug.
        client.create_board.return_value = {
            "name": "[bold red]urgent[/bold red]",
            "_idempotency_replayed": False,
        }
        with (
            patch("dailybot_cli.commands.board.require_auth", return_value=client),
            patch("dailybot_cli.commands.board.get_token", return_value="b"),
        ):
            result = runner.invoke(cli, ["board", "create", "-n", "x"])
        assert "[bold red]urgent" in result.stdout
        assert "Unexpected error" not in result.stderr


class TestGoalGetRendersWhatItWasAsked:
    """Finding 6: `--include projects` was accepted, sent, and rendered nowhere.

    Only `progress` reached the human path, so a caller who asked for the projects
    roll-up got no signal the selector had worked.
    """

    def test_the_projects_rollup_is_shown(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_goal.return_value = {"uuid": "g-1", "name": "Q4", "project_count": 3}
        with patch("dailybot_cli.commands.goal.require_auth", return_value=client):
            result = runner.invoke(cli, ["goal", "get", "g-1", "--include", "projects"])
        assert "Projects" in result.stdout
        assert "3" in result.stdout

    def test_an_unrequested_rollup_stays_absent(self, runner: CliRunner, client: MagicMock) -> None:
        # Absent is one of three answers and must not be rendered as zero.
        client.get_goal.return_value = {"uuid": "g-1", "name": "Q4"}
        with patch("dailybot_cli.commands.goal.require_auth", return_value=client):
            result = runner.invoke(cli, ["goal", "get", "g-1"])
        assert "Projects" not in result.stdout

    def test_json_is_unchanged(self, runner: CliRunner, client: MagicMock) -> None:
        client.get_goal.return_value = {"uuid": "g-1", "project_count": 3}
        with patch("dailybot_cli.commands.goal.require_auth", return_value=client):
            result = runner.invoke(cli, ["goal", "get", "g-1", "--include", "projects", "--json"])
        assert json.loads(result.stdout)["project_count"] == 3
