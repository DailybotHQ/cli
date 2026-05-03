"""Tests for `dailybot uninstall`."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``CONFIG_DIR`` to a tmp path so --purge tests can't touch real ~/.config."""
    fake_config: Path = tmp_path / "fake_dailybot_config"
    monkeypatch.setattr("dailybot_cli.commands.uninstall.CONFIG_DIR", fake_config)
    return fake_config


def _patch_method(method: str, install_path: Path = Path("/fake/install/path")) -> Any:
    """Patch detection so we don't depend on whatever installed pytest."""

    def _ctx() -> Any:
        return patch.multiple(
            "dailybot_cli.commands.uninstall",
            detect_install_method=MagicMock(return_value=method),
            resolve_install_path=MagicMock(return_value=install_path),
        )

    return _ctx()


# --- Confirmation flow ------------------------------------------------------


class TestUninstallConfirmation:
    def test_aborts_when_user_declines(self, runner: CliRunner, isolated_config_dir: Path) -> None:
        with (
            _patch_method("pip"),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            result = runner.invoke(cli, ["uninstall"], input="n\n")
        assert result.exit_code == 0
        assert "Aborted" in result.output
        mock_run.assert_not_called()

    def test_yes_flag_skips_prompt(self, runner: CliRunner, isolated_config_dir: Path) -> None:
        with (
            _patch_method("pip"),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["uninstall", "--yes"])
        assert result.exit_code == 0
        # The "Proceed?" string is the click.confirm prompt — it MUST be absent.
        assert "Proceed?" not in result.output
        mock_run.assert_called_once()

    def test_short_y_alias(self, runner: CliRunner, isolated_config_dir: Path) -> None:
        with (
            _patch_method("pip"),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["uninstall", "-y"])
        assert result.exit_code == 0
        mock_run.assert_called_once()

    def test_default_is_no(self, runner: CliRunner, isolated_config_dir: Path) -> None:
        """Sending an empty answer (just Enter) takes the safe ``no`` default."""
        with (
            _patch_method("pip"),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            result = runner.invoke(cli, ["uninstall"], input="\n")
        assert result.exit_code == 0
        mock_run.assert_not_called()


# --- Per-install-method dispatch -------------------------------------------


class TestUninstallDispatch:
    def test_pipx(self, runner: CliRunner, isolated_config_dir: Path) -> None:
        with (
            _patch_method("pipx"),
            patch(
                "dailybot_cli.commands.uninstall.shutil.which",
                return_value="/usr/local/bin/pipx",
            ),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["uninstall", "--yes"])
        assert result.exit_code == 0
        argv = mock_run.call_args[0][0]
        assert argv == ["pipx", "uninstall", "dailybot-cli"]

    def test_uv_tool(self, runner: CliRunner, isolated_config_dir: Path) -> None:
        with (
            _patch_method("uv-tool"),
            patch(
                "dailybot_cli.commands.uninstall.shutil.which",
                return_value="/usr/local/bin/uv",
            ),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["uninstall", "--yes"])
        assert result.exit_code == 0
        argv = mock_run.call_args[0][0]
        assert argv == ["uv", "tool", "uninstall", "dailybot-cli"]

    def test_pip(self, runner: CliRunner, isolated_config_dir: Path) -> None:
        with (
            _patch_method("pip"),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["uninstall", "--yes"])
        assert result.exit_code == 0
        argv = mock_run.call_args[0][0]
        # Use whichever Python is running — don't hardcode a path.
        assert argv[1:] == ["-m", "pip", "uninstall", "-y", "dailybot-cli"]

    def test_homebrew_prints_manual_command(
        self, runner: CliRunner, isolated_config_dir: Path
    ) -> None:
        with (
            _patch_method("homebrew"),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            result = runner.invoke(cli, ["uninstall", "--yes"])
        assert result.exit_code == 0
        assert "brew uninstall dailybothq/tap/dailybot" in result.output
        mock_run.assert_not_called()

    def test_binary_prints_rm_command(self, runner: CliRunner, isolated_config_dir: Path) -> None:
        with (
            _patch_method("binary", install_path=Path("/usr/local/bin/dailybot")),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            result = runner.invoke(cli, ["uninstall", "--yes"])
        assert result.exit_code == 0
        assert "rm " in result.output
        mock_run.assert_not_called()

    def test_editable_refuses_early(self, runner: CliRunner, isolated_config_dir: Path) -> None:
        """An editable install must bail out BEFORE asking for confirmation."""
        with (
            _patch_method("editable"),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            result = runner.invoke(cli, ["uninstall"])
        assert result.exit_code == 0
        assert "Refusing to auto-uninstall" in result.output
        # Even though we didn't pass --yes, the editable path skips the prompt
        # entirely, so subprocess.run must never be called.
        mock_run.assert_not_called()
        assert "Proceed?" not in result.output


# --- Dry-run ---------------------------------------------------------------


class TestUninstallDryRun:
    def test_dry_run_prints_plan_and_exits(
        self, runner: CliRunner, isolated_config_dir: Path
    ) -> None:
        with (
            _patch_method("pip"),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            result = runner.invoke(cli, ["uninstall", "--dry-run"])
        assert result.exit_code == 0
        assert "Uninstall plan:" in result.output
        assert "Dry run" in result.output
        mock_run.assert_not_called()

    def test_dry_run_does_not_prompt(self, runner: CliRunner, isolated_config_dir: Path) -> None:
        """Dry-run must short-circuit before the confirmation prompt."""
        with (
            _patch_method("pip"),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            # Empty input — if the command tried to prompt, it'd hang or
            # take the default. We assert the prompt string is absent.
            result = runner.invoke(cli, ["uninstall", "--dry-run"], input="")
        assert result.exit_code == 0
        assert "Proceed?" not in result.output
        mock_run.assert_not_called()


# --- --purge ---------------------------------------------------------------


class TestUninstallPurge:
    def test_purge_removes_config_dir(self, runner: CliRunner, isolated_config_dir: Path) -> None:
        # Pre-populate the fake config dir.
        isolated_config_dir.mkdir(parents=True)
        (isolated_config_dir / "credentials.json").write_text('{"token": "x"}')

        with (
            _patch_method("pip"),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["uninstall", "--yes", "--purge"])

        assert result.exit_code == 0
        assert not isolated_config_dir.exists()
        assert "Removed" in result.output

    def test_purge_handles_missing_config_dir(
        self, runner: CliRunner, isolated_config_dir: Path
    ) -> None:
        # Don't pre-create the dir — it's missing.
        assert not isolated_config_dir.exists()

        with (
            _patch_method("pip"),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["uninstall", "--yes", "--purge"])

        assert result.exit_code == 0
        assert "did not exist" in result.output

    def test_default_keeps_config(self, runner: CliRunner, isolated_config_dir: Path) -> None:
        isolated_config_dir.mkdir(parents=True)
        (isolated_config_dir / "credentials.json").write_text('{"token": "x"}')

        with (
            _patch_method("pip"),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["uninstall", "--yes"])

        assert result.exit_code == 0
        # Without --purge the directory must survive.
        assert isolated_config_dir.exists()
        assert "use --purge to remove" in result.output

    def test_purge_runs_for_homebrew_too(
        self, runner: CliRunner, isolated_config_dir: Path
    ) -> None:
        """--purge should still wipe the config dir even when we delegate the package
        manager work to the user (homebrew/binary). Otherwise users on macOS would
        have to remember a second `rm -rf` step."""
        isolated_config_dir.mkdir(parents=True)
        (isolated_config_dir / "credentials.json").write_text('{"token": "x"}')

        with (
            _patch_method("homebrew"),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            result = runner.invoke(cli, ["uninstall", "--yes", "--purge"])

        assert result.exit_code == 0
        assert not isolated_config_dir.exists()
        mock_run.assert_not_called()


# --- Failure paths ---------------------------------------------------------


class TestUninstallFailures:
    def test_subprocess_failure_propagates_exit_code(
        self, runner: CliRunner, isolated_config_dir: Path
    ) -> None:
        import subprocess

        with (
            _patch_method("pip"),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = subprocess.CalledProcessError(2, ["pip"])
            result = runner.invoke(cli, ["uninstall", "--yes"])
        assert result.exit_code == 2
        assert "failed with exit code 2" in result.output

    def test_executable_not_found_falls_back(
        self, runner: CliRunner, isolated_config_dir: Path
    ) -> None:
        with (
            _patch_method("pipx"),
            patch(
                "dailybot_cli.commands.uninstall.shutil.which",
                return_value="/usr/local/bin/pipx",
            ),
            patch("dailybot_cli.commands.uninstall.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = FileNotFoundError("pipx not found")
            result = runner.invoke(cli, ["uninstall", "--yes"])
        assert result.exit_code == 1
        assert "manual command" in result.output


# --- Top-level CLI integration ---------------------------------------------


class TestUninstallTopLevelIntegration:
    def test_uninstall_appears_in_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "uninstall" in result.output

    def test_uninstall_help_documents_purge(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["uninstall", "--help"])
        assert result.exit_code == 0
        assert "--purge" in result.output
        assert "--yes" in result.output
        assert "--dry-run" in result.output
