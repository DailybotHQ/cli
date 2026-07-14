"""Tests for CLI commands."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.api_client import APIError
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestVersionAndHelp:
    def test_version(self, runner: CliRunner) -> None:
        from dailybot_cli import __version__

        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "dailybot" in result.output
        assert __version__ in result.output

    def test_version_includes_python_version(self, runner: CliRunner) -> None:
        """`--version` should show the Python version too (gh-cli style)."""
        import platform

        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert f"Python {platform.python_version()}" in result.output

    def test_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "login" in result.output
        assert "logout" in result.output
        assert "update" in result.output
        assert "status" in result.output
        assert "agent" in result.output
        assert "version" in result.output
        assert "--api-url" in result.output


class TestVersionCommand:
    """`dailybot version` (rich panel) and `dailybot version --check`."""

    def test_version_command_local_only(self, runner: CliRunner) -> None:
        """No network when --check is omitted."""
        from dailybot_cli import __version__

        with patch("dailybot_cli.commands.version.httpx.get") as mock_get:
            result = runner.invoke(cli, ["version"])
            assert result.exit_code == 0
            assert __version__ in result.output
            mock_get.assert_not_called()  # no network without --check

    def test_version_command_includes_install_path(self, runner: CliRunner) -> None:
        """Output should include the on-disk install location of the package."""
        result = runner.invoke(cli, ["version"])
        assert result.exit_code == 0
        # The path resolves to .../dailybot_cli, so just check the package name
        # appears in the rendered panel.
        assert "dailybot_cli" in result.output

    def test_version_command_check_up_to_date(self, runner: CliRunner) -> None:
        """When PyPI returns the same version, mark as up-to-date."""
        from dailybot_cli import __version__

        mock_response: MagicMock = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"info": {"version": __version__}}
        with patch("dailybot_cli.commands.version.httpx.get", return_value=mock_response):
            result = runner.invoke(cli, ["version", "--check"])
            assert result.exit_code == 0
            assert "up-to-date" in result.output

    def test_version_command_check_update_available(self, runner: CliRunner) -> None:
        """When PyPI returns a higher version, surface the upgrade hint."""
        mock_response: MagicMock = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"info": {"version": "999.0.0"}}
        with patch("dailybot_cli.commands.version.httpx.get", return_value=mock_response):
            result = runner.invoke(cli, ["version", "--check"])
            assert result.exit_code == 0
            assert "update available: 999.0.0" in result.output
            assert "brew upgrade dailybot" in result.output

    def test_version_command_check_offline(self, runner: CliRunner) -> None:
        """If PyPI is unreachable, fall back to local info with a warning."""
        import httpx as _httpx

        with patch(
            "dailybot_cli.commands.version.httpx.get",
            side_effect=_httpx.ConnectError("offline"),
        ):
            result = runner.invoke(cli, ["version", "--check"])
            assert result.exit_code == 0
            assert "Could not reach PyPI" in result.output

    def test_version_command_pyinstaller_bundle(self, runner: CliRunner) -> None:
        """In a frozen (PyInstaller) build, show the binary path, not the temp dir."""
        with patch("dailybot_cli.commands.version.sys") as mock_sys:
            mock_sys.frozen = True
            mock_sys.executable = "/usr/local/bin/dailybot"
            result = runner.invoke(cli, ["version"])
            assert result.exit_code == 0
            assert "/usr/local/bin/dailybot" in result.output
            assert "PyInstaller bundle" in result.output


class TestUpgradeCommand:
    """`dailybot upgrade` — auto-detect install method and update."""

    def test_upgrade_already_latest(self, runner: CliRunner) -> None:
        """If we're already on the latest version, exit cleanly without running anything."""
        from dailybot_cli import __version__

        with (
            patch(
                "dailybot_cli.commands.upgrade._fetch_latest_pypi_version",
                return_value=__version__,
            ),
            patch("dailybot_cli.commands.upgrade.subprocess.run") as mock_run,
        ):
            result = runner.invoke(cli, ["upgrade"])
            assert result.exit_code == 0
            assert "already on the latest" in result.output
            mock_run.assert_not_called()

    def test_upgrade_pipx_runs_pipx(self, runner: CliRunner) -> None:
        """A pipx-detected install runs `pipx upgrade dailybot-cli`."""
        with (
            patch(
                "dailybot_cli.commands.upgrade._fetch_latest_pypi_version",
                return_value="999.0.0",
            ),
            patch(
                "dailybot_cli.commands.upgrade._detect_install_method",
                return_value="pipx",
            ),
            patch(
                "dailybot_cli.commands.upgrade.shutil.which",
                return_value="/usr/local/bin/pipx",
            ),
            patch(
                "dailybot_cli.commands.upgrade._query_installed_version",
                return_value="999.0.0",
            ),
            patch("dailybot_cli.commands.upgrade.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["upgrade"])
            assert result.exit_code == 0
            mock_run.assert_called_once()
            argv = mock_run.call_args[0][0]
            assert argv == ["pipx", "upgrade", "dailybot-cli"]

    def test_upgrade_uv_tool(self, runner: CliRunner) -> None:
        """A uv-tool install runs `uv tool upgrade dailybot-cli`."""
        with (
            patch(
                "dailybot_cli.commands.upgrade._fetch_latest_pypi_version",
                return_value="999.0.0",
            ),
            patch(
                "dailybot_cli.commands.upgrade._detect_install_method",
                return_value="uv-tool",
            ),
            patch(
                "dailybot_cli.commands.upgrade.shutil.which",
                return_value="/usr/local/bin/uv",
            ),
            patch(
                "dailybot_cli.commands.upgrade._query_installed_version",
                return_value="999.0.0",
            ),
            patch("dailybot_cli.commands.upgrade.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["upgrade"])
            assert result.exit_code == 0
            argv = mock_run.call_args[0][0]
            assert argv == ["uv", "tool", "upgrade", "dailybot-cli"]

    def test_upgrade_pip_pins_version_from_pypi(self, runner: CliRunner) -> None:
        """A pip install pins the exact version (==X.Y.Z) so pip can't no-op
        when its index cache is stale or system-site is read-only."""
        with (
            patch(
                "dailybot_cli.commands.upgrade._fetch_latest_pypi_version",
                return_value="999.0.0",
            ),
            patch(
                "dailybot_cli.commands.upgrade._detect_install_method",
                return_value="pip",
            ),
            patch(
                "dailybot_cli.commands.upgrade._query_installed_version",
                return_value="999.0.0",
            ),
            patch("dailybot_cli.commands.upgrade.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["upgrade"])
            assert result.exit_code == 0
            argv = mock_run.call_args[0][0]
            assert argv[1:] == ["-m", "pip", "install", "--upgrade", "dailybot-cli==999.0.0"]

    def test_upgrade_pip_falls_back_to_unpinned_when_pypi_unreachable(
        self, runner: CliRunner
    ) -> None:
        """If the JSON API didn't return a version, we still try `pip install --upgrade`
        without a pin — at least gives the user a chance instead of bailing."""
        with (
            patch(
                "dailybot_cli.commands.upgrade._fetch_latest_pypi_version",
                return_value=None,
            ),
            patch(
                "dailybot_cli.commands.upgrade._detect_install_method",
                return_value="pip",
            ),
            patch(
                "dailybot_cli.commands.upgrade._query_installed_version",
                return_value="999.0.0",
            ),
            patch("dailybot_cli.commands.upgrade.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["upgrade"])
            assert result.exit_code == 0
            argv = mock_run.call_args[0][0]
            assert argv[1:] == ["-m", "pip", "install", "--upgrade", "dailybot-cli"]

    def test_upgrade_homebrew_prints_command_not_run(self, runner: CliRunner) -> None:
        """Homebrew installs print a manual command — do NOT auto-invoke brew."""
        with (
            patch(
                "dailybot_cli.commands.upgrade._fetch_latest_pypi_version",
                return_value="999.0.0",
            ),
            patch(
                "dailybot_cli.commands.upgrade._detect_install_method",
                return_value="homebrew",
            ),
            patch("dailybot_cli.commands.upgrade.subprocess.run") as mock_run,
        ):
            result = runner.invoke(cli, ["upgrade"])
            assert result.exit_code == 0
            assert "brew update && brew upgrade dailybot" in result.output
            mock_run.assert_not_called()

    def test_upgrade_binary_prints_install_sh(self, runner: CliRunner) -> None:
        """A PyInstaller binary install prints the install.sh re-run command on Linux."""
        with (
            patch(
                "dailybot_cli.commands.upgrade._fetch_latest_pypi_version",
                return_value="999.0.0",
            ),
            patch(
                "dailybot_cli.commands.upgrade._detect_install_method",
                return_value="binary",
            ),
            patch(
                "dailybot_cli.commands.upgrade.platform.system",
                return_value="Linux",
            ),
            patch("dailybot_cli.commands.upgrade.subprocess.run") as mock_run,
        ):
            result = runner.invoke(cli, ["upgrade"])
            assert result.exit_code == 0
            assert "cli.dailybot.com/install.sh" in result.output
            mock_run.assert_not_called()

    def test_upgrade_binary_prints_install_ps1_on_windows(self, runner: CliRunner) -> None:
        """A frozen install on Windows prints the install.ps1 command."""
        with (
            patch(
                "dailybot_cli.commands.upgrade._fetch_latest_pypi_version",
                return_value="999.0.0",
            ),
            patch(
                "dailybot_cli.commands.upgrade._detect_install_method",
                return_value="binary",
            ),
            patch(
                "dailybot_cli.commands.upgrade.platform.system",
                return_value="Windows",
            ),
            patch("dailybot_cli.commands.upgrade.subprocess.run") as mock_run,
        ):
            result = runner.invoke(cli, ["upgrade"])
            assert result.exit_code == 0
            assert "install.ps1" in result.output
            mock_run.assert_not_called()

    def test_upgrade_editable_refuses(self, runner: CliRunner) -> None:
        """An editable (development) install must NOT auto-upgrade."""
        with (
            patch(
                "dailybot_cli.commands.upgrade._fetch_latest_pypi_version",
                return_value="999.0.0",
            ),
            patch(
                "dailybot_cli.commands.upgrade._detect_install_method",
                return_value="editable",
            ),
            patch("dailybot_cli.commands.upgrade.subprocess.run") as mock_run,
        ):
            result = runner.invoke(cli, ["upgrade"])
            assert result.exit_code == 0
            assert "editable" in result.output
            assert "git" in result.output
            mock_run.assert_not_called()

    def test_upgrade_dry_run_does_not_execute(self, runner: CliRunner) -> None:
        """--dry-run prints what would happen but does not invoke the upgrade."""
        with (
            patch(
                "dailybot_cli.commands.upgrade._fetch_latest_pypi_version",
                return_value="999.0.0",
            ),
            patch(
                "dailybot_cli.commands.upgrade._detect_install_method",
                return_value="pip",
            ),
            patch("dailybot_cli.commands.upgrade.subprocess.run") as mock_run,
        ):
            result = runner.invoke(cli, ["upgrade", "--dry-run"])
            assert result.exit_code == 0
            assert "Would run" in result.output
            mock_run.assert_not_called()

    def test_upgrade_force_runs_even_when_latest(self, runner: CliRunner) -> None:
        """--force runs the upgrade even when the installed version equals latest."""
        from dailybot_cli import __version__

        with (
            patch(
                "dailybot_cli.commands.upgrade._fetch_latest_pypi_version",
                return_value=__version__,
            ),
            patch(
                "dailybot_cli.commands.upgrade._detect_install_method",
                return_value="pip",
            ),
            patch(
                "dailybot_cli.commands.upgrade._query_installed_version",
                return_value=__version__,
            ),
            patch("dailybot_cli.commands.upgrade.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["upgrade", "--force"])
            assert result.exit_code == 0
            assert "already on the latest" not in result.output
            mock_run.assert_called_once()

    def test_upgrade_subprocess_failure_propagates_exit_code(self, runner: CliRunner) -> None:
        """When the upgrade command itself fails, surface its exit code."""
        import subprocess

        with (
            patch(
                "dailybot_cli.commands.upgrade._fetch_latest_pypi_version",
                return_value="999.0.0",
            ),
            patch(
                "dailybot_cli.commands.upgrade._detect_install_method",
                return_value="pip",
            ),
            patch(
                "dailybot_cli.commands.upgrade.subprocess.run",
                side_effect=subprocess.CalledProcessError(returncode=42, cmd="pip"),
            ),
        ):
            result = runner.invoke(cli, ["upgrade"])
            assert result.exit_code == 42
            assert "failed with exit code 42" in result.output

    def test_upgrade_warns_when_pip_silently_noops(self, runner: CliRunner) -> None:
        """Reproduces the real-world failure: pip exits 0 but the on-disk
        version didn't change. This happened after the v1.7.0 release with
        a stale pip index cache + read-only system site-packages.

        The fix is twofold: pin ``==<latest>`` so pip can't claim "already
        satisfied" (covered by other tests) AND verify the post-install
        version (covered here)."""
        from dailybot_cli import __version__

        with (
            patch(
                "dailybot_cli.commands.upgrade._fetch_latest_pypi_version",
                return_value="999.0.0",
            ),
            patch(
                "dailybot_cli.commands.upgrade._detect_install_method",
                return_value="pip",
            ),
            patch(
                "dailybot_cli.commands.upgrade._query_installed_version",
                return_value=__version__,  # pip exited 0 but didn't actually upgrade
            ),
            patch("dailybot_cli.commands.upgrade.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["upgrade"])
            assert result.exit_code == 0
            # Should NOT claim success
            assert "Upgrade complete" not in result.output
            # Should warn the user clearly and point at the install.sh fallback.
            # Rich wraps long warnings at terminal width, so collapse whitespace
            # before searching for the phrase.
            collapsed: str = " ".join(result.output.split())
            assert "exited successfully but the installed version is still" in collapsed
            assert "install.sh" in collapsed

    def test_upgrade_succeeds_when_version_actually_changed(self, runner: CliRunner) -> None:
        """Sanity: when the post-install version differs from current, we
        report success."""
        with (
            patch(
                "dailybot_cli.commands.upgrade._fetch_latest_pypi_version",
                return_value="999.0.0",
            ),
            patch(
                "dailybot_cli.commands.upgrade._detect_install_method",
                return_value="pip",
            ),
            patch(
                "dailybot_cli.commands.upgrade._query_installed_version",
                return_value="999.0.0",
            ),
            patch("dailybot_cli.commands.upgrade.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["upgrade"])
            assert result.exit_code == 0
            assert "Upgrade complete" in result.output

    @patch("dailybot_cli.main.set_api_url_override")
    @patch("dailybot_cli.commands.update.get_agent_auth")
    @patch("dailybot_cli.commands.update.DailyBotClient")
    def test_api_url_override(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        mock_set_override: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_update.return_value = {
            "followups_count": 1,
            "attached_followups": [{"followup_name": "Standup", "action": "created"}],
        }

        result = runner.invoke(cli, ["--api-url", "https://staging.dailybot.com", "update", "test"])
        assert result.exit_code == 0
        mock_set_override.assert_called_once_with("https://staging.dailybot.com")

    @patch("dailybot_cli.main.set_app_url_override")
    @patch("dailybot_cli.commands.update.get_agent_auth")
    @patch("dailybot_cli.commands.update.DailyBotClient")
    def test_app_url_override(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        mock_set_override: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_update.return_value = {
            "followups_count": 1,
            "attached_followups": [{"followup_name": "Standup", "action": "created"}],
        }

        result = runner.invoke(cli, ["--app-url", "http://localhost:8090", "update", "test"])
        assert result.exit_code == 0
        mock_set_override.assert_called_once_with("http://localhost:8090")


class TestLoginCommand:
    @patch("dailybot_cli.commands.auth.DailyBotClient")
    @patch("dailybot_cli.commands.auth.save_credentials")
    def test_login_single_org(
        self,
        mock_save: MagicMock,
        mock_client_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.api_url = "https://api.dailybot.com"
        mock_client.request_code.return_value = {
            "detail": "Verification code sent to your email.",
            "organizations": [{"id": 1, "name": "MyOrg", "uuid": "org-uuid-456"}],
            "is_multi_org": False,
        }
        mock_client.verify_code.return_value = {
            "requires_organization_selection": False,
            "token": "tok123",
            "user": {"email": "user@test.com"},
            "organization": {"id": 1, "name": "MyOrg", "uuid": "org-uuid-456"},
        }

        result = runner.invoke(cli, ["login"], input="user@test.com\n123456\n")
        assert result.exit_code == 0
        assert "Logged in" in result.output
        assert "MyOrg" in result.output
        mock_save.assert_called_once()
        # Single-org: verify is called once with organization_id
        mock_client.verify_code.assert_called_once_with(
            "user@test.com", "123456", organization_id=1
        )

    @patch("dailybot_cli.commands.auth.DailyBotClient")
    def test_login_warns_when_env_json_redirects_the_server(
        self,
        mock_client_cls: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Login persists the resolved api_url into the GLOBAL credentials
        file — when an active env.json profile is what points the CLI at a
        different server, the user must be warned before the OTP flow."""
        repo: Path = tmp_path / "repo"
        env_dir: Path = repo / ".dailybot"
        env_dir.mkdir(parents=True)
        (env_dir / "env.json").write_text(
            json.dumps(
                {
                    "active": "local",
                    "profiles": [
                        {
                            "name": "local",
                            "api_key": "sk-local",
                            "api_url": "http://localhost:8000",
                        }
                    ],
                }
            )
        )
        monkeypatch.chdir(repo)

        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.api_url = "http://localhost:8000"
        mock_client.request_code.side_effect = APIError(400, "stop here")

        result = runner.invoke(cli, ["login", "--email", "user@test.com"])
        assert "env.json" in result.output
        assert "GLOBAL session" in result.output
        assert "dailybot env off" in result.output

    @patch("dailybot_cli.commands.auth.DailyBotClient")
    def test_login_no_warning_without_env_json(
        self,
        mock_client_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.api_url = "https://api.dailybot.com"
        mock_client.request_code.side_effect = APIError(400, "stop here")

        result = runner.invoke(cli, ["login", "--email", "user@test.com"])
        assert "GLOBAL session" not in result.output

    @patch("dailybot_cli.commands.auth.questionary")
    @patch("dailybot_cli.commands.auth.DailyBotClient")
    @patch("dailybot_cli.commands.auth.save_credentials")
    def test_login_multi_org(
        self,
        mock_save: MagicMock,
        mock_client_cls: MagicMock,
        mock_questionary: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.api_url = "https://api.dailybot.com"
        orgs = [
            {"id": 1, "name": "Acme Corp", "uuid": "abc-123"},
            {"id": 2, "name": "Side Project", "uuid": "def-456"},
        ]
        mock_client.request_code.return_value = {
            "detail": "Verification code sent to your email.",
            "organizations": orgs,
            "is_multi_org": True,
        }
        mock_client.verify_code.return_value = {
            "requires_organization_selection": False,
            "token": "tok456",
            "user": {"email": "user@test.com"},
            "organization": {"id": 2, "name": "Side Project", "uuid": "def-456"},
        }
        # Mock questionary.select to return the second org
        mock_questionary.select.return_value.ask.return_value = orgs[1]

        # Enter email, code (org selection handled by questionary mock)
        result = runner.invoke(cli, ["login"], input="user@test.com\n123456\n")
        assert result.exit_code == 0
        assert "Logged in" in result.output
        assert "Side Project" in result.output
        # Org selected before verify — single call with org_id
        mock_client.verify_code.assert_called_once_with(
            "user@test.com", "123456", organization_id=2
        )

    @patch("dailybot_cli.commands.auth.DailyBotClient")
    def test_login_bad_email(self, mock_client_cls: MagicMock, runner: CliRunner) -> None:
        from dailybot_cli.api_client import APIError

        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.request_code.side_effect = APIError(400, "No account found")

        result = runner.invoke(cli, ["login"], input="bad@test.com\n")
        assert result.exit_code != 0

    @patch("dailybot_cli.commands.auth.DailyBotClient")
    @patch("dailybot_cli.commands.auth.save_credentials")
    def test_login_non_interactive_verify(
        self,
        mock_save: MagicMock,
        mock_client_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Non-interactive step 2: --email + --code verifies directly."""
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.api_url = "https://api.dailybot.com"
        mock_client.verify_code.return_value = {
            "token": "tok789",
            "user": {"email": "user@test.com"},
            "organization": {"id": 1, "name": "MyOrg", "uuid": "org-uuid"},
        }

        result = runner.invoke(cli, ["login", "--email=user@test.com", "--code=123456"])
        assert result.exit_code == 0
        assert "Logged in" in result.output
        mock_client.verify_code.assert_called_once_with(
            "user@test.com", "123456", organization_id=None
        )
        mock_save.assert_called_once()
        # request_code should NOT be called
        mock_client.request_code.assert_not_called()

    @patch("dailybot_cli.commands.auth.clear_org_cache")
    @patch("dailybot_cli.commands.auth.load_org_cache")
    @patch("dailybot_cli.commands.auth.DailyBotClient")
    @patch("dailybot_cli.commands.auth.save_credentials")
    def test_login_non_interactive_verify_with_org(
        self,
        mock_save: MagicMock,
        mock_client_cls: MagicMock,
        mock_load_cache: MagicMock,
        mock_clear_cache: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Non-interactive step 2 with --org UUID resolves via cached org list."""
        mock_load_cache.return_value = [
            {"id": 1, "name": "Acme Corp", "uuid": "abc-123"},
            {"id": 2, "name": "Side Project", "uuid": "def-456"},
        ]
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.api_url = "https://api.dailybot.com"
        mock_client.verify_code.return_value = {
            "token": "tok999",
            "user": {"email": "user@test.com"},
            "organization": {"id": 2, "name": "Side Project", "uuid": "def-456"},
        }

        result = runner.invoke(
            cli, ["login", "--email=user@test.com", "--code=654321", "--org=def-456"]
        )
        assert result.exit_code == 0
        assert "Logged in" in result.output
        assert "Side Project" in result.output
        # Should NOT call request_code (would invalidate the OTP)
        mock_client.request_code.assert_not_called()
        # Single verify call with resolved integer ID
        mock_client.verify_code.assert_called_once_with(
            "user@test.com", "654321", organization_id=2
        )
        mock_clear_cache.assert_called_once()

    @patch("dailybot_cli.commands.auth.load_org_cache")
    @patch("dailybot_cli.commands.auth.DailyBotClient")
    def test_login_non_interactive_verify_with_bad_org_uuid(
        self,
        mock_client_cls: MagicMock,
        mock_load_cache: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Non-interactive --org with unknown UUID shows error and org list."""
        mock_load_cache.return_value = [
            {"id": 1, "name": "Acme Corp", "uuid": "abc-123"},
        ]

        result = runner.invoke(
            cli, ["login", "--email=user@test.com", "--code=654321", "--org=wrong-uuid"]
        )
        assert result.exit_code != 0
        assert "not found" in result.output
        assert "Acme Corp" in result.output

    @patch("dailybot_cli.commands.auth.load_org_cache")
    def test_login_non_interactive_verify_with_org_no_cache(
        self,
        mock_load_cache: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Non-interactive --org without cached org list tells user to run step 1."""
        mock_load_cache.return_value = None

        result = runner.invoke(
            cli, ["login", "--email=user@test.com", "--code=654321", "--org=abc-123"]
        )
        assert result.exit_code != 0
        assert "No cached organization list" in result.output

    @patch("dailybot_cli.commands.auth.save_org_cache")
    @patch("dailybot_cli.commands.auth.DailyBotClient")
    def test_login_non_interactive_request_code_multi_org(
        self,
        mock_client_cls: MagicMock,
        mock_save_cache: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Non-interactive step 1: --email requests code, prints orgs, caches org list."""
        orgs = [
            {"id": 1, "name": "Acme Corp", "uuid": "abc-123"},
            {"id": 2, "name": "Side Project", "uuid": "def-456"},
        ]
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.api_url = "https://api.dailybot.com"
        mock_client.request_code.return_value = {
            "detail": "Verification code sent.",
            "organizations": orgs,
            "is_multi_org": True,
        }

        result = runner.invoke(cli, ["login", "--email=user@test.com"])
        assert result.exit_code == 0
        assert "Verification code sent" in result.output
        assert "Acme Corp" in result.output
        assert "uuid: abc-123" in result.output
        assert "Side Project" in result.output
        assert "uuid: def-456" in result.output
        assert "--code=CODE --org=ORG_UUID" in result.output
        # Should cache org list for step 2
        mock_save_cache.assert_called_once_with("user@test.com", orgs)
        # Should NOT prompt for code
        mock_client.verify_code.assert_not_called()

    @patch("dailybot_cli.commands.auth.DailyBotClient")
    def test_login_non_interactive_verify_requires_org(
        self,
        mock_client_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Non-interactive verify without --org when multi-org: prints orgs and instruction."""
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.api_url = "https://api.dailybot.com"
        mock_client.verify_code.return_value = {
            "requires_organization_selection": True,
            "organizations": [
                {"id": 1, "name": "Acme Corp", "uuid": "abc-123"},
                {"id": 2, "name": "Side Project", "uuid": "def-456"},
            ],
        }

        result = runner.invoke(cli, ["login", "--email=user@test.com", "--code=123456"])
        assert result.exit_code != 0
        assert "Acme Corp" in result.output
        assert "Side Project" in result.output
        assert "--org=ORG_UUID" in result.output

    @patch("dailybot_cli.commands.auth.DailyBotClient")
    @patch("dailybot_cli.commands.auth.save_credentials")
    def test_login_non_interactive_verify_auto_selects_single_org(
        self,
        mock_save: MagicMock,
        mock_client_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Non-interactive verify auto-selects when only one org available."""
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.api_url = "https://api.dailybot.com"
        # First call: requires org selection with 1 org
        # Second call (retry with org_id): returns token
        mock_client.verify_code.side_effect = [
            {
                "requires_organization_selection": True,
                "organizations": [{"id": 1, "name": "MyOrg", "uuid": "org-uuid"}],
            },
            {
                "token": "tok-auto",
                "organization": {"id": 1, "name": "MyOrg", "uuid": "org-uuid"},
            },
        ]

        result = runner.invoke(cli, ["login", "--email=user@test.com", "--code=123456"])
        assert result.exit_code == 0
        assert "Auto-selecting organization: MyOrg" in result.output
        assert "Logged in" in result.output
        assert mock_client.verify_code.call_count == 2
        mock_client.verify_code.assert_called_with("user@test.com", "123456", organization_id=1)

    @patch("dailybot_cli.commands.auth.DailyBotClient")
    def test_login_non_interactive_request_code_single_org(
        self,
        mock_client_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Non-interactive step 1 with single org: prints instructions without --org."""
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.api_url = "https://api.dailybot.com"
        mock_client.request_code.return_value = {
            "detail": "Verification code sent.",
            "organizations": [{"id": 1, "name": "MyOrg", "uuid": "org-uuid"}],
            "is_multi_org": False,
        }

        result = runner.invoke(cli, ["login", "--email=user@test.com"])
        assert result.exit_code == 0
        assert "Verification code sent" in result.output
        assert "--code=CODE" in result.output
        assert "--org" not in result.output
        mock_client.verify_code.assert_not_called()


class TestLogoutCommand:
    @patch("dailybot_cli.commands.auth.get_token")
    @patch("dailybot_cli.commands.auth.clear_credentials")
    @patch("dailybot_cli.commands.auth.DailyBotClient")
    def test_logout(
        self,
        mock_client_cls: MagicMock,
        mock_clear: MagicMock,
        mock_get_token: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.logout.return_value = {}

        result = runner.invoke(cli, ["logout"])
        assert result.exit_code == 0
        assert "Logged out" in result.output
        mock_clear.assert_called_once()

    @patch("dailybot_cli.commands.auth.get_token")
    def test_logout_not_logged_in(self, mock_get_token: MagicMock, runner: CliRunner) -> None:
        mock_get_token.return_value = None
        result = runner.invoke(cli, ["logout"])
        assert result.exit_code == 0
        assert "Not logged in" in result.output


class TestUpdateCommand:
    @patch("dailybot_cli.commands.update.get_agent_auth")
    @patch("dailybot_cli.commands.update.DailyBotClient")
    def test_update_message(
        self, mock_client_cls: MagicMock, mock_get_token: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_update.return_value = {
            "followups_count": 1,
            "attached_followups": [{"followup_name": "Standup"}],
        }

        result = runner.invoke(cli, ["update", "Finished auth module"])
        assert result.exit_code == 0
        assert "1 check-in" in result.output

    @patch("dailybot_cli.commands.update.get_agent_auth")
    @patch("dailybot_cli.commands.update.DailyBotClient")
    def test_update_structured(
        self, mock_client_cls: MagicMock, mock_get_token: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_update.return_value = {
            "followups_count": 1,
            "attached_followups": [{"followup_name": "Standup"}],
        }

        result = runner.invoke(
            cli, ["update", "--done", "Auth", "--doing", "Tests", "--blocked", "None"]
        )
        assert result.exit_code == 0
        mock_client.submit_update.assert_called_once_with(
            message=None, done="Auth", doing="Tests", blocked="None"
        )

    @patch("dailybot_cli.commands.update.get_agent_auth")
    @patch("dailybot_cli.commands.update.DailyBotClient")
    def test_update_shows_submitted_for_created(
        self, mock_client_cls: MagicMock, mock_get_token: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_update.return_value = {
            "followups_count": 1,
            "attached_followups": [{"followup_name": "Standup", "action": "created"}],
        }

        result = runner.invoke(cli, ["update", "Did some work"])
        assert result.exit_code == 0
        assert "Submitted" in result.output

    @patch("dailybot_cli.commands.update.get_agent_auth")
    @patch("dailybot_cli.commands.update.DailyBotClient")
    def test_update_shows_updated_for_enriched(
        self, mock_client_cls: MagicMock, mock_get_token: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_update.return_value = {
            "followups_count": 1,
            "attached_followups": [{"followup_name": "Standup", "action": "updated"}],
        }

        result = runner.invoke(cli, ["update", "More progress"])
        assert result.exit_code == 0
        assert "Updated" in result.output

    @patch("dailybot_cli.commands.update.get_agent_auth")
    @patch("dailybot_cli.commands.update.DailyBotClient")
    def test_update_ai_processing_failed(
        self, mock_client_cls: MagicMock, mock_get_token: MagicMock, runner: CliRunner
    ) -> None:
        from dailybot_cli.api_client import APIError

        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_update.side_effect = APIError(400, "AI processing failed for input")

        result = runner.invoke(cli, ["update", "???"])
        assert result.exit_code != 0
        assert "could not process" in result.output
        assert "support@dailybot.com" in result.output

    @patch("dailybot_cli.commands.update.get_agent_auth")
    @patch("dailybot_cli.commands.update.DailyBotClient")
    def test_update_timeout(
        self, mock_client_cls: MagicMock, mock_get_token: MagicMock, runner: CliRunner
    ) -> None:
        import httpx

        mock_get_token.return_value = "tok"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_update.side_effect = httpx.ReadTimeout("timed out")

        result = runner.invoke(cli, ["update", "test"])
        assert result.exit_code != 0
        assert "timed out" in result.output

    @patch("dailybot_cli.commands.update.get_agent_auth")
    @patch("dailybot_cli.commands.update.DailyBotClient")
    def test_update_works_with_api_key(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        """`dailybot update` works with an API key and no login session."""
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_update.return_value = {
            "followups_count": 1,
            "attached_followups": [{"followup_name": "Standup"}],
        }

        result = runner.invoke(cli, ["update", "Shipped the API-key parity fix"])
        assert result.exit_code == 0

    @patch("dailybot_cli.commands.update.get_agent_auth")
    def test_update_not_authenticated(self, mock_get_auth: MagicMock, runner: CliRunner) -> None:
        mock_get_auth.return_value = None
        result = runner.invoke(cli, ["update", "test"])
        assert result.exit_code != 0


class TestStatusCommand:
    @patch("dailybot_cli.commands.status.get_agent_auth")
    @patch("dailybot_cli.commands.status.DailyBotClient")
    def test_status_with_checkins(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "bearer"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_status.return_value = {
            "count": 1,
            "pending_checkins": [
                {
                    "followup_name": "Daily Standup",
                    "template_questions": [
                        {"question": "What did you do?", "is_blocker": False},
                    ],
                }
            ],
        }

        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "Daily Standup" in result.output

    @patch("dailybot_cli.commands.status.get_agent_auth")
    @patch("dailybot_cli.commands.status.DailyBotClient")
    def test_status_no_checkins(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "bearer"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_status.return_value = {"count": 0, "pending_checkins": []}

        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "No pending" in result.output

    @patch("dailybot_cli.commands.status.get_agent_auth")
    @patch("dailybot_cli.commands.status.DailyBotClient")
    def test_status_works_with_api_key(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        """`dailybot status` works with an API key and no login session."""
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_status.return_value = {"count": 0, "pending_checkins": []}

        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0

    @patch("dailybot_cli.commands.status.get_agent_auth")
    @patch("dailybot_cli.commands.status.DailyBotClient")
    def test_status_json_flag(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        """CORE-2262: --json emits machine-readable output."""
        mock_get_auth.return_value = "bearer"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_status.return_value = {
            "count": 1,
            "pending_checkins": [
                {
                    "followup_name": "Daily Standup",
                    "template_questions": [
                        {"question": "What did you do?", "is_blocker": False},
                    ],
                }
            ],
        }

        result = runner.invoke(cli, ["status", "--json"])
        assert result.exit_code == 0
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["count"] == 1
        assert len(payload["pending_checkins"]) == 1
        assert payload["pending_checkins"][0]["followup_name"] == "Daily Standup"

    @patch("dailybot_cli.commands.status.get_agent_auth")
    @patch("dailybot_cli.commands.status.DailyBotClient")
    def test_status_json_empty(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "bearer"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_status.return_value = {"count": 0, "pending_checkins": []}

        result = runner.invoke(cli, ["status", "--json"])
        assert result.exit_code == 0
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["count"] == 0
        assert payload["pending_checkins"] == []

    @patch("dailybot_cli.commands.status.get_agent_auth")
    def test_status_not_authenticated(self, mock_get_auth: MagicMock, runner: CliRunner) -> None:
        mock_get_auth.return_value = None
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 1
        assert "Not authenticated" in result.output

    @patch("dailybot_cli.commands.status.get_api_key")
    @patch("dailybot_cli.commands.status.get_token")
    @patch("dailybot_cli.commands.status.DailyBotClient")
    def test_status_auth_valid_login(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        mock_get_api_key: MagicMock,
        runner: CliRunner,
    ) -> None:
        """--auth with valid OTP session shows login auth info."""
        mock_get_token.return_value = "tok"
        mock_get_api_key.return_value = None
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.auth_status.return_value = {
            "user": {"email": "user@test.com"},
            "organization": {"name": "MyOrg", "uuid": "org-uuid"},
        }
        mock_client._agent_auth_mode = "bearer"

        result = runner.invoke(cli, ["status", "--auth"])
        assert result.exit_code == 0
        assert "login (OTP)" in result.output
        assert "user@test.com" in result.output
        assert "MyOrg" in result.output

    @patch("dailybot_cli.commands.status.get_api_key")
    @patch("dailybot_cli.commands.status.get_token")
    @patch("dailybot_cli.commands.status.DailyBotClient")
    def test_status_auth_valid_api_key(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        mock_get_api_key: MagicMock,
        runner: CliRunner,
    ) -> None:
        """--auth reports 'API key' when the client used the API key path
        (either because no login token exists, or because env.json is
        active and forces the API key as the effective credential)."""
        mock_get_token.return_value = None
        mock_get_api_key.return_value = "sk-abc123"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.auth_status.return_value = {
            "user": {"email": "user@test.com"},
            "organization": {"name": "MyOrg", "uuid": "org-uuid"},
        }
        mock_client._agent_auth_mode = "api_key"

        result = runner.invoke(cli, ["status", "--auth"])
        assert result.exit_code == 0
        assert "API key" in result.output
        assert "sk-a****" in result.output

    @patch("dailybot_cli.commands.status.get_api_key")
    @patch("dailybot_cli.commands.status.get_token")
    @patch("dailybot_cli.commands.status.DailyBotClient")
    def test_status_auth_expired_login_transparently_falls_back(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        mock_get_api_key: MagicMock,
        runner: CliRunner,
    ) -> None:
        """--auth with an expired login + valid API key succeeds silently:
        the client's internal alt-credential retry (Bearer → API key) means
        ``status --auth`` never surfaces the intermediate failure. The final
        reported credential is the API key because that's what actually
        succeeded on the wire."""
        mock_get_token.return_value = "expired-tok"
        mock_get_api_key.return_value = "sk-xyz789"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.auth_status.return_value = {
            "user": {"email": "user@test.com"},
            "organization": {"name": "MyOrg", "uuid": "org-uuid"},
        }
        mock_client._agent_auth_mode = "api_key"

        result = runner.invoke(cli, ["status", "--auth"])
        assert result.exit_code == 0
        assert "invalid or expired" not in result.output
        assert "API key" in result.output
        assert "sk-x****" in result.output

    @patch("dailybot_cli.commands.status.get_api_key")
    @patch("dailybot_cli.commands.status.get_token")
    @patch("dailybot_cli.commands.status.DailyBotClient")
    def test_status_auth_both_credentials_rejected(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        mock_get_api_key: MagicMock,
        runner: CliRunner,
    ) -> None:
        """When both Bearer and API key are on disk AND the API rejects both
        (401/403), the CLI surfaces a distinctive error that names both
        credentials — otherwise the user cannot tell whether the login is
        expired, the API key is wrong, or both."""
        from dailybot_cli.api_client import APIError

        mock_get_token.return_value = "expired-tok"
        mock_get_api_key.return_value = "sk-xyz789"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.auth_status.side_effect = APIError(401, "Unauthorized")

        result = runner.invoke(cli, ["status", "--auth"])
        assert result.exit_code == 1
        assert "Both credentials were rejected" in result.output

    @patch("dailybot_cli.commands.status.get_api_key")
    @patch("dailybot_cli.commands.status.get_token")
    def test_status_auth_no_credentials(
        self,
        mock_get_token: MagicMock,
        mock_get_api_key: MagicMock,
        runner: CliRunner,
    ) -> None:
        """--auth with no credentials shows error."""
        mock_get_token.return_value = None
        mock_get_api_key.return_value = None

        result = runner.invoke(cli, ["status", "--auth"])
        assert result.exit_code != 0
        assert "Not authenticated" in result.output


class TestInteractiveLogin:
    @patch("dailybot_cli.commands.interactive.questionary")
    @patch("dailybot_cli.commands.interactive._do_login")
    @patch("dailybot_cli.commands.interactive.load_credentials")
    @patch("dailybot_cli.commands.interactive.get_token")
    def test_interactive_guides_login_when_not_authenticated(
        self,
        mock_get_token: MagicMock,
        mock_load_creds: MagicMock,
        mock_do_login: MagicMock,
        mock_questionary: MagicMock,
        runner: CliRunner,
    ) -> None:
        # First call: not logged in; second call (after _do_login): return creds
        mock_get_token.return_value = None
        mock_load_creds.side_effect = [
            None,
            {"token": "tok", "email": "u@t.com", "organization": "Org"},
        ]
        # Mock questionary.select to return the exit action ID
        mock_questionary.select.return_value.ask.return_value = "exit"
        # Provide email for the prompt (code is handled inside _do_login which is mocked)
        runner.invoke(cli, [], input="u@t.com\n")
        mock_do_login.assert_called_once_with("u@t.com")


class TestInteractiveChatCommand:
    @patch("dailybot_cli.tui.app.run_chat_app")
    @patch("dailybot_cli.commands.interactive_chat.require_auth")
    def test_interactive_alias_launches_textual_app(
        self,
        mock_require_auth: MagicMock,
        mock_run_chat_app: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_client: MagicMock = MagicMock()
        mock_require_auth.return_value = mock_client

        result = runner.invoke(cli, ["interactive"])

        assert result.exit_code == 0
        # Deprecated alias, but still opens the chat via require_auth (either credential).
        assert "deprecated" in result.output.lower()
        mock_require_auth.assert_called_once_with()
        mock_run_chat_app.assert_called_once_with(mock_client)

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    def test_interactive_not_authenticated(
        self,
        mock_get_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        """With neither credential, the AI chat exits 3 (not authenticated)."""
        mock_get_auth.return_value = None
        result = runner.invoke(cli, ["interactive"])
        assert result.exit_code == 3
        assert "Not authenticated" in result.output


class TestAskCommand:
    @patch("dailybot_cli.commands.ask.require_auth")
    def test_ask_headless_prints_answer(
        self, mock_require_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_client: MagicMock = MagicMock()
        mock_client.create_chat_completion.return_value = {
            "message": {"role": "assistant", "content": "You have 1 pending check-in."},
        }
        mock_require_auth.return_value = mock_client

        result = runner.invoke(cli, ["ask", "What are my check-ins?"])

        assert result.exit_code == 0
        assert "You have 1 pending check-in." in result.output
        mock_client.create_chat_completion.assert_called_once_with(
            message="What are my check-ins?", session_id=None
        )

    @patch("dailybot_cli.commands.ask.require_auth")
    def test_ask_json_output(self, mock_require_auth: MagicMock, runner: CliRunner) -> None:
        mock_client: MagicMock = MagicMock()
        mock_client.create_chat_completion.return_value = {
            "message": {"content": "Done."},
            "actions": [{"name": "open_form"}],
            "classification": "action",
            "session_id": "sess-1",
        }
        mock_require_auth.return_value = mock_client

        result = runner.invoke(cli, ["ask", "do it", "--json", "--session-id", "sess-1"])

        assert result.exit_code == 0
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["message"] == "Done."
        assert payload["actions"] == [{"name": "open_form"}]
        assert payload["session_id"] == "sess-1"
        mock_client.create_chat_completion.assert_called_once_with(
            message="do it", session_id="sess-1"
        )

    @patch("dailybot_cli.commands.ask.launch_chat_tui")
    @patch("dailybot_cli.commands.ask.require_auth")
    def test_ask_without_message_launches_tui(
        self, mock_require_auth: MagicMock, mock_launch_tui: MagicMock, runner: CliRunner
    ) -> None:
        mock_client: MagicMock = MagicMock()
        mock_require_auth.return_value = mock_client

        result = runner.invoke(cli, ["ask"])

        assert result.exit_code == 0
        mock_launch_tui.assert_called_once_with(mock_client)
        mock_client.create_chat_completion.assert_not_called()

    @patch("dailybot_cli.commands.ask.require_auth")
    def test_ask_reads_piped_stdin(self, mock_require_auth: MagicMock, runner: CliRunner) -> None:
        mock_client: MagicMock = MagicMock()
        mock_client.create_chat_completion.return_value = {"message": {"content": "ok"}}
        mock_require_auth.return_value = mock_client

        result = runner.invoke(cli, ["ask"], input="draft my standup\n")

        assert result.exit_code == 0
        mock_client.create_chat_completion.assert_called_once_with(
            message="draft my standup", session_id=None
        )

    @patch("dailybot_cli.commands.public_api_helpers.get_agent_auth")
    def test_ask_not_authenticated(self, mock_get_auth: MagicMock, runner: CliRunner) -> None:
        mock_get_auth.return_value = None
        result = runner.invoke(cli, ["ask", "hello"])
        assert result.exit_code == 3

    @patch("dailybot_cli.commands.ask.require_auth")
    def test_ask_api_error(self, mock_require_auth: MagicMock, runner: CliRunner) -> None:
        mock_client: MagicMock = MagicMock()
        mock_client.create_chat_completion.side_effect = APIError(401, "Unauthorized")
        mock_require_auth.return_value = mock_client

        result = runner.invoke(cli, ["ask", "hello"])
        assert result.exit_code == 3

    @patch("dailybot_cli.commands.ask.require_auth")
    def test_ask_rate_limited_text(self, mock_require_auth: MagicMock, runner: CliRunner) -> None:
        mock_client: MagicMock = MagicMock()
        mock_client.create_chat_completion.side_effect = APIError(
            429, "Request was throttled.", retry_after=2.0
        )
        mock_require_auth.return_value = mock_client

        result = runner.invoke(cli, ["ask", "hello"])
        assert result.exit_code == 6
        assert "Try again in 2s" in result.output

    @patch("dailybot_cli.commands.ask.require_auth")
    def test_ask_rate_limited_json(self, mock_require_auth: MagicMock, runner: CliRunner) -> None:
        mock_client: MagicMock = MagicMock()
        mock_client.create_chat_completion.side_effect = APIError(
            429, "Request was throttled.", retry_after=2.0
        )
        mock_require_auth.return_value = mock_client

        result = runner.invoke(cli, ["ask", "hello", "--json"])
        assert result.exit_code == 6
        payload: dict[str, Any] = json.loads(result.output)
        assert payload["status"] == 429
        assert payload["retry_after_seconds"] == 2


class TestInteractiveMenu:
    @patch("dailybot_cli.commands.interactive.pick_from_list")
    @patch("dailybot_cli.commands.interactive.questionary")
    @patch("dailybot_cli.commands.interactive.load_credentials")
    @patch("dailybot_cli.commands.interactive.get_token")
    @patch("dailybot_cli.commands.interactive.execute_kudos_give")
    @patch("dailybot_cli.commands.interactive.get_current_user_uuid")
    @patch("dailybot_cli.commands.interactive.DailyBotClient")
    def test_interactive_give_kudos_picks_teammate(
        self,
        mock_client_cls: MagicMock,
        mock_current_uuid: MagicMock,
        mock_execute_kudos: MagicMock,
        mock_get_token: MagicMock,
        mock_load_creds: MagicMock,
        mock_questionary: MagicMock,
        mock_pick_from_list: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_load_creds.return_value = {
            "token": "tok",
            "email": "me@example.com",
            "organization": "Org",
            "api_url": "https://api.dailybot.com",
        }
        mock_current_uuid.return_value = "self-uuid"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.list_users.return_value = [
            {"uuid": "self-uuid", "full_name": "Me"},
            {"uuid": "peer-uuid", "full_name": "Jane Doe"},
        ]
        mock_questionary.select.return_value.ask.side_effect = ["team.kudos", "exit"]
        mock_pick_from_list.return_value = {"uuid": "peer-uuid", "full_name": "Jane Doe"}
        mock_questionary.text.return_value.ask.return_value = "Great work!"

        result = runner.invoke(cli, [])
        assert result.exit_code == 0
        mock_execute_kudos.assert_called_once()
        call_args = mock_execute_kudos.call_args
        assert call_args.args[1] == "Great work!"
        assert call_args.kwargs["user_receivers"] == [("peer-uuid", "Jane Doe")]
        assert call_args.kwargs["assume_yes"] is True

    @patch("dailybot_cli.commands.interactive_chat.launch_chat_tui")
    @patch("dailybot_cli.commands.interactive.questionary")
    @patch("dailybot_cli.commands.interactive.load_credentials")
    @patch("dailybot_cli.commands.interactive.get_token")
    @patch("dailybot_cli.commands.interactive.DailyBotClient")
    def test_interactive_menu_ask_ai_launches_chat_and_returns(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        mock_load_creds: MagicMock,
        mock_questionary: MagicMock,
        mock_launch_tui: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Picking the AI option opens the chat TUI, then the loop returns to the menu."""
        mock_get_token.return_value = "tok"
        mock_load_creds.return_value = {
            "token": "tok",
            "email": "me@example.com",
            "organization": "Org",
            "api_url": "https://api.dailybot.com",
        }
        mock_client: MagicMock = mock_client_cls.return_value
        # Select "Ask the Dailybot AI", then Exit — proving control returns to the menu.
        mock_questionary.select.return_value.ask.side_effect = ["ask.ai", "exit"]

        result = runner.invoke(cli, [])
        assert result.exit_code == 0
        mock_launch_tui.assert_called_once_with(mock_client)
        assert mock_questionary.select.return_value.ask.call_count == 2

    @patch("dailybot_cli.commands.interactive.get_api_key")
    @patch("dailybot_cli.commands.interactive.questionary")
    @patch("dailybot_cli.commands.interactive.load_credentials")
    @patch("dailybot_cli.commands.interactive.get_token")
    @patch("dailybot_cli.commands.interactive.DailyBotClient")
    def test_interactive_send_chat_to_channel(
        self,
        mock_client_cls: MagicMock,
        mock_get_token: MagicMock,
        mock_load_creds: MagicMock,
        mock_questionary: MagicMock,
        mock_get_api_key: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_load_creds.return_value = {
            "token": "tok",
            "email": "me@example.com",
            "organization": "Org",
            "api_url": "https://api.dailybot.com",
        }
        mock_get_api_key.return_value = "org-key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.send_chat_message.return_value = {"bot_message_id": "555"}
        # Menu: chat.send then exit; target select: channel; confirm: True
        mock_questionary.select.return_value.ask.side_effect = ["chat.send", "channel", "exit"]
        mock_questionary.text.return_value.ask.side_effect = ["C0123", "Deploy done", ""]
        mock_questionary.confirm.return_value.ask.return_value = True

        result = runner.invoke(cli, [])
        assert result.exit_code == 0
        mock_client.send_chat_message.assert_called_once_with(
            {"message": "Deploy done", "target_channels": ["C0123"]}
        )


class TestAgentCommand:
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_update(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {"id": 1, "uuid": "abc"}

        result = runner.invoke(cli, ["agent", "update", "Deployed v2.1", "--name", "Claude Code"])
        assert result.exit_code == 0
        assert "Report submitted" in result.output

    @patch("dailybot_cli.commands.agent.ledger")
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_update_marks_report_ledger(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        mock_ledger: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {"id": 1, "uuid": "abc"}

        result = runner.invoke(cli, ["agent", "update", "Deployed v2.1", "--name", "Claude Code"])
        assert result.exit_code == 0
        mock_ledger.mark_reported.assert_called_once_with(reported_by="Claude Code")

    @patch("dailybot_cli.commands.agent.ledger")
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_update_succeeds_when_ledger_fails(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        mock_ledger: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {"id": 1, "uuid": "abc"}
        mock_ledger.mark_reported.side_effect = RuntimeError("disk full")

        result = runner.invoke(cli, ["agent", "update", "Deployed v2.1", "--name", "Claude Code"])
        assert result.exit_code == 0
        assert "Report submitted" in result.output

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_update_shows_placement_url(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {
            "id": 1,
            "uuid": "abc",
            "url": "https://app.dailybot.com/agents/report/abc",
        }

        result = runner.invoke(cli, ["agent", "update", "Deployed v2.1", "--name", "Claude Code"])
        assert result.exit_code == 0
        assert "Report submitted" in result.output
        assert "https://app.dailybot.com/agents/report/abc" in result.output

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_update_without_url_omits_link(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {"id": 1, "uuid": "abc"}

        result = runner.invoke(cli, ["agent", "update", "Deployed v2.1", "--name", "Claude Code"])
        assert result.exit_code == 0
        assert "Report submitted" in result.output
        assert "View:" not in result.output

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_update_keeps_long_url_on_view_line(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        """A long placement URL must stay on the same line as the 'View:' label.

        Rich word-wraps at the default 80-column width, which would push a
        long, unbreakable URL onto its own line and leave 'View:' orphaned.
        The renderer disables wrapping so the label and URL stay together.
        """
        mock_get_auth.return_value = "api_key"
        long_url: str = (
            "https://app.dailybot.com/agents/report/b59abb71-fdb6-4d4f-b0f2-1bf5399b15e4"
        )
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {"id": 1, "uuid": "abc", "url": long_url}

        result = runner.invoke(cli, ["agent", "update", "Deployed v2.1", "--name", "Claude Code"])
        assert result.exit_code == 0
        assert f"View: {long_url}" in result.output

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_update_with_metadata(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {"id": 2, "uuid": "def"}

        result = runner.invoke(
            cli,
            [
                "agent",
                "update",
                "Fixed login bug",
                "--name",
                "Claude Code",
                "--metadata",
                '{"repo": "api-services", "branch": "fix/login", "pr": "#142"}',
            ],
        )
        assert result.exit_code == 0
        assert "Report submitted" in result.output
        mock_client.submit_agent_report.assert_called_once_with(
            agent_name="Claude Code",
            content="Fixed login bug",
            structured=None,
            metadata={"repo": "api-services", "branch": "fix/login", "pr": "#142"},
            is_milestone=False,
            co_authors=None,
        )

    @patch("dailybot_cli.commands.agent.get_default_profile", return_value=None)
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    def test_agent_update_no_api_key(
        self, mock_get_auth: MagicMock, _mock_profile: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = None
        result = runner.invoke(cli, ["agent", "update", "test"])
        assert result.exit_code != 0

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_health_ok(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_health.return_value = {
            "agent_name": "Claude Code",
            "status": "healthy",
            "last_check": "2025-01-01T00:00:00Z",
            "history": [],
        }

        result = runner.invoke(
            cli, ["agent", "health", "--ok", "--message", "All good", "--name", "Claude Code"]
        )
        assert result.exit_code == 0
        assert "healthy" in result.output
        assert "Claude Code" in result.output
        mock_client.submit_agent_health.assert_called_once_with(
            agent_name="Claude Code", ok=True, message="All good"
        )

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_health_fail(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_health.return_value = {
            "agent_name": "CI Bot",
            "status": "unhealthy",
            "last_check": "2025-01-01T00:00:00Z",
            "history": [],
        }

        result = runner.invoke(
            cli, ["agent", "health", "--fail", "--message", "DB down", "--name", "CI Bot"]
        )
        assert result.exit_code == 0
        assert "unhealthy" in result.output
        assert "CI Bot" in result.output
        mock_client.submit_agent_health.assert_called_once_with(
            agent_name="CI Bot", ok=False, message="DB down"
        )

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_health_status(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_agent_health.return_value = {
            "agent_name": "Claude Code",
            "status": "healthy",
            "last_check": "2025-01-01T00:00:00Z",
            "history": [
                {"timestamp": "2025-01-01T00:00:00Z", "status": "healthy", "message": "All good"},
            ],
        }

        result = runner.invoke(cli, ["agent", "health", "--status", "--name", "Claude Code"])
        assert result.exit_code == 0
        assert "healthy" in result.output
        assert "Claude Code" in result.output
        mock_client.get_agent_health.assert_called_once_with(agent_name="Claude Code")

    @patch("dailybot_cli.commands.agent.get_default_profile", return_value=None)
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    def test_agent_health_no_api_key(
        self, mock_get_auth: MagicMock, _mock_profile: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = None
        result = runner.invoke(cli, ["agent", "health", "--ok"])
        assert result.exit_code != 0

    def test_agent_health_no_flag(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["agent", "health"])
        assert result.exit_code != 0

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_health_with_pending_messages(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_health.return_value = {
            "agent_name": "Claude Code",
            "status": "healthy",
            "last_check": "2025-01-01T00:00:00Z",
            "history": [],
            "pending_messages": [
                {
                    "id": "uuid-1",
                    "content": "Please review PR #42",
                    "message_type": "text",
                    "sender_type": "human",
                    "sender_name": "John Doe",
                    "created_at": "2025-01-01T00:00:00Z",
                },
                {
                    "id": "uuid-2",
                    "content": "New deployment ready",
                    "message_type": "system",
                    "sender_type": "system",
                    "sender_name": None,
                    "created_at": "2025-01-01T00:00:00Z",
                },
            ],
        }

        result = runner.invoke(cli, ["agent", "health", "--ok", "--name", "Claude Code"])
        assert result.exit_code == 0
        assert "Pending messages from Dailybot (2)" in result.output
        assert "[id:uuid-1]" in result.output
        assert "Please review PR #42" in result.output
        assert "John Doe:" in result.output
        assert "[id:uuid-2]" in result.output
        assert "New deployment ready" in result.output
        assert "[system]:" in result.output
        assert "dailybot agent message claim <id>" in result.output

    # --- Webhook tests ---

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_webhook_register(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.register_agent_webhook.return_value = {
            "agent_name": "Claude Code",
            "webhook_url": "https://my-server.com/hook",
        }

        result = runner.invoke(
            cli,
            [
                "agent",
                "webhook",
                "register",
                "--url",
                "https://my-server.com/hook",
                "--secret",
                "my-token",
                "--name",
                "Claude Code",
            ],
        )
        assert result.exit_code == 0
        assert "Webhook Registered" in result.output
        assert "https://my-server.com/hook" in result.output
        mock_client.register_agent_webhook.assert_called_once_with(
            agent_name="Claude Code",
            webhook_url="https://my-server.com/hook",
            webhook_secret="my-token",
        )

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_webhook_unregister(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.unregister_agent_webhook.return_value = {
            "detail": "Webhook unregistered.",
        }

        result = runner.invoke(cli, ["agent", "webhook", "unregister", "--name", "Claude Code"])
        assert result.exit_code == 0
        assert "Webhook unregistered" in result.output

    @patch("dailybot_cli.commands.agent.get_default_profile", return_value=None)
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    def test_webhook_register_no_api_key(
        self, mock_get_auth: MagicMock, _mock_profile: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = None
        result = runner.invoke(
            cli, ["agent", "webhook", "register", "--url", "https://example.com/hook"]
        )
        assert result.exit_code != 0

    @patch("dailybot_cli.commands.agent.get_default_profile", return_value=None)
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    def test_webhook_unregister_no_api_key(
        self, mock_get_auth: MagicMock, _mock_profile: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = None
        result = runner.invoke(cli, ["agent", "webhook", "unregister"])
        assert result.exit_code != 0

    # --- Message tests ---

    @patch("dailybot_cli.commands.agent.get_default_profile", return_value=None)
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_message_send(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        _mock_profile: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.send_agent_message.return_value = {
            "id": "msg-uuid",
            "agent_name": "Claude Code",
            "content": "Review PR #42",
            "message_type": "text",
            "sender_type": "agent",
            "sender_name": "CLI Agent",
            "delivered": False,
            "created_at": "2025-01-01T00:00:00Z",
        }

        result = runner.invoke(
            cli,
            ["agent", "message", "send", "--to", "Claude Code", "--content", "Review PR #42"],
        )
        assert result.exit_code == 0
        assert "Message Sent" in result.output
        assert "Review PR #42" in result.output
        assert "CLI Agent" in result.output
        mock_client.send_agent_message.assert_called_once_with(
            agent_name="Claude Code",
            content="Review PR #42",
            message_type=None,
            metadata=None,
            expires_at=None,
            sender_type="agent",
            sender_name="CLI Agent",
        )

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_message_send_with_type(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.send_agent_message.return_value = {
            "id": "msg-uuid",
            "agent_name": "Claude Code",
            "content": "Do X",
            "message_type": "command",
            "sender_type": "agent",
            "sender_name": "My Bot",
            "delivered": False,
            "created_at": "2025-01-01T00:00:00Z",
        }

        result = runner.invoke(
            cli,
            [
                "agent",
                "message",
                "send",
                "--to",
                "Claude Code",
                "--content",
                "Do X",
                "--type",
                "command",
                "--name",
                "My Bot",
            ],
        )
        assert result.exit_code == 0
        assert "Message Sent" in result.output
        mock_client.send_agent_message.assert_called_once_with(
            agent_name="Claude Code",
            content="Do X",
            message_type="command",
            metadata=None,
            expires_at=None,
            sender_type="agent",
            sender_name="My Bot",
        )

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_message_list(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_agent_messages.return_value = [
            {
                "id": "msg-1",
                "content": "Review PR #42",
                "message_type": "text",
                "sender_type": "human",
                "sender_name": "John Doe",
                "delivered": False,
                "created_at": "2025-01-01T00:00:00Z",
            },
            {
                "id": "msg-2",
                "content": "Deploy done",
                "message_type": "system",
                "sender_type": "agent",
                "sender_name": "CI Bot",
                "delivered": True,
                "created_at": "2025-01-01T01:00:00Z",
            },
        ]

        result = runner.invoke(cli, ["agent", "message", "list", "--name", "Claude Code"])
        assert result.exit_code == 0
        assert "Review PR #42" in result.output
        assert "John Doe" in result.output
        assert "Deploy done" in result.output
        assert "CI Bot" in result.output
        mock_client.get_agent_messages.assert_called_once_with(
            agent_name="Claude Code", delivered=None
        )

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_message_list_pending(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_agent_messages.return_value = []

        result = runner.invoke(
            cli, ["agent", "message", "list", "--name", "Claude Code", "--pending"]
        )
        assert result.exit_code == 0
        assert "No messages" in result.output
        mock_client.get_agent_messages.assert_called_once_with(
            agent_name="Claude Code", delivered=False
        )

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_message_list_paginated_envelope(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        """Regression: API returns a paginated envelope {count, results} — CORE-2260."""
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_agent_messages.return_value = [
            {
                "id": "msg-1",
                "content": "Hello",
                "message_type": "text",
                "sender_type": "human",
                "sender_name": "Jane",
                "delivered": False,
                "created_at": "2026-07-11T00:00:00Z",
            },
        ]
        result = runner.invoke(cli, ["agent", "message", "list", "--name", "Bot"])
        assert result.exit_code == 0
        assert "Hello" in result.output
        assert "Jane" in result.output

    @patch("dailybot_cli.commands.agent.get_default_profile", return_value=None)
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    def test_message_send_no_api_key(
        self, mock_get_auth: MagicMock, _mock_profile: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = None
        result = runner.invoke(cli, ["agent", "message", "send", "--to", "Bot", "--content", "hi"])
        assert result.exit_code != 0

    @patch("dailybot_cli.commands.agent.get_default_profile", return_value=None)
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    def test_message_list_no_api_key(
        self, mock_get_auth: MagicMock, _mock_profile: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = None
        result = runner.invoke(cli, ["agent", "message", "list", "--name", "Bot"])
        assert result.exit_code != 0

    @patch("dailybot_cli.commands.agent.get_default_profile", return_value=None)
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_update_milestone(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        _mock_profile: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {
            "id": 10,
            "is_milestone": True,
        }

        result = runner.invoke(cli, ["agent", "update", "Big feature", "--milestone"])
        assert result.exit_code == 0
        assert "[Milestone]" in result.output
        mock_client.submit_agent_report.assert_called_once_with(
            agent_name="CLI Agent",
            content="Big feature",
            structured=None,
            metadata=None,
            is_milestone=True,
            co_authors=None,
        )

    @patch("dailybot_cli.commands.agent.get_default_profile", return_value=None)
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_update_co_authors(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        _mock_profile: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {
            "id": 11,
            "co_authors": [
                {"name": "Alice", "uuid": "a-uuid"},
                {"name": "Bob", "uuid": "b-uuid"},
            ],
        }

        result = runner.invoke(
            cli,
            [
                "agent",
                "update",
                "Paired work",
                "--co-authors",
                "alice@co.com",
                "--co-authors",
                "bob@co.com",
            ],
        )
        assert result.exit_code == 0
        assert "Co-authors: Alice, Bob" in result.output
        mock_client.submit_agent_report.assert_called_once_with(
            agent_name="CLI Agent",
            content="Paired work",
            structured=None,
            metadata=None,
            is_milestone=False,
            co_authors=["alice@co.com", "bob@co.com"],
        )

    @patch("dailybot_cli.commands.agent.get_default_profile", return_value=None)
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_update_co_authors_comma_separated(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        _mock_profile: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {
            "id": 12,
            "co_authors": [
                {"name": "Alice", "uuid": "a-uuid"},
                {"name": "Bob", "uuid": "b-uuid"},
            ],
        }

        result = runner.invoke(
            cli, ["agent", "update", "Paired work", "--co-authors", "alice@co.com,bob@co.com"]
        )
        assert result.exit_code == 0
        assert "Co-authors: Alice, Bob" in result.output
        mock_client.submit_agent_report.assert_called_once_with(
            agent_name="CLI Agent",
            content="Paired work",
            structured=None,
            metadata=None,
            is_milestone=False,
            co_authors=["alice@co.com", "bob@co.com"],
        )

    @patch("dailybot_cli.commands.agent.get_default_profile", return_value=None)
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_update_milestone_and_co_authors(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        _mock_profile: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {
            "id": 13,
            "is_milestone": True,
            "co_authors": [{"name": "Alice", "uuid": "a-uuid"}],
        }

        result = runner.invoke(
            cli, ["agent", "update", "Big feature", "--milestone", "--co-authors", "alice@co.com"]
        )
        assert result.exit_code == 0
        assert "[Milestone]" in result.output
        assert "Co-authors: Alice" in result.output
        mock_client.submit_agent_report.assert_called_once_with(
            agent_name="CLI Agent",
            content="Big feature",
            structured=None,
            metadata=None,
            is_milestone=True,
            co_authors=["alice@co.com"],
        )

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_agent_update_with_pending_messages(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {
            "id": 14,
            "pending_messages": [
                {
                    "id": "uuid-1",
                    "sender_type": "human",
                    "sender_name": "John Doe",
                    "content": "Please review PR #42",
                },
                {
                    "id": "uuid-2",
                    "sender_type": "system",
                    "sender_name": "",
                    "content": "New deployment ready",
                },
            ],
        }

        result = runner.invoke(cli, ["agent", "update", "Did some work"])
        assert result.exit_code == 0
        assert "Report submitted" in result.output
        assert "Pending messages from Dailybot (2)" in result.output
        assert "[id:uuid-1]" in result.output
        assert "John Doe:" in result.output
        assert "Please review PR #42" in result.output
        assert "[id:uuid-2]" in result.output
        assert "New deployment ready" in result.output
        assert "dailybot agent message claim <id>" in result.output

    @patch("dailybot_cli.commands.agent.get_default_profile", return_value=None)
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    def test_agent_no_auth(
        self, mock_get_auth: MagicMock, _mock_profile: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = None
        result = runner.invoke(cli, ["agent", "update", "test"])
        assert result.exit_code != 0
        assert "dailybot config key=" in result.output
        assert "dailybot login" in result.output


class TestAgentEmailCommand:
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_email_send(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.send_agent_email.return_value = {
            "sent_count": 1,
            "total_recipients": 1,
            "reply_to": "ag-abc@mail.dailybot.com",
        }

        result = runner.invoke(
            cli,
            [
                "agent",
                "email",
                "send",
                "--to",
                "user@example.com",
                "--subject",
                "Build passed",
                "--body-html",
                "<p>All green.</p>",
                "--name",
                "Claude Code",
            ],
        )
        assert result.exit_code == 0
        assert "Email Sent" in result.output
        assert "1 of 1" in result.output
        assert "ag-abc@mail.dailybot.com" in result.output
        mock_client.send_agent_email.assert_called_once_with(
            agent_name="Claude Code",
            to=["user@example.com"],
            subject="Build passed",
            body_html="<p>All green.</p>",
            metadata=None,
        )

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_email_send_multiple_recipients(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.send_agent_email.return_value = {
            "sent_count": 2,
            "total_recipients": 2,
            "reply_to": "ag-abc@mail.dailybot.com",
        }

        result = runner.invoke(
            cli,
            [
                "agent",
                "email",
                "send",
                "--to",
                "a@co.com",
                "--to",
                "b@co.com",
                "--subject",
                "Report",
                "--body-html",
                "<h1>Done</h1>",
                "--name",
                "CI Bot",
            ],
        )
        assert result.exit_code == 0
        assert "2 of 2" in result.output
        mock_client.send_agent_email.assert_called_once_with(
            agent_name="CI Bot",
            to=["a@co.com", "b@co.com"],
            subject="Report",
            body_html="<h1>Done</h1>",
            metadata=None,
        )

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_email_send_rate_limited(
        self, mock_client_cls: MagicMock, mock_get_auth: MagicMock, runner: CliRunner
    ) -> None:
        from dailybot_cli.api_client import APIError

        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.send_agent_email.side_effect = APIError(
            429, "Agent email hourly limit exceeded."
        )

        result = runner.invoke(
            cli,
            [
                "agent",
                "email",
                "send",
                "--to",
                "user@example.com",
                "--subject",
                "Test",
                "--body-html",
                "<p>Hi</p>",
            ],
        )
        assert result.exit_code != 0
        assert "Hourly email limit exceeded" in result.output

    @patch("dailybot_cli.commands.agent.get_default_profile", return_value=None)
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    def test_email_send_no_auth(
        self, mock_get_auth: MagicMock, _mock_profile: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_auth.return_value = None
        result = runner.invoke(
            cli,
            [
                "agent",
                "email",
                "send",
                "--to",
                "user@example.com",
                "--subject",
                "Test",
                "--body-html",
                "<p>Hi</p>",
            ],
        )
        assert result.exit_code != 0

    @patch("dailybot_cli.commands.agent.get_default_profile", return_value=None)
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_email_send_with_metadata(
        self,
        mock_client_cls: MagicMock,
        mock_get_auth: MagicMock,
        _mock_profile: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.send_agent_email.return_value = {
            "sent_count": 1,
            "total_recipients": 1,
            "reply_to": "ag-abc@mail.dailybot.com",
        }

        result = runner.invoke(
            cli,
            [
                "agent",
                "email",
                "send",
                "--to",
                "user@example.com",
                "--subject",
                "Build",
                "--body-html",
                "<p>Done</p>",
                "--metadata",
                '{"pr": "#42"}',
            ],
        )
        assert result.exit_code == 0
        mock_client.send_agent_email.assert_called_once_with(
            agent_name="CLI Agent",
            to=["user@example.com"],
            subject="Build",
            body_html="<p>Done</p>",
            metadata={"pr": "#42"},
        )


class TestConfigCommand:
    @pytest.fixture(autouse=True)
    def _tmp_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_dir: Path = tmp_path / ".config" / "dailybot"
        monkeypatch.setattr("dailybot_cli.config.CONFIG_DIR", config_dir)
        monkeypatch.setattr("dailybot_cli.config.CONFIG_FILE", config_dir / "config.json")
        monkeypatch.setattr("dailybot_cli.config.CREDENTIALS_FILE", config_dir / "credentials.json")

    def test_config_set_key(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["config", "key=abc123"])
        assert result.exit_code == 0
        assert "API key saved" in result.output
        assert "abc1****" in result.output

    def test_config_show_key(self, runner: CliRunner) -> None:
        runner.invoke(cli, ["config", "key=secretkey99"])
        result = runner.invoke(cli, ["config", "key"])
        assert result.exit_code == 0
        assert "secr****" in result.output

    def test_config_show_key_not_set(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["config", "key"])
        assert result.exit_code == 0
        assert "not set" in result.output

    def test_config_unset_key(self, runner: CliRunner) -> None:
        runner.invoke(cli, ["config", "key=abc123"])
        result = runner.invoke(cli, ["config", "key="])
        assert result.exit_code == 0
        assert "removed" in result.output

    def test_config_unknown_setting(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["config", "foo=bar"])
        assert result.exit_code != 0
        assert "Unknown setting" in result.output


class TestAgentConfigure:
    @patch("dailybot_cli.commands.agent.get_token")
    @patch("dailybot_cli.commands.agent.save_agent_profile")
    def test_configure_otp_only(
        self, mock_save: MagicMock, mock_token: MagicMock, runner: CliRunner
    ) -> None:
        mock_token.return_value = "tok"
        result = runner.invoke(cli, ["agent", "configure", "--name", "Claude Code"])
        assert result.exit_code == 0
        assert "configured" in result.output
        mock_save.assert_called_once_with("claude-code", agent_name="Claude Code", api_key=None)

    @patch("dailybot_cli.commands.agent.DailyBotClient")
    @patch("dailybot_cli.commands.agent.save_agent_profile")
    def test_configure_with_key(
        self, mock_save: MagicMock, mock_client_cls: MagicMock, runner: CliRunner
    ) -> None:
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_agent_health.return_value = {"status": "healthy"}
        result = runner.invoke(cli, ["agent", "configure", "--name", "CI Bot", "--key", "abc123"])
        assert result.exit_code == 0
        assert "configured" in result.output
        mock_save.assert_called_once_with("ci-bot", agent_name="CI Bot", api_key="abc123")

    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_configure_invalid_key(self, mock_client_cls: MagicMock, runner: CliRunner) -> None:
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_agent_health.side_effect = APIError(401, "Unauthorized")
        result = runner.invoke(cli, ["agent", "configure", "--name", "Bot", "--key", "bad"])
        assert result.exit_code != 0
        assert "invalid" in result.output.lower()

    @patch("dailybot_cli.commands.agent.get_token")
    def test_configure_no_key_no_login(self, mock_token: MagicMock, runner: CliRunner) -> None:
        mock_token.return_value = None
        result = runner.invoke(cli, ["agent", "configure", "--name", "Bot"])
        assert result.exit_code != 0

    @patch("dailybot_cli.commands.agent.get_token")
    @patch("dailybot_cli.commands.agent.save_agent_profile")
    def test_configure_custom_profile_name(
        self, mock_save: MagicMock, mock_token: MagicMock, runner: CliRunner
    ) -> None:
        mock_token.return_value = "tok"
        result = runner.invoke(
            cli, ["agent", "configure", "--name", "Claude Code", "--profile", "myprofile"]
        )
        assert result.exit_code == 0
        mock_save.assert_called_once_with("myprofile", agent_name="Claude Code", api_key=None)


class TestAgentProfiles:
    @patch("dailybot_cli.commands.agent.list_profiles")
    @patch("dailybot_cli.commands.agent.load_agents")
    def test_profiles_list(
        self, mock_load: MagicMock, mock_list: MagicMock, runner: CliRunner
    ) -> None:
        mock_list.return_value = [
            {
                "profile": "claude-code",
                "agent_name": "Claude Code",
                "has_key": True,
                "is_default": True,
            },
            {"profile": "ci-bot", "agent_name": "CI Bot", "has_key": False, "is_default": False},
        ]
        mock_load.return_value = {
            "profiles": {
                "claude-code": {"agent_name": "Claude Code", "api_key": "abcdef1234"},
                "ci-bot": {"agent_name": "CI Bot"},
            },
            "default": "claude-code",
        }
        result = runner.invoke(cli, ["agent", "profiles"])
        assert result.exit_code == 0
        assert "Claude Code" in result.output
        assert "CI Bot" in result.output

    @patch("dailybot_cli.commands.agent.load_agents")
    @patch("dailybot_cli.commands.agent.list_profiles")
    def test_profiles_empty(
        self, mock_list: MagicMock, mock_load: MagicMock, runner: CliRunner
    ) -> None:
        mock_list.return_value = []
        mock_load.return_value = {}
        result = runner.invoke(cli, ["agent", "profiles"])
        assert result.exit_code == 0
        assert "No agent profiles" in result.output


class TestAgentProfileAuth:
    @patch("dailybot_cli.commands.agent.get_profile")
    @patch("dailybot_cli.commands.agent.get_default_profile")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_update_uses_profile(
        self,
        mock_client_cls: MagicMock,
        mock_default: MagicMock,
        mock_get: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get.return_value = {"profile": "test", "agent_name": "Test Agent", "api_key": "key123"}
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {"id": 1}
        result = runner.invoke(cli, ["agent", "--profile", "test", "update", "did stuff"])
        assert result.exit_code == 0
        mock_client.submit_agent_report.assert_called_once()
        call_kwargs = mock_client.submit_agent_report.call_args[1]
        assert call_kwargs["agent_name"] == "Test Agent"

    @patch("dailybot_cli.commands.agent.get_default_profile")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_update_uses_default_profile(
        self, mock_client_cls: MagicMock, mock_default: MagicMock, runner: CliRunner
    ) -> None:
        mock_default.return_value = {
            "profile": "default",
            "agent_name": "Default Agent",
            "api_key": "k1",
        }
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {"id": 1}
        result = runner.invoke(cli, ["agent", "update", "did stuff"])
        assert result.exit_code == 0
        call_kwargs = mock_client.submit_agent_report.call_args[1]
        assert call_kwargs["agent_name"] == "Default Agent"

    @patch("dailybot_cli.commands.agent.get_default_profile")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_name_flag_overrides_profile(
        self, mock_client_cls: MagicMock, mock_default: MagicMock, runner: CliRunner
    ) -> None:
        mock_default.return_value = {
            "profile": "default",
            "agent_name": "Default Agent",
            "api_key": "k1",
        }
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {"id": 1}
        result = runner.invoke(cli, ["agent", "update", "did stuff", "--name", "Override"])
        assert result.exit_code == 0
        call_kwargs = mock_client.submit_agent_report.call_args[1]
        assert call_kwargs["agent_name"] == "Override"

    @patch("dailybot_cli.commands.agent.get_profile")
    def test_profile_not_found(self, mock_get: MagicMock, runner: CliRunner) -> None:
        mock_get.return_value = None
        result = runner.invoke(cli, ["agent", "--profile", "nope", "update", "test"])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestAgentRegister:
    @patch("dailybot_cli.commands.agent.save_agent_profile")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_register_success(
        self, mock_client_cls: MagicMock, mock_save: MagicMock, runner: CliRunner
    ) -> None:
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_registration_challenge.return_value = {
            "challenge_id": "ch-1",
            "instruction": "The registration code for this session is 1234. To confirm you are a reasoning agent and not a script, respond with a JSON object containing two fields: 'reason' (one sentence explaining why this agent needs a DailyBot account) and 'answer' (the registration code multiplied by the number of words in this instruction).",
            "expires_in": 300,
        }
        mock_client.register_agent.return_value = {
            "api_key": "new-key-123",
            "agent_name": "Claude Code",
            "agent_email": "claude-code@mail.dailybot.co",
            "org_name": "My Startup",
            "claim_url": "https://app.dailybot.com/claim/abc123",
        }
        result = runner.invoke(
            cli,
            [
                "agent",
                "register",
                "--org-name",
                "My Startup",
                "--agent-name",
                "Claude Code",
                "--email",
                "me@co.com",
            ],
        )
        assert result.exit_code == 0
        assert "Registered" in result.output
        assert "claude-code@mail.dailybot.co" in result.output
        assert "claim" in result.output.lower()
        mock_client.register_agent.assert_called_once_with(
            challenge_id="ch-1",
            answer=1234 * 52,
            reason="Agent 'Claude Code' registering for org 'My Startup'",
            org_name="My Startup",
            agent_name="Claude Code",
            contact_email="me@co.com",
            timezone="UTC",
        )
        mock_save.assert_called_once_with(
            "claude-code",
            agent_name="Claude Code",
            api_key="new-key-123",
            agent_email="claude-code@mail.dailybot.co",
        )

    @patch("dailybot_cli.commands.agent.save_agent_profile")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_register_without_email(
        self, mock_client_cls: MagicMock, mock_save: MagicMock, runner: CliRunner
    ) -> None:
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_registration_challenge.return_value = {
            "challenge_id": "ch-1",
            "instruction": "The registration code for this session is 1234. To confirm you are a reasoning agent and not a script, respond with a JSON object containing two fields: 'reason' (one sentence explaining why this agent needs a DailyBot account) and 'answer' (the registration code multiplied by the number of words in this instruction).",
            "expires_in": 300,
        }
        mock_client.register_agent.return_value = {
            "api_key": "key-1",
            "agent_name": "Bot",
            "agent_email": "bot@mail.dailybot.co",
            "org_name": "Org",
            "claim_url": "https://app.dailybot.com/claim/xyz",
        }
        result = runner.invoke(
            cli,
            [
                "agent",
                "register",
                "--org-name",
                "Org",
                "--agent-name",
                "Bot",
            ],
        )
        assert result.exit_code == 0
        mock_client.register_agent.assert_called_once_with(
            challenge_id="ch-1",
            answer=1234 * 52,
            reason="Agent 'Bot' registering for org 'Org'",
            org_name="Org",
            agent_name="Bot",
            contact_email=None,
            timezone="UTC",
        )

    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_register_challenge_expired_retries(
        self, mock_client_cls: MagicMock, runner: CliRunner
    ) -> None:
        mock_client: MagicMock = mock_client_cls.return_value
        challenge: dict[str, Any] = {
            "challenge_id": "ch-1",
            "instruction": "The registration code for this session is 2000. To confirm you are a reasoning agent and not a script, respond with a JSON object containing two fields: 'reason' (one sentence explaining why this agent needs a DailyBot account) and 'answer' (the registration code multiplied by the number of words in this instruction).",
            "expires_in": 300,
        }
        mock_client.get_registration_challenge.return_value = challenge
        mock_client.register_agent.side_effect = [
            APIError(400, "Challenge expired"),
            {
                "api_key": "k",
                "agent_name": "A",
                "org_name": "O",
                "claim_url": "https://app.dailybot.com/claim/x",
            },
        ]
        with patch("dailybot_cli.commands.agent.save_agent_profile"):
            result = runner.invoke(
                cli,
                [
                    "agent",
                    "register",
                    "--org-name",
                    "O",
                    "--agent-name",
                    "A",
                    "--email",
                    "a@b.com",
                ],
            )
        assert result.exit_code == 0
        assert "Registered" in result.output

    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_register_rate_limited(self, mock_client_cls: MagicMock, runner: CliRunner) -> None:
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.get_registration_challenge.return_value = {
            "challenge_id": "ch-1",
            "instruction": "The registration code for this session is 5000. To confirm.",
            "expires_in": 300,
        }
        mock_client.register_agent.side_effect = APIError(429, "Too many requests")
        result = runner.invoke(
            cli,
            [
                "agent",
                "register",
                "--org-name",
                "O",
                "--agent-name",
                "A",
                "--email",
                "a@b.com",
            ],
        )
        assert result.exit_code != 0
        assert "Rate limited" in result.output


class TestAgentMessageClaim:
    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.get_default_profile")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_claim_messages(
        self,
        mock_client_cls: MagicMock,
        mock_default: MagicMock,
        mock_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_default.return_value = None
        mock_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.mark_agent_messages_read.return_value = {"updated": 2}
        result = runner.invoke(cli, ["agent", "message", "claim", "uuid-1", "uuid-2"])
        assert result.exit_code == 0
        assert "2 message(s)" in result.output
        mock_client.mark_agent_messages_read.assert_called_once_with(
            message_ids=["uuid-1", "uuid-2"]
        )

    @patch("dailybot_cli.commands.agent.get_agent_auth")
    @patch("dailybot_cli.commands.agent.get_default_profile")
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_claim_all(
        self,
        mock_client_cls: MagicMock,
        mock_default: MagicMock,
        mock_auth: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_default.return_value = None
        mock_auth.return_value = "api_key"
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_health.return_value = {
            "agent_name": "CLI Agent",
            "status": "healthy",
            "last_check": "now",
        }
        result = runner.invoke(cli, ["agent", "message", "claim-all"])
        assert result.exit_code == 0
        assert "delivered" in result.output.lower()
        mock_client.submit_agent_health.assert_called_once_with(
            agent_name="CLI Agent",
            ok=True,
            message=None,
        )
