"""Tests for the onboarding UX: `dailybot agent init`, `configure --repo`,
the first-run nudge, and the underlying `write_repo_profile` helper."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.commands.agent import _reset_init_nudge
from dailybot_cli.config import (
    RepoProfileError,
    find_repo_root,
    write_repo_profile,
)
from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _reset_nudge_between_tests() -> None:
    _reset_init_nudge()


@pytest.fixture
def chdir_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def isolated_global_agents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fully isolate global state: AGENTS_FILE, CREDENTIALS_FILE, CONFIG_FILE, env vars.

    Without all four, the wizard / nudge tests would read the real ~/.config/dailybot/
    on the developer's machine, making behavior dependent on whether they happen to
    be logged in.
    """
    fake_agents: Path = tmp_path / "fake-agents.json"
    fake_creds: Path = tmp_path / "fake-credentials.json"
    fake_config: Path = tmp_path / "fake-config.json"
    monkeypatch.setattr("dailybot_cli.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("dailybot_cli.config.AGENTS_FILE", fake_agents)
    monkeypatch.setattr("dailybot_cli.config.CREDENTIALS_FILE", fake_creds)
    monkeypatch.setattr("dailybot_cli.config.CONFIG_FILE", fake_config)
    monkeypatch.delenv("DAILYBOT_API_KEY", raising=False)
    monkeypatch.delenv("DAILYBOT_CLI_TOKEN", raising=False)
    return fake_agents


# --- write_repo_profile -----------------------------------------------------


class TestWriteRepoProfile:
    def test_writes_fresh_file_with_json_payload(self, chdir_tmp: Path) -> None:
        path: Path = write_repo_profile({"name": "Bot"})
        assert path == chdir_tmp / ".dailybot" / "profile.json"
        assert json.loads(path.read_text()) == {"name": "Bot"}

    def test_creates_directory_when_missing(self, chdir_tmp: Path) -> None:
        assert not (chdir_tmp / ".dailybot").exists()
        write_repo_profile({"name": "Bot"})
        assert (chdir_tmp / ".dailybot").is_dir()

    def test_merges_with_existing_file(self, chdir_tmp: Path) -> None:
        # Pre-existing file with name + metadata
        path: Path = write_repo_profile(
            {"name": "Old Bot", "default_metadata": {"team": "billing"}}
        )
        # Overwrite name + add a new metadata key
        write_repo_profile({"name": "New Bot", "default_metadata": {"service": "core"}})
        result: dict[str, Any] = json.loads(path.read_text())
        assert result["name"] == "New Bot"
        # Metadata is shallow-merged (both keys preserved).
        assert result["default_metadata"] == {"team": "billing", "service": "core"}

    def test_metadata_key_overwrite_wins(self, chdir_tmp: Path) -> None:
        write_repo_profile({"default_metadata": {"team": "old"}})
        write_repo_profile({"default_metadata": {"team": "new"}})
        result: dict[str, Any] = json.loads((chdir_tmp / ".dailybot" / "profile.json").read_text())
        assert result["default_metadata"] == {"team": "new"}

    def test_refuses_key_field(self, chdir_tmp: Path) -> None:
        with pytest.raises(RepoProfileError) as exc_info:
            write_repo_profile({"name": "Bot", "key": "secret"})
        assert "credentials" in str(exc_info.value).lower()
        assert not (chdir_tmp / ".dailybot" / "profile.json").exists()

    def test_rejects_unknown_keys(self, chdir_tmp: Path) -> None:
        with pytest.raises(ValueError) as exc_info:
            write_repo_profile({"name": "Bot", "future_field": "nope"})
        assert "future_field" in str(exc_info.value)

    def test_anchors_at_git_root_not_cwd(
        self, chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (chdir_tmp / ".git").mkdir()
        nested: Path = chdir_tmp / "src" / "deep"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        path: Path = write_repo_profile({"name": "Bot"})
        # Even though cwd is `nested`, the file goes to the git root.
        assert path == chdir_tmp / ".dailybot" / "profile.json"

    def test_falls_back_to_cwd_outside_git(self, chdir_tmp: Path) -> None:
        # No .git directory anywhere — write to cwd.
        assert not (chdir_tmp / ".git").exists()
        path: Path = write_repo_profile({"name": "Bot"})
        assert path.parent.parent == chdir_tmp

    def test_corrupt_existing_file_starts_fresh(self, chdir_tmp: Path) -> None:
        profile_dir: Path = chdir_tmp / ".dailybot"
        profile_dir.mkdir()
        (profile_dir / "profile.json").write_text("{not valid json")
        path: Path = write_repo_profile({"name": "Bot"})
        assert json.loads(path.read_text()) == {"name": "Bot"}


class TestFindRepoRoot:
    def test_returns_git_ancestor(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        nested: Path = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        assert find_repo_root(nested) == tmp_path.resolve()

    def test_falls_back_to_start_dir(self, tmp_path: Path) -> None:
        # No .git anywhere → returns the starting directory itself.
        assert find_repo_root(tmp_path) == tmp_path.resolve()


# --- agent configure --repo --------------------------------------------------


class TestConfigureRepoFlag:
    def test_writes_repo_profile_with_name(self, runner: CliRunner, chdir_tmp: Path) -> None:
        result = runner.invoke(cli, ["agent", "configure", "--repo", "--name", "Core Hub Bot"])
        assert result.exit_code == 0
        path: Path = chdir_tmp / ".dailybot" / "profile.json"
        assert json.loads(path.read_text()) == {"name": "Core Hub Bot"}

    def test_writes_metadata_pairs(self, runner: CliRunner, chdir_tmp: Path) -> None:
        result = runner.invoke(
            cli,
            [
                "agent",
                "configure",
                "--repo",
                "--name",
                "Bot",
                "--metadata",
                "team=platform",
                "--metadata",
                "service=core-hub",
            ],
        )
        assert result.exit_code == 0
        data: dict[str, Any] = json.loads((chdir_tmp / ".dailybot" / "profile.json").read_text())
        assert data == {
            "name": "Bot",
            "default_metadata": {"team": "platform", "service": "core-hub"},
        }

    def test_writes_profile_slug(self, runner: CliRunner, chdir_tmp: Path) -> None:
        result = runner.invoke(cli, ["agent", "configure", "--repo", "--profile", "core-hub-bot"])
        assert result.exit_code == 0
        data: dict[str, Any] = json.loads((chdir_tmp / ".dailybot" / "profile.json").read_text())
        assert data == {"profile": "core-hub-bot"}

    def test_repo_with_key_is_rejected(self, runner: CliRunner, chdir_tmp: Path) -> None:
        result = runner.invoke(
            cli,
            ["agent", "configure", "--repo", "--name", "Bot", "--key", "secret"],
        )
        assert result.exit_code == 1
        assert "--key cannot be combined with --repo" in result.output
        assert not (chdir_tmp / ".dailybot" / "profile.json").exists()

    def test_repo_requires_at_least_one_field(self, runner: CliRunner, chdir_tmp: Path) -> None:
        result = runner.invoke(cli, ["agent", "configure", "--repo"])
        assert result.exit_code == 1
        assert "Nothing to write" in result.output

    def test_metadata_without_repo_errors(
        self, runner: CliRunner, isolated_global_agents: Path
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "agent",
                "configure",
                "--name",
                "Bot",
                "--metadata",
                "team=platform",
            ],
        )
        assert result.exit_code == 1
        assert "--metadata is only valid with --repo" in result.output

    def test_invalid_metadata_format(self, runner: CliRunner, chdir_tmp: Path) -> None:
        result = runner.invoke(
            cli,
            ["agent", "configure", "--repo", "--name", "Bot", "--metadata", "no-equals"],
        )
        assert result.exit_code == 1
        assert "key=value" in result.output

    def test_repeated_run_merges_metadata(self, runner: CliRunner, chdir_tmp: Path) -> None:
        runner.invoke(
            cli,
            [
                "agent",
                "configure",
                "--repo",
                "--name",
                "Bot",
                "--metadata",
                "team=platform",
            ],
        )
        result = runner.invoke(
            cli,
            ["agent", "configure", "--repo", "--metadata", "service=core"],
        )
        assert result.exit_code == 0
        data: dict[str, Any] = json.loads((chdir_tmp / ".dailybot" / "profile.json").read_text())
        # Name preserved, both metadata keys present.
        assert data == {
            "name": "Bot",
            "default_metadata": {"team": "platform", "service": "core"},
        }

    def test_global_configure_still_works(
        self, runner: CliRunner, isolated_global_agents: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sanity-check: making --name optional in the click signature didn't
        break the original global-configure flow."""
        monkeypatch.setenv("DAILYBOT_CLI_TOKEN", "fake-token")
        result = runner.invoke(cli, ["agent", "configure", "--name", "Global Bot"])
        assert result.exit_code == 0
        assert "Agent profile 'global-bot' configured" in result.output
        assert isolated_global_agents.exists()

    def test_global_configure_without_name_errors(
        self, runner: CliRunner, isolated_global_agents: Path
    ) -> None:
        result = runner.invoke(cli, ["agent", "configure"])
        assert result.exit_code == 1
        assert "--name is required" in result.output


# --- agent init wizard -------------------------------------------------------


def _mock_questionary(select_returns: list[str], text_returns: list[str | None]) -> MagicMock:
    """Build a questionary mock whose `.select(...).ask()` and `.text(...).ask()`
    return the provided sequences, in order."""
    mock = MagicMock()
    mock.select.side_effect = lambda *_args, **_kwargs: MagicMock(
        ask=MagicMock(side_effect=select_returns.copy())
    )
    # Each call to `mock.text(...)` returns a fresh inner mock whose .ask()
    # consumes the next text reply.
    text_iter = iter(text_returns)

    def _text_factory(*_args, **_kwargs):
        reply = next(text_iter)
        return MagicMock(ask=MagicMock(return_value=reply))

    mock.text.side_effect = _text_factory
    return mock


class TestAgentInit:
    def test_personal_only_with_login(
        self,
        runner: CliRunner,
        chdir_tmp: Path,
        isolated_global_agents: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DAILYBOT_CLI_TOKEN", "fake-token")
        # Select "Personal", then within the personal step pick "login session".
        questionary_mock = MagicMock()
        questionary_mock.select.side_effect = [
            MagicMock(
                ask=MagicMock(
                    return_value="Personal profile (this machine only — saves to ~/.config/dailybot/agents.json)"
                )
            ),
            MagicMock(ask=MagicMock(return_value="Use my login session (recommended for humans)")),
        ]
        questionary_mock.text.return_value = MagicMock(ask=MagicMock(return_value="Sergio Florez"))

        with patch.dict("sys.modules", {"questionary": questionary_mock}):
            result = runner.invoke(cli, ["agent", "init"])

        assert result.exit_code == 0
        assert "Saved global profile 'sergio-florez'" in result.output
        # Agents file was created.
        assert isolated_global_agents.exists()

    def test_personal_with_pasted_api_key(
        self,
        runner: CliRunner,
        chdir_tmp: Path,
        isolated_global_agents: Path,
    ) -> None:
        questionary_mock = MagicMock()
        questionary_mock.select.side_effect = [
            MagicMock(
                ask=MagicMock(
                    return_value="Personal profile (this machine only — saves to ~/.config/dailybot/agents.json)"
                )
            ),
            MagicMock(
                ask=MagicMock(
                    return_value="Paste an API key (recommended for CI / dedicated agents)"
                )
            ),
        ]
        questionary_mock.text.return_value = MagicMock(ask=MagicMock(return_value="CI Bot"))
        questionary_mock.password.return_value = MagicMock(
            ask=MagicMock(return_value="dbk_xxxxxxxx")
        )

        # Mock the API key validation so we don't hit the network.
        with (
            patch.dict("sys.modules", {"questionary": questionary_mock}),
            patch("dailybot_cli.commands.agent.DailyBotClient") as mock_client_cls,
        ):
            mock_client_cls.return_value.get_agent_health.return_value = {"status": "healthy"}
            result = runner.invoke(cli, ["agent", "init"])

        assert result.exit_code == 0
        assert "Saved global profile 'ci-bot'" in result.output

    def test_repo_only(
        self, runner: CliRunner, chdir_tmp: Path, isolated_global_agents: Path
    ) -> None:
        # No login token, no api key — should still write the repo file but
        # warn the user that they need credentials to actually send.
        questionary_mock = MagicMock()
        questionary_mock.select.side_effect = [
            MagicMock(
                ask=MagicMock(
                    return_value="Repo profile (writes .dailybot/profile.json — committed to git, shared by every contributor)"
                )
            ),
        ]
        # Two text prompts inside _init_repo: name, then metadata.
        text_iter = iter(["Core Hub Bot", "team=platform"])
        questionary_mock.text.side_effect = lambda *_a, **_k: MagicMock(
            ask=MagicMock(return_value=next(text_iter))
        )

        with patch.dict("sys.modules", {"questionary": questionary_mock}):
            result = runner.invoke(cli, ["agent", "init"])

        assert result.exit_code == 0
        assert "Wrote" in result.output
        assert (chdir_tmp / ".dailybot" / "profile.json").exists()
        # The "no credentials" warning should fire (we have neither token nor key).
        assert "you still need to authenticate" in result.output.lower()

    def test_aborts_on_ctrl_c(self, runner: CliRunner, isolated_global_agents: Path) -> None:
        questionary_mock = MagicMock()
        questionary_mock.select.return_value = MagicMock(ask=MagicMock(return_value=None))

        with patch.dict("sys.modules", {"questionary": questionary_mock}):
            result = runner.invoke(cli, ["agent", "init"])

        assert result.exit_code == 0
        assert "Aborted" in result.output


# --- first-run nudge --------------------------------------------------------


class TestInitNudge:
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_nudge_shown_when_resolved_to_fallback(
        self,
        mock_client_cls: MagicMock,
        runner: CliRunner,
        chdir_tmp: Path,
        isolated_global_agents: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DAILYBOT_API_KEY", "fake-key")
        mock_client_cls.return_value.submit_agent_report.return_value = {
            "id": 1,
            "uuid": "abc",
        }
        result = runner.invoke(cli, ["agent", "update", "Did the thing"])
        assert result.exit_code == 0
        assert "dailybot agent init" in result.output

    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_nudge_skipped_when_real_name_resolved(
        self,
        mock_client_cls: MagicMock,
        runner: CliRunner,
        chdir_tmp: Path,
        isolated_global_agents: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DAILYBOT_API_KEY", "fake-key")
        mock_client_cls.return_value.submit_agent_report.return_value = {
            "id": 1,
            "uuid": "abc",
        }
        result = runner.invoke(cli, ["agent", "update", "Did the thing", "--name", "Sergio"])
        assert result.exit_code == 0
        assert "dailybot agent init" not in result.output

    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_nudge_only_once_per_process(
        self,
        mock_client_cls: MagicMock,
        runner: CliRunner,
        chdir_tmp: Path,
        isolated_global_agents: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DAILYBOT_API_KEY", "fake-key")
        mock_client_cls.return_value.submit_agent_report.return_value = {
            "id": 1,
            "uuid": "abc",
        }
        # First invocation — nudge fires.
        first = runner.invoke(cli, ["agent", "update", "First"])
        assert "dailybot agent init" in first.output
        # Second invocation in the same process — silent.
        second = runner.invoke(cli, ["agent", "update", "Second"])
        assert "dailybot agent init" not in second.output
