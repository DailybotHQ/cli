"""Tests for repo-level agent profile (`.dailybot/profile.json`)."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.commands.agent import _merge_repo_metadata, _resolve_agent_context
from dailybot_cli.config import (
    RepoProfileError,
    find_repo_profile_path,
    load_repo_profile,
    reset_repo_profile_warnings,
    resolve_active_profile,
)
from dailybot_cli.main import cli


@pytest.fixture(autouse=True)
def _isolate_global_agents(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Make sure no real ~/.config/dailybot/agents.json bleeds into the tests."""
    fake_agents: Path = tmp_path / "fake_global_agents.json"
    monkeypatch.setattr("dailybot_cli.config.AGENTS_FILE", fake_agents)
    monkeypatch.delenv("DAILYBOT_API_KEY", raising=False)
    monkeypatch.delenv("DAILYBOT_CLI_TOKEN", raising=False)
    reset_repo_profile_warnings()


@pytest.fixture
def chdir_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_repo_profile(repo_root: Path, payload: dict[str, Any]) -> Path:
    profile_dir: Path = repo_root / ".dailybot"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_path: Path = profile_dir / "profile.json"
    profile_path.write_text(json.dumps(payload))
    return profile_path


# --- find_repo_profile_path / load_repo_profile -----------------------------


class TestFindRepoProfile:
    def test_walk_up_from_nested_cwd(self, chdir_tmp: Path) -> None:
        _write_repo_profile(chdir_tmp, {"name": "Core Bot"})
        nested: Path = chdir_tmp / "src" / "deep" / "feature"
        nested.mkdir(parents=True)
        found: Path | None = find_repo_profile_path(nested)
        assert found is not None
        assert found.parent.parent == chdir_tmp

    def test_closest_ancestor_wins(self, chdir_tmp: Path) -> None:
        _write_repo_profile(chdir_tmp, {"name": "Outer"})
        inner: Path = chdir_tmp / "inner"
        inner.mkdir()
        _write_repo_profile(inner, {"name": "Inner"})
        nested: Path = inner / "src"
        nested.mkdir()

        found: Path | None = find_repo_profile_path(nested)
        assert found is not None
        assert found.parent.parent == inner

    def test_returns_none_when_missing(self, chdir_tmp: Path) -> None:
        assert find_repo_profile_path(chdir_tmp) is None

    def test_dailybot_as_regular_file_is_ignored(self, chdir_tmp: Path) -> None:
        (chdir_tmp / ".dailybot").write_text("not a directory")
        assert find_repo_profile_path(chdir_tmp) is None

    def test_dailybot_dir_without_profile_json(self, chdir_tmp: Path) -> None:
        (chdir_tmp / ".dailybot").mkdir()
        # Create disabled marker but no profile.json.
        (chdir_tmp / ".dailybot" / "disabled").write_text("")
        assert find_repo_profile_path(chdir_tmp) is None


class TestLoadRepoProfile:
    def test_loads_valid_payload(self, chdir_tmp: Path) -> None:
        path: Path = _write_repo_profile(
            chdir_tmp,
            {"name": "Core Hub Bot", "default_metadata": {"team": "platform"}},
        )
        result: dict[str, Any] | None = load_repo_profile(chdir_tmp)
        assert result is not None
        assert result["name"] == "Core Hub Bot"
        assert result["default_metadata"] == {"team": "platform"}
        assert result["_path"] == str(path)

    def test_key_field_raises_repoprofileerror(self, chdir_tmp: Path) -> None:
        _write_repo_profile(chdir_tmp, {"name": "Bot", "key": "secret-key"})
        with pytest.raises(RepoProfileError) as exc_info:
            load_repo_profile(chdir_tmp)
        assert "key" in str(exc_info.value).lower()
        # Message must reference credentials/security so the user understands.
        assert "credentials" in str(exc_info.value).lower()

    def test_malformed_json_warns_and_returns_none(self, chdir_tmp: Path) -> None:
        profile_dir: Path = chdir_tmp / ".dailybot"
        profile_dir.mkdir()
        (profile_dir / "profile.json").write_text("{not valid json")
        # Should not crash; warning is emitted via rich, but the contract here
        # is that the file is silently treated as absent.
        assert load_repo_profile(chdir_tmp) is None

    def test_non_object_json_returns_none(self, chdir_tmp: Path) -> None:
        profile_dir: Path = chdir_tmp / ".dailybot"
        profile_dir.mkdir()
        (profile_dir / "profile.json").write_text('["not", "an", "object"]')
        assert load_repo_profile(chdir_tmp) is None

    def test_unknown_keys_are_dropped(self, chdir_tmp: Path) -> None:
        _write_repo_profile(chdir_tmp, {"name": "Bot", "future_field": "ignored", "another": 42})
        result: dict[str, Any] | None = load_repo_profile(chdir_tmp)
        assert result is not None
        assert "future_field" not in result
        assert "another" not in result
        assert result["name"] == "Bot"

    def test_no_repo_dir_returns_none(self, chdir_tmp: Path) -> None:
        assert load_repo_profile(chdir_tmp) is None


# --- resolve_active_profile -------------------------------------------------


class TestResolveActiveProfile:
    def test_no_repo_no_global_returns_default_name(self, chdir_tmp: Path) -> None:
        resolved: dict[str, Any] = resolve_active_profile(None, None, cwd=chdir_tmp)
        assert resolved["agent_name"] == "CLI Agent"
        assert resolved["api_key"] is None
        assert resolved["default_metadata"] == {}
        assert resolved["resolved_from"]["agent_name"] == "default"

    def test_repo_name_overrides_default(self, chdir_tmp: Path) -> None:
        _write_repo_profile(chdir_tmp, {"name": "Core Hub Bot"})
        resolved: dict[str, Any] = resolve_active_profile(None, None, cwd=chdir_tmp)
        assert resolved["agent_name"] == "Core Hub Bot"
        assert resolved["resolved_from"]["agent_name"] == "repo"

    def test_cli_name_flag_overrides_repo(self, chdir_tmp: Path) -> None:
        _write_repo_profile(chdir_tmp, {"name": "Core Hub Bot"})
        resolved: dict[str, Any] = resolve_active_profile(
            None, name_flag="Override Bot", cwd=chdir_tmp
        )
        assert resolved["agent_name"] == "Override Bot"
        assert resolved["resolved_from"]["agent_name"] == "flag"

    def test_repo_default_metadata_returned(self, chdir_tmp: Path) -> None:
        _write_repo_profile(
            chdir_tmp,
            {"name": "Bot", "default_metadata": {"team": "platform", "tier": "1"}},
        )
        resolved: dict[str, Any] = resolve_active_profile(None, None, cwd=chdir_tmp)
        assert resolved["default_metadata"] == {"team": "platform", "tier": "1"}

    def test_repo_profile_slug_resolves_global(self, chdir_tmp: Path) -> None:
        _write_repo_profile(chdir_tmp, {"name": "Repo Bot", "profile": "core-hub"})
        with patch(
            "dailybot_cli.config.get_profile",
            return_value={
                "profile": "core-hub",
                "agent_name": "Global Bot",
                "api_key": "abc-key",
            },
        ):
            resolved: dict[str, Any] = resolve_active_profile(None, None, cwd=chdir_tmp)
        # Repo `name` still overrides the global profile's display name.
        assert resolved["agent_name"] == "Repo Bot"
        assert resolved["api_key"] == "abc-key"
        assert resolved["profile_slug"] == "core-hub"

    def test_repo_slug_missing_falls_through(self, chdir_tmp: Path) -> None:
        _write_repo_profile(chdir_tmp, {"name": "Repo Bot", "profile": "ghost"})
        with patch("dailybot_cli.config.get_profile", return_value=None):
            resolved: dict[str, Any] = resolve_active_profile(None, None, cwd=chdir_tmp)
        assert resolved["agent_name"] == "Repo Bot"
        assert resolved["api_key"] is None
        assert resolved["profile_missing_from_repo"] is True
        assert resolved["profile_missing_from_flag"] is False

    def test_flag_slug_missing_signaled(self, chdir_tmp: Path) -> None:
        with patch("dailybot_cli.config.get_profile", return_value=None):
            resolved: dict[str, Any] = resolve_active_profile("explicit", None, cwd=chdir_tmp)
        assert resolved["profile_missing_from_flag"] is True


# --- _merge_repo_metadata ---------------------------------------------------


class TestMergeRepoMetadata:
    def test_inline_wins_per_key(self) -> None:
        merged: dict[str, Any] | None = _merge_repo_metadata(
            inline={"team": "y", "tier": "1"},
            default_metadata={"team": "x"},
        )
        assert merged == {"team": "y", "tier": "1"}

    def test_missing_keys_fall_through(self) -> None:
        merged: dict[str, Any] | None = _merge_repo_metadata(
            inline={"tier": "1"},
            default_metadata={"team": "platform"},
        )
        assert merged == {"team": "platform", "tier": "1"}

    def test_empty_default_returns_inline(self) -> None:
        assert _merge_repo_metadata({"a": 1}, {}) == {"a": 1}

    def test_no_inline_no_default_returns_none(self) -> None:
        assert _merge_repo_metadata(None, {}) is None

    def test_no_inline_with_default_returns_default(self) -> None:
        assert _merge_repo_metadata(None, {"team": "x"}) == {"team": "x"}


# --- _resolve_agent_context (integration) -----------------------------------


class TestResolveAgentContext:
    def test_repo_name_used_when_no_flag(
        self, chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_repo_profile(chdir_tmp, {"name": "Core Hub Bot"})
        monkeypatch.setenv("DAILYBOT_API_KEY", "k")
        agent_name, _client, default_metadata = _resolve_agent_context(None, None)
        assert agent_name == "Core Hub Bot"
        assert default_metadata == {}

    def test_flag_overrides_repo_name(
        self, chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_repo_profile(chdir_tmp, {"name": "Core Hub Bot"})
        monkeypatch.setenv("DAILYBOT_API_KEY", "k")
        agent_name, _client, _meta = _resolve_agent_context(None, "Explicit Name")
        assert agent_name == "Explicit Name"

    def test_repo_default_metadata_passed_through(
        self, chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_repo_profile(
            chdir_tmp,
            {"name": "Bot", "default_metadata": {"team": "platform"}},
        )
        monkeypatch.setenv("DAILYBOT_API_KEY", "k")
        _name, _client, default_metadata = _resolve_agent_context(None, None)
        assert default_metadata == {"team": "platform"}

    def test_key_field_in_repo_aborts(
        self, chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_repo_profile(chdir_tmp, {"name": "Bot", "key": "leaked"})
        monkeypatch.setenv("DAILYBOT_API_KEY", "k")
        with pytest.raises(SystemExit) as exc_info:
            _resolve_agent_context(None, None)
        assert exc_info.value.code == 1


class TestResolveAgentContextEnvJson:
    """env.json credentials vs. keyed agents.json profiles.

    Regression guard for the asymmetry where `agent profiles --resolve`
    (via `resolve_active_profile`) showed the env.json key as the winner
    while the actual command client (via `_resolve_agent_context`) used
    the agents.json profile key. Display and runtime must always agree:
    env.json wins, except under an explicit `--profile` flag.
    """

    def _write_env_json(self, repo_root: Path) -> None:
        env_dir: Path = repo_root / ".dailybot"
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / "env.json").write_text(
            json.dumps(
                {
                    "active": "local",
                    "profiles": [{"name": "local", "api_key": "env-json-key"}],
                }
            )
        )

    def test_env_json_beats_keyed_default_profile(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import save_agent_profile

        save_agent_profile("bot", "Bot", api_key="agents-json-key")
        self._write_env_json(chdir_tmp)
        _name, client, _meta = _resolve_agent_context(None, None)
        assert client.api_key == "env-json-key"
        assert client._prefer_api_key is True  # wins on the wire too

    def test_explicit_profile_flag_beats_env_json(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import save_agent_profile

        save_agent_profile("bot", "Bot", api_key="agents-json-key")
        self._write_env_json(chdir_tmp)
        _name, client, _meta = _resolve_agent_context("bot", None)
        assert client.api_key == "agents-json-key"

    def test_repo_profile_slug_still_yields_to_env_json(self, chdir_tmp: Path) -> None:
        """A slug pinned by profile.json is repo config, not a CLI flag —
        env.json (the more specific repo-local auth file) still wins."""
        from dailybot_cli.config import save_agent_profile

        save_agent_profile("bot", "Bot", api_key="agents-json-key")
        _write_repo_profile(chdir_tmp, {"profile": "bot"})
        self._write_env_json(chdir_tmp)
        _name, client, _meta = _resolve_agent_context(None, None)
        assert client.api_key == "env-json-key"

    def test_keyless_profile_uses_ambient_api_key(
        self, chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A keyless profile with DAILYBOT_API_KEY available must use it
        instead of erroring out (the ambient chain includes API keys)."""
        from dailybot_cli.config import save_agent_profile

        save_agent_profile("bot", "Bot")
        monkeypatch.setenv("DAILYBOT_API_KEY", "ambient-key")
        _name, client, _meta = _resolve_agent_context(None, None)
        assert client.api_key == "ambient-key"

    def test_display_and_runtime_agree(self, chdir_tmp: Path) -> None:
        """`resolve_active_profile` (display) and `_resolve_agent_context`
        (runtime) must pick the same key."""
        from dailybot_cli.config import save_agent_profile

        save_agent_profile("bot", "Bot", api_key="agents-json-key")
        self._write_env_json(chdir_tmp)
        shown: dict[str, Any] = resolve_active_profile(None, None)
        _name, client, _meta = _resolve_agent_context(None, None)
        assert shown["api_key"] == client.api_key == "env-json-key"
        assert shown["resolved_from"]["api_key"] == "env.json"


# --- End-to-end CLI tests ---------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestAgentUpdateRepoIntegration:
    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_repo_name_used_in_report(
        self,
        mock_client_cls: MagicMock,
        chdir_tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
        runner: CliRunner,
    ) -> None:
        _write_repo_profile(chdir_tmp, {"name": "Core Hub Bot"})
        monkeypatch.setenv("DAILYBOT_API_KEY", "k")
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {"id": 7, "uuid": "x"}

        result = runner.invoke(cli, ["agent", "update", "Did the thing"])
        assert result.exit_code == 0
        kwargs: dict[str, Any] = mock_client.submit_agent_report.call_args.kwargs
        assert kwargs["agent_name"] == "Core Hub Bot"
        assert kwargs["metadata"] is None

    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_repo_default_metadata_merged_with_inline(
        self,
        mock_client_cls: MagicMock,
        chdir_tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
        runner: CliRunner,
    ) -> None:
        _write_repo_profile(
            chdir_tmp,
            {"name": "Bot", "default_metadata": {"team": "platform", "service": "core"}},
        )
        monkeypatch.setenv("DAILYBOT_API_KEY", "k")
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {"id": 1, "uuid": "u"}

        result = runner.invoke(
            cli,
            [
                "agent",
                "update",
                "Did it",
                "--metadata",
                '{"team": "billing", "pr": "#42"}',
            ],
        )
        assert result.exit_code == 0
        kwargs: dict[str, Any] = mock_client.submit_agent_report.call_args.kwargs
        # Inline `team` wins; missing repo `service` falls through; new `pr` added.
        assert kwargs["metadata"] == {
            "team": "billing",
            "service": "core",
            "pr": "#42",
        }

    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_flag_overrides_repo_name(
        self,
        mock_client_cls: MagicMock,
        chdir_tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
        runner: CliRunner,
    ) -> None:
        _write_repo_profile(chdir_tmp, {"name": "Repo Bot"})
        monkeypatch.setenv("DAILYBOT_API_KEY", "k")
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {"id": 1, "uuid": "u"}

        result = runner.invoke(cli, ["agent", "update", "Hello", "--name", "CLI Bot"])
        assert result.exit_code == 0
        kwargs: dict[str, Any] = mock_client.submit_agent_report.call_args.kwargs
        assert kwargs["agent_name"] == "CLI Bot"

    def test_key_field_aborts_with_security_message(
        self,
        chdir_tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
        runner: CliRunner,
    ) -> None:
        _write_repo_profile(chdir_tmp, {"name": "Bot", "key": "leak"})
        monkeypatch.setenv("DAILYBOT_API_KEY", "k")
        result = runner.invoke(cli, ["agent", "update", "Hello"])
        assert result.exit_code == 1
        # Error goes to stderr but Click captures both into result.output.
        combined: str = result.output + (result.stderr if result.stderr_bytes else "")
        assert "key" in combined.lower()
        assert "credentials" in combined.lower()

    @patch("dailybot_cli.commands.agent.DailyBotClient")
    def test_disabled_marker_does_not_block_cli(
        self,
        mock_client_cls: MagicMock,
        chdir_tmp: Path,
        monkeypatch: pytest.MonkeyPatch,
        runner: CliRunner,
    ) -> None:
        # `.dailybot/disabled` is an opt-out marker for the agent skill, not the
        # CLI. The CLI should still send when the user explicitly invokes it.
        # Verifies that the presence of `disabled` does not prevent profile.json
        # from being read.
        profile_dir: Path = chdir_tmp / ".dailybot"
        profile_dir.mkdir()
        (profile_dir / "disabled").write_text("")
        (profile_dir / "profile.json").write_text(json.dumps({"name": "Core Bot"}))
        monkeypatch.setenv("DAILYBOT_API_KEY", "k")
        mock_client: MagicMock = mock_client_cls.return_value
        mock_client.submit_agent_report.return_value = {"id": 1, "uuid": "u"}

        result = runner.invoke(cli, ["agent", "update", "Update"])
        assert result.exit_code == 0
        kwargs: dict[str, Any] = mock_client.submit_agent_report.call_args.kwargs
        assert kwargs["agent_name"] == "Core Bot"


class TestAgentProfilesResolve:
    def test_resolve_flag_prints_active_profile(
        self,
        chdir_tmp: Path,
        runner: CliRunner,
    ) -> None:
        _write_repo_profile(
            chdir_tmp,
            {"name": "Core Hub Bot", "default_metadata": {"team": "platform"}},
        )
        result = runner.invoke(cli, ["agent", "profiles", "--resolve"])
        assert result.exit_code == 0
        assert "Core Hub Bot" in result.output
        assert "team" in result.output
