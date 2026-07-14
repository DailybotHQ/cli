"""Tests for the `dailybot env` CLI command group."""

import json
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner


@pytest.fixture(autouse=True)
def _reset_env_warnings() -> None:
    from dailybot_cli.config import reset_repo_env_warnings

    reset_repo_env_warnings()


@pytest.fixture(autouse=True)
def _isolate_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "DAILYBOT_API_KEY",
        "DAILYBOT_CLI_TOKEN",
        "DAILYBOT_API_URL",
        "DAILYBOT_APP_URL",
        "DAILYBOT_CONFIG_DIR",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def chdir_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    # Init a git repo so save_repo_env anchors at tmp_path, not somewhere else.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# --- Top-level wiring -------------------------------------------------------


def test_env_group_registered(runner: CliRunner) -> None:
    """The `env` group must be discoverable from the root CLI."""
    from dailybot_cli.main import cli

    result = runner.invoke(cli, ["env", "--help"])
    assert result.exit_code == 0
    assert "env" in result.output.lower()
    for sub in ("list", "use", "show", "add", "remove", "off", "on"):
        assert sub in result.output


# --- env add ----------------------------------------------------------------


class TestEnvAdd:
    def test_creates_file_and_sets_active(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        result = runner.invoke(
            cli,
            [
                "env",
                "add",
                "--name",
                "local",
                "--key",
                "sk_local_xxx",
                "--api-url",
                "http://localhost:8000",
                "--app-url",
                "http://localhost:8090",
            ],
        )
        assert result.exit_code == 0, result.output
        env_path: Path = chdir_tmp / ".dailybot" / "env.json"
        assert env_path.exists()
        assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
        payload: dict[str, Any] = json.loads(env_path.read_text())
        assert payload["active"] == "local"
        assert payload["profiles"][0]["api_key"] == "sk_local_xxx"
        assert payload["profiles"][0]["api_url"] == "http://localhost:8000"
        # Success feedback mentions the profile name and that it became active.
        assert "local" in result.output

    def test_append_does_not_change_active(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        runner.invoke(cli, ["env", "add", "--name", "live", "--key", "sk_live_xxx"])
        result = runner.invoke(
            cli,
            [
                "env",
                "add",
                "--name",
                "staging",
                "--key",
                "sk_staging_xxx",
                "--api-url",
                "https://staging-api.example.com",
            ],
        )
        assert result.exit_code == 0, result.output
        payload: dict[str, Any] = json.loads((chdir_tmp / ".dailybot" / "env.json").read_text())
        assert payload["active"] == "live"
        assert [p["name"] for p in payload["profiles"]] == ["live", "staging"]

    def test_duplicate_name_errors(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        runner.invoke(cli, ["env", "add", "--name", "live", "--key", "k1"])
        result = runner.invoke(cli, ["env", "add", "--name", "live", "--key", "k2"])
        assert result.exit_code == 1
        assert "already exists" in (result.output + (result.stderr or "")).lower()

    def test_missing_required_flags_errors(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        # Without --name / --key we expect Click to complain about missing options.
        result = runner.invoke(cli, ["env", "add"])
        assert result.exit_code != 0

    def test_warns_when_gitignore_does_not_cover_env_json(
        self,
        runner: CliRunner,
        chdir_tmp: Path,
    ) -> None:
        """If .gitignore doesn't cover env.json, we warn (write still succeeds)."""
        from dailybot_cli.main import cli

        # No .gitignore in the repo — env.json would be trackable.
        result = runner.invoke(cli, ["env", "add", "--name", "live", "--key", "k"])
        assert result.exit_code == 0, result.output
        combined: str = result.output + (result.stderr or "")
        assert "gitignore" in combined.lower()


# --- env use ----------------------------------------------------------------


class TestEnvUse:
    def test_switches_active(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        runner.invoke(cli, ["env", "add", "--name", "live", "--key", "k1"])
        runner.invoke(cli, ["env", "add", "--name", "local", "--key", "k2"])
        result = runner.invoke(cli, ["env", "use", "local"])
        assert result.exit_code == 0, result.output
        payload: dict[str, Any] = json.loads((chdir_tmp / ".dailybot" / "env.json").read_text())
        assert payload["active"] == "local"

    def test_clear_active_with_empty_string(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        runner.invoke(cli, ["env", "add", "--name", "live", "--key", "k1"])
        result = runner.invoke(cli, ["env", "use", ""])
        assert result.exit_code == 0, result.output
        payload: dict[str, Any] = json.loads((chdir_tmp / ".dailybot" / "env.json").read_text())
        assert payload["active"] is None

    def test_unknown_name_errors(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        runner.invoke(cli, ["env", "add", "--name", "live", "--key", "k"])
        result = runner.invoke(cli, ["env", "use", "ghost"])
        assert result.exit_code == 1

    def test_no_file_errors(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        result = runner.invoke(cli, ["env", "use", "live"])
        assert result.exit_code == 1


# --- env show ---------------------------------------------------------------


class TestEnvShow:
    def test_shows_active_profile_masked(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        runner.invoke(
            cli,
            [
                "env",
                "add",
                "--name",
                "local",
                "--key",
                "sk_supersecret_xxxxxxxxxxxxxxxx",
                "--api-url",
                "http://localhost:8000",
            ],
        )
        result = runner.invoke(cli, ["env", "show"])
        assert result.exit_code == 0, result.output
        # Masked (first 4 chars + ****)
        assert "sk_s****" in result.output
        assert "sk_supersecret_xxxxxxxxxxxxxxxx" not in result.output
        assert "http://localhost:8000" in result.output
        assert "local" in result.output

    def test_reports_disabled_state(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        runner.invoke(cli, ["env", "add", "--name", "live", "--key", "k"])
        runner.invoke(cli, ["env", "off"])
        result = runner.invoke(cli, ["env", "show"])
        assert result.exit_code == 0, result.output
        assert "disabled" in result.output.lower()

    def test_reports_no_active(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        runner.invoke(cli, ["env", "add", "--name", "live", "--key", "k"])
        runner.invoke(cli, ["env", "use", ""])
        result = runner.invoke(cli, ["env", "show"])
        assert result.exit_code == 0, result.output
        assert "no active" in result.output.lower() or "inactive" in result.output.lower()

    def test_no_file_message(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        result = runner.invoke(cli, ["env", "show"])
        assert result.exit_code == 0
        assert "no" in result.output.lower() and "env.json" in result.output.lower()


# --- env list ---------------------------------------------------------------


class TestEnvList:
    def test_lists_all_profiles_marks_active(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        runner.invoke(cli, ["env", "add", "--name", "live", "--key", "k1"])
        runner.invoke(cli, ["env", "add", "--name", "local", "--key", "k2"])
        runner.invoke(cli, ["env", "use", "local"])
        result = runner.invoke(cli, ["env", "list"])
        assert result.exit_code == 0, result.output
        assert "live" in result.output
        assert "local" in result.output

    def test_empty_file_prints_hint(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        result = runner.invoke(cli, ["env", "list"])
        assert result.exit_code == 0
        assert "env add" in result.output


# --- env remove -------------------------------------------------------------


class TestEnvRemove:
    def test_removes_profile(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        runner.invoke(cli, ["env", "add", "--name", "live", "--key", "k1"])
        runner.invoke(cli, ["env", "add", "--name", "local", "--key", "k2"])
        result = runner.invoke(cli, ["env", "remove", "local", "--yes"])
        assert result.exit_code == 0, result.output
        payload: dict[str, Any] = json.loads((chdir_tmp / ".dailybot" / "env.json").read_text())
        assert [p["name"] for p in payload["profiles"]] == ["live"]

    def test_removing_active_reports_it(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        runner.invoke(cli, ["env", "add", "--name", "live", "--key", "k"])
        result = runner.invoke(cli, ["env", "remove", "live", "--yes"])
        assert result.exit_code == 0, result.output
        assert "active" in result.output.lower()

    def test_unknown_profile_errors(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        runner.invoke(cli, ["env", "add", "--name", "live", "--key", "k"])
        result = runner.invoke(cli, ["env", "remove", "ghost", "--yes"])
        assert result.exit_code == 1


# --- env off / on -----------------------------------------------------------


class TestEnvKillSwitch:
    def test_off_disables_env_json(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.config import get_active_env_profile
        from dailybot_cli.main import cli

        runner.invoke(cli, ["env", "add", "--name", "live", "--key", "k"])
        assert get_active_env_profile(chdir_tmp) is not None
        result = runner.invoke(cli, ["env", "off"])
        assert result.exit_code == 0, result.output
        assert get_active_env_profile(chdir_tmp) is None

    def test_on_re_enables(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.config import get_active_env_profile
        from dailybot_cli.main import cli

        runner.invoke(cli, ["env", "add", "--name", "live", "--key", "k"])
        runner.invoke(cli, ["env", "off"])
        result = runner.invoke(cli, ["env", "on"])
        assert result.exit_code == 0, result.output
        active: dict[str, Any] | None = get_active_env_profile(chdir_tmp)
        assert active is not None
        assert active["name"] == "live"

    def test_off_no_file_errors(self, runner: CliRunner, chdir_tmp: Path) -> None:
        from dailybot_cli.main import cli

        result = runner.invoke(cli, ["env", "off"])
        assert result.exit_code == 1


# --- Committed guard surfaces at CLI --------------------------------------


class TestCommittedGuardSurfacing:
    def _stage_tracked_env_json(self, runner: CliRunner, chdir_tmp: Path) -> None:
        """Shared setup: write env.json via the CLI, then simulate a
        developer mistake by force-adding and committing it."""
        from dailybot_cli.main import cli

        runner.invoke(cli, ["env", "add", "--name", "live", "--key", "k"])
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=chdir_tmp,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=chdir_tmp,
            check=True,
        )
        subprocess.run(
            ["git", "add", "-f", ".dailybot/env.json"],
            cwd=chdir_tmp,
            check=True,
        )
        subprocess.run(["git", "commit", "-q", "-m", "leak"], cwd=chdir_tmp, check=True)

    def test_env_use_bubbles_fatal_when_env_json_tracked(
        self,
        runner: CliRunner,
        chdir_tmp: Path,
    ) -> None:
        """Env.json tracked in git → any env subcommand exits non-zero with a
        message the developer can act on."""
        from dailybot_cli.main import cli

        self._stage_tracked_env_json(runner, chdir_tmp)
        result = runner.invoke(cli, ["env", "show"])
        assert result.exit_code == 1
        combined: str = result.output + (result.stderr or "")
        assert "tracked" in combined.lower()

    def test_root_cli_refuses_every_command_when_env_json_tracked(
        self,
        runner: CliRunner,
        chdir_tmp: Path,
    ) -> None:
        """Regression guard for the security bug where the refuse-if-tracked
        check only fired for `env` subcommands — every other command
        (`status`, `user list`, `form list`, `agent update`, ...) silently
        ignored the guard and continued with fallback global auth, leaving
        the tracked env.json (and the API keys it contains) exposed in git
        history while the CLI happily kept running.

        The fix wires the check into the root `cli()` callback so it fires
        universally, before any subcommand executes. Any command that goes
        through the root group should refuse."""
        from dailybot_cli.main import cli

        self._stage_tracked_env_json(runner, chdir_tmp)

        # Sample non-env commands from every layer — user-scoped, agent,
        # meta, and no-op subcommands. All must refuse identically.
        for argv in (
            ["status", "--auth"],
            ["user", "list"],
            ["form", "list"],
            ["me"],
            ["config", "list"],
        ):
            result = runner.invoke(cli, argv)
            assert result.exit_code == 1, f"{argv!r} should have refused"
            combined: str = result.output + (result.stderr or "")
            assert "tracked" in combined.lower(), (
                f"{argv!r} exit was 1 but the error text did not surface the "
                f"tracked-env.json reason. Got: {combined!r}"
            )

    def test_root_cli_help_still_works_when_env_json_tracked(
        self,
        runner: CliRunner,
        chdir_tmp: Path,
    ) -> None:
        """`--help` and `--version` must NOT be blocked by the guard —
        Click short-circuits these before the root callback, so the user
        can always discover the CLI (and read the fix instructions)."""
        from dailybot_cli.main import cli

        self._stage_tracked_env_json(runner, chdir_tmp)

        for argv in (["--help"], ["--version"]):
            result = runner.invoke(cli, argv)
            assert result.exit_code == 0, f"{argv!r} should succeed even when env.json is tracked"
