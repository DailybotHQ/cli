"""Regression tests for the CI AI review's seventh pass on PR #85.

Seven findings. The two that matter most are disagreements between two paths that
describe the same event: `task bulk` told a person a batch had failed and told an
agent it had succeeded, and the `tasks:admin` refusal exited 3 from the CLI's own
pre-flight and 4 from the server. In both cases the defect is not that one side is
wrong — it is that the two sides disagree, so which answer a caller gets depends on
something they did not ask about.

The rest close the markup-escape sweep at the three Tasks call sites that echo a
server timestamp into Rich markup, and finish the `--json` stdout promise at the
one exit it had never covered: transport failure.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import DailyBotClient, PaginatedResult
from dailybot_cli.commands.public_api_helpers import (
    EXIT_NOT_AUTHENTICATED,
    EXIT_PERMISSION_DENIED,
)
from dailybot_cli.main import cli

EXIT_TRANSPORT: int = 8


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=DailyBotClient)


@pytest.fixture
def batch(tmp_path: Any) -> str:
    path = tmp_path / "batch.json"
    path.write_text('[{"uuid": "t-1"}, {"uuid": "t-2"}]')
    return str(path)


def _rows(*statuses: str) -> dict[str, Any]:
    return {
        "results": [
            {"uuid": f"t-{i}", "status": st, "code": "not_found" if st == "error" else None}
            for i, st in enumerate(statuses, start=1)
        ]
    }


class TestBulkAgreesWithItself:
    """Finding 1: a partial bulk failure exited 1 for a person and 0 for an agent.

    The failed-row scan sat *below* the `--json` early return, so the machine path
    never reached it. An agent inspecting only the process exit was told the batch
    had applied while the same call, run by hand, said it had not.
    """

    def test_json_exits_non_zero_on_a_partial_failure(
        self, runner: CliRunner, client: MagicMock, batch: str
    ) -> None:
        client.bulk_tasks.return_value = _rows("ok", "error")
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(
                cli, ["task", "bulk", "--operation", "archive", "-f", batch, "--yes", "--json"]
            )
        assert result.exit_code == 1

    def test_the_document_is_still_emitted(
        self, runner: CliRunner, client: MagicMock, batch: str
    ) -> None:
        # Exiting non-zero must not cost the caller the per-item detail: it is the
        # only way to learn *which* items failed.
        client.bulk_tasks.return_value = _rows("ok", "error")
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(
                cli, ["task", "bulk", "--operation", "archive", "-f", batch, "--yes", "--json"]
            )
        body: Any = json.loads(result.stdout)
        assert [row["status"] for row in body["results"]] == ["ok", "error"]

    def test_a_clean_batch_still_exits_zero(
        self, runner: CliRunner, client: MagicMock, batch: str
    ) -> None:
        client.bulk_tasks.return_value = _rows("ok", "ok")
        with patch("dailybot_cli.commands.task.require_auth", return_value=client):
            result = runner.invoke(
                cli, ["task", "bulk", "--operation", "archive", "-f", batch, "--yes", "--json"]
            )
        assert result.exit_code == 0

    def test_both_modes_agree(self, runner: CliRunner, client: MagicMock, batch: str) -> None:
        codes: list[int] = []
        for argv in (["--yes"], ["--yes", "--json"]):
            client.bulk_tasks.return_value = _rows("ok", "error")
            with patch("dailybot_cli.commands.task.require_auth", return_value=client):
                codes.append(
                    runner.invoke(
                        cli, ["task", "bulk", "--operation", "archive", "-f", batch, *argv]
                    ).exit_code
                )
        assert codes[0] == codes[1]


class TestPreflightExitMatchesTheServer:
    """Finding 2: the pre-flight was observable through the exit code.

    Round 6 made the JSON `code` identical whether the refusal came from the client
    or the server, so a caller need not know which. The exit code still differed:
    the `tasks:admin` pre-flight exited 3 while the server's `403 insufficient_scope`
    exited 4 — so an agent branching "3 → re-login, 4 → permission" behaved
    differently depending on whether a request happened to be spent.
    """

    @pytest.mark.parametrize(
        ("argv", "module"),
        [
            (["board", "create", "--name", "b"], "board"),
            (["project", "create", "--name", "p"], "project"),
            (["goal", "create", "--name", "g"], "project"),
        ],
    )
    def test_admin_doors_exit_four(self, runner: CliRunner, argv: list[str], module: str) -> None:
        with patch(f"dailybot_cli.commands.{module}.get_token", return_value=None):
            result = runner.invoke(cli, argv)
        assert result.exit_code == EXIT_PERMISSION_DENIED

    @pytest.mark.parametrize(
        ("argv", "module"),
        [
            (["tasks", "inbox"], "tasks"),
            (["tasks", "mine"], "tasks"),
            (["tasks", "counts"], "tasks"),
            (["task", "participants", "add", "t-1", "--user", "u-1"], "task"),
        ],
    )
    def test_person_shaped_doors_still_exit_three(
        self, runner: CliRunner, argv: list[str], module: str
    ) -> None:
        # These answer `actor_required`, which IS a credential problem — `dailybot
        # login` genuinely fixes it, so 3 is the right advice here.
        with patch(f"dailybot_cli.commands.{module}.get_token", return_value=None):
            result = runner.invoke(cli, argv)
        assert result.exit_code == EXIT_NOT_AUTHENTICATED


class TestServerTimestampsAreEscaped:
    """Findings 3-5: three Tasks renderers put a server field into markup raw.

    The body text beside each one already went through `present_untrusted`. The
    timestamp did not — so a `created_at` containing `[/dim]` raised MarkupError
    and the root safety net reported the CLI's own bug instead of the data.
    """

    @pytest.mark.parametrize(
        ("argv", "module", "door", "row"),
        [
            (
                ["tasks", "activity"],
                "tasks",
                "list_tasks_activity",
                {"created_at": "[/dim][bold red]x", "summary": "did a thing"},
            ),
            (
                ["tasks", "timeline"],
                "tasks",
                "list_tasks_timeline",
                {"date": "[/dim][red]x", "title": "a day"},
            ),
            (
                ["project", "updates"],
                "project",
                "list_project_updates",
                {"created_at": "[/dim][red]x", "body": "shipped"},
            ),
        ],
    )
    def test_a_markup_timestamp_does_not_crash_the_render(
        self,
        runner: CliRunner,
        client: MagicMock,
        argv: list[str],
        module: str,
        door: str,
        row: dict[str, Any],
    ) -> None:
        getattr(client, door).return_value = PaginatedResult(
            results=[row], count=1, next=None, previous=None
        )
        with patch(f"dailybot_cli.commands.{module}.require_auth", return_value=client):
            result = runner.invoke(cli, argv)
        assert "Unexpected error" not in result.stderr
        assert "MarkupError" not in result.stderr
        assert result.exit_code == 0

    def test_an_ordinary_timestamp_still_renders(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.list_tasks_activity.return_value = PaginatedResult(
            results=[{"created_at": "2026-09-21T00:00:00Z", "summary": "did a thing"}],
            count=1,
            next=None,
            previous=None,
        )
        with patch("dailybot_cli.commands.tasks.require_auth", return_value=client):
            result = runner.invoke(cli, ["tasks", "activity"])
        assert "2026-09-21" in result.stdout


class TestTransportFailureHonoursJson:
    """Finding 7: exit 8 left stdout empty.

    The safety net sits above every command callback, so the leaf's `json_mode`
    is out of reach — which is why this exit had never been covered by the
    `--json` promise. An agent that parses stdout on every non-zero exit read an
    unreachable host as a parser crash.
    """

    def test_stdout_carries_a_transport_envelope(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        client.get_tasks_pulse.side_effect = httpx.ConnectError("refused")
        with (
            patch("dailybot_cli.commands.tasks.require_auth", return_value=client),
            patch("sys.argv", ["dailybot", "tasks", "status", "--json"]),
        ):
            result = runner.invoke(cli, ["tasks", "status", "--json"])
        assert result.exit_code == 1  # a raw httpx error is not a TransportError
        assert json.loads(result.stdout)["status"] == "error"

    def test_a_real_transport_error_exits_eight_with_json(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        from dailybot_cli.api_client import TransportError

        client.get_tasks_pulse.side_effect = TransportError("Could not reach Dailybot at x")
        with (
            patch("dailybot_cli.commands.tasks.require_auth", return_value=client),
            patch("sys.argv", ["dailybot", "tasks", "status", "--json"]),
        ):
            result = runner.invoke(cli, ["tasks", "status", "--json"])
        assert result.exit_code == EXIT_TRANSPORT
        body: Any = json.loads(result.stdout)
        assert body["code"] == "transport_error"

    def test_without_json_it_stays_prose_on_stderr(
        self, runner: CliRunner, client: MagicMock
    ) -> None:
        from dailybot_cli.api_client import TransportError

        client.get_tasks_pulse.side_effect = TransportError("Could not reach Dailybot at x")
        with (
            patch("dailybot_cli.commands.tasks.require_auth", return_value=client),
            patch("sys.argv", ["dailybot", "tasks", "status"]),
        ):
            result = runner.invoke(cli, ["tasks", "status"])
        assert result.exit_code == EXIT_TRANSPORT
        assert result.stdout == ""
        assert "Could not reach" in result.stderr
