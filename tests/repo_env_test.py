"""Tests for repo-level env override (`.dailybot/env.json`).

Covers:
- Walk-up discovery (mirrors `find_repo_profile_path`).
- Schema validation on load (unknown keys warn, invalid entries skipped).
- `active` resolution (top-level string, empty/null → inert).
- `disabled: true` kill-switch (preserves `active`, ignores the file).
- Committed-to-git guard — fatal (raises `RepoEnvError`).
- File permissions locked to `0o600` on write.
- Precedence in `get_api_key()`, `get_api_url()`, `get_app_url()` — env.json
  active profile wins over env vars, config, and credentials, but yields to
  explicit CLI flag overrides.
- Mutation helpers (`add_env_profile`, `remove_env_profile`, `set_active_env_profile`,
  `set_env_disabled`) — including auto-active on first add and clear-active
  on removal.
"""

import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_env_warnings() -> None:
    """Clear the per-process env.json warning dedup between tests."""
    from dailybot_cli.config import reset_repo_env_warnings

    reset_repo_env_warnings()


@pytest.fixture(autouse=True)
def _isolate_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent leakage from the real developer environment."""
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
    return tmp_path


def _write_env(repo_root: Path, payload: dict[str, Any], *, mode: int | None = None) -> Path:
    env_dir: Path = repo_root / ".dailybot"
    env_dir.mkdir(parents=True, exist_ok=True)
    env_path: Path = env_dir / "env.json"
    env_path.write_text(json.dumps(payload))
    if mode is not None:
        os.chmod(env_path, mode)
    return env_path


# --- find_repo_env_path -----------------------------------------------------


class TestFindRepoEnvPath:
    def test_walk_up_from_nested_cwd(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import find_repo_env_path

        _write_env(chdir_tmp, {"profiles": []})
        nested: Path = chdir_tmp / "src" / "deep"
        nested.mkdir(parents=True)
        found: Path | None = find_repo_env_path(nested)
        assert found is not None
        assert found.parent.parent == chdir_tmp

    def test_closest_ancestor_wins(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import find_repo_env_path

        _write_env(chdir_tmp, {"profiles": []})
        inner: Path = chdir_tmp / "inner"
        inner.mkdir()
        _write_env(inner, {"profiles": [{"name": "x", "api_key": "k"}]})
        assert find_repo_env_path(inner / "src") is None or (
            find_repo_env_path(inner) is not None
            and find_repo_env_path(inner).parent.parent == inner  # type: ignore[union-attr]
        )

    def test_returns_none_when_missing(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import find_repo_env_path

        assert find_repo_env_path(chdir_tmp) is None

    def test_ignores_dailybot_as_regular_file(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import find_repo_env_path

        (chdir_tmp / ".dailybot").write_text("not a directory")
        assert find_repo_env_path(chdir_tmp) is None


# --- load_repo_env ----------------------------------------------------------


class TestLoadRepoEnv:
    def test_loads_valid_payload(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import load_repo_env

        path: Path = _write_env(
            chdir_tmp,
            {
                "active": "live",
                "profiles": [
                    {"name": "live", "api_key": "live-key"},
                    {
                        "name": "local",
                        "api_key": "local-key",
                        "api_url": "http://localhost:8000",
                        "app_url": "http://localhost:8090",
                    },
                ],
            },
        )
        result: dict[str, Any] | None = load_repo_env(chdir_tmp)
        assert result is not None
        assert result["active"] == "live"
        assert result["disabled"] is False
        assert len(result["profiles"]) == 2
        assert result["profiles"][0] == {"name": "live", "api_key": "live-key"}
        assert result["profiles"][1]["api_url"] == "http://localhost:8000"
        assert result["_path"] == str(path)

    def test_active_missing_returns_none_active(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import load_repo_env

        _write_env(chdir_tmp, {"profiles": [{"name": "x", "api_key": "k"}]})
        result: dict[str, Any] | None = load_repo_env(chdir_tmp)
        assert result is not None
        assert result["active"] is None

    def test_active_empty_string_returns_none_active(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import load_repo_env

        _write_env(
            chdir_tmp,
            {"active": "", "profiles": [{"name": "x", "api_key": "k"}]},
        )
        result: dict[str, Any] | None = load_repo_env(chdir_tmp)
        assert result is not None
        assert result["active"] is None

    def test_active_null_returns_none_active(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import load_repo_env

        _write_env(
            chdir_tmp,
            {"active": None, "profiles": [{"name": "x", "api_key": "k"}]},
        )
        result: dict[str, Any] | None = load_repo_env(chdir_tmp)
        assert result is not None
        assert result["active"] is None

    def test_disabled_true_short_circuits(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import load_repo_env

        _write_env(
            chdir_tmp,
            {
                "disabled": True,
                "active": "live",
                "profiles": [{"name": "live", "api_key": "k"}],
            },
        )
        result: dict[str, Any] | None = load_repo_env(chdir_tmp)
        assert result is not None
        assert result["disabled"] is True
        # Profiles are still parsed so `env list` can render them, but the
        # convenience getter surfaces the flag so callers know to bail.

    def test_malformed_json_returns_none(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import load_repo_env

        env_dir: Path = chdir_tmp / ".dailybot"
        env_dir.mkdir()
        (env_dir / "env.json").write_text("{not valid json")
        assert load_repo_env(chdir_tmp) is None

    def test_non_object_json_returns_none(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import load_repo_env

        env_dir: Path = chdir_tmp / ".dailybot"
        env_dir.mkdir()
        (env_dir / "env.json").write_text('["not", "an", "object"]')
        assert load_repo_env(chdir_tmp) is None

    def test_profiles_not_a_list_returns_none(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import load_repo_env

        _write_env(chdir_tmp, {"profiles": "nope"})  # type: ignore[dict-item]
        assert load_repo_env(chdir_tmp) is None

    def test_entry_missing_required_key_is_skipped(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import load_repo_env

        _write_env(
            chdir_tmp,
            {
                "profiles": [
                    {"name": "good", "api_key": "k"},
                    {"name": "missing-key"},
                    {"api_key": "orphan-key"},
                ]
            },
        )
        result: dict[str, Any] | None = load_repo_env(chdir_tmp)
        assert result is not None
        assert [p["name"] for p in result["profiles"]] == ["good"]

    def test_unknown_top_level_keys_are_dropped(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import load_repo_env

        _write_env(
            chdir_tmp,
            {
                "profiles": [{"name": "x", "api_key": "k"}],
                "future_field": "ignored",
            },
        )
        result: dict[str, Any] | None = load_repo_env(chdir_tmp)
        assert result is not None
        assert "future_field" not in result

    def test_unknown_profile_keys_are_dropped(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import load_repo_env

        _write_env(
            chdir_tmp,
            {
                "profiles": [
                    {
                        "name": "x",
                        "api_key": "k",
                        "webAppUrl": "http://x",
                        "note": "future",
                    }
                ]
            },
        )
        result: dict[str, Any] | None = load_repo_env(chdir_tmp)
        assert result is not None
        assert result["profiles"][0] == {"name": "x", "api_key": "k"}

    def test_defensive_chmod_when_file_lax(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import load_repo_env

        path: Path = _write_env(
            chdir_tmp,
            {"profiles": [{"name": "x", "api_key": "k"}]},
            mode=0o644,
        )
        load_repo_env(chdir_tmp)
        mode: int = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600


# --- Committed-to-git guard -------------------------------------------------


class TestCommittedGuard:
    def test_untracked_in_git_repo_is_allowed(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import load_repo_env

        # Init a git repo and make sure the file is gitignored.
        subprocess.run(["git", "init", "-q"], cwd=chdir_tmp, check=True)
        (chdir_tmp / ".gitignore").write_text(".dailybot/*\n")
        _write_env(chdir_tmp, {"profiles": [{"name": "x", "api_key": "k"}]})
        result: dict[str, Any] | None = load_repo_env(chdir_tmp)
        assert result is not None

    def test_tracked_env_json_raises(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import RepoEnvError, load_repo_env

        subprocess.run(["git", "init", "-q"], cwd=chdir_tmp, check=True)
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
        _write_env(chdir_tmp, {"profiles": [{"name": "x", "api_key": "leaked"}]})
        # Intentionally track it — simulates a developer mistake.
        subprocess.run(
            ["git", "add", "-f", ".dailybot/env.json"],
            cwd=chdir_tmp,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "leak"],
            cwd=chdir_tmp,
            check=True,
        )
        with pytest.raises(RepoEnvError) as exc_info:
            load_repo_env(chdir_tmp)
        message: str = str(exc_info.value)
        assert "tracked" in message.lower()
        assert "credentials" in message.lower() or "api key" in message.lower()

    def test_no_git_at_all_is_allowed(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import load_repo_env

        # No `git init` at all — the guard should skip cleanly.
        _write_env(chdir_tmp, {"profiles": [{"name": "x", "api_key": "k"}]})
        result: dict[str, Any] | None = load_repo_env(chdir_tmp)
        assert result is not None


# --- get_active_env_profile -------------------------------------------------


class TestGetActiveEnvProfile:
    def test_returns_active_profile(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import get_active_env_profile

        _write_env(
            chdir_tmp,
            {
                "active": "local",
                "profiles": [
                    {"name": "live", "api_key": "live-k"},
                    {
                        "name": "local",
                        "api_key": "local-k",
                        "api_url": "http://localhost:8000",
                    },
                ],
            },
        )
        active: dict[str, Any] | None = get_active_env_profile(chdir_tmp)
        assert active is not None
        assert active["name"] == "local"
        assert active["api_key"] == "local-k"
        assert active["api_url"] == "http://localhost:8000"

    def test_missing_active_returns_none(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import get_active_env_profile

        _write_env(chdir_tmp, {"profiles": [{"name": "x", "api_key": "k"}]})
        assert get_active_env_profile(chdir_tmp) is None

    def test_active_unknown_name_returns_none(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import get_active_env_profile

        _write_env(
            chdir_tmp,
            {
                "active": "ghost",
                "profiles": [{"name": "live", "api_key": "k"}],
            },
        )
        assert get_active_env_profile(chdir_tmp) is None

    def test_disabled_true_returns_none_even_with_active(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import get_active_env_profile

        _write_env(
            chdir_tmp,
            {
                "disabled": True,
                "active": "live",
                "profiles": [{"name": "live", "api_key": "k"}],
            },
        )
        assert get_active_env_profile(chdir_tmp) is None

    def test_no_file_returns_none(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import get_active_env_profile

        assert get_active_env_profile(chdir_tmp) is None


# --- save_repo_env ----------------------------------------------------------


class TestSaveRepoEnv:
    def test_writes_at_repo_root_with_0600(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import save_repo_env

        subprocess.run(["git", "init", "-q"], cwd=chdir_tmp, check=True)
        nested: Path = chdir_tmp / "src" / "deep"
        nested.mkdir(parents=True)
        path: Path = save_repo_env(
            {"active": "x", "profiles": [{"name": "x", "api_key": "k"}]},
            cwd=nested,
        )
        # File anchors at git repo root, not the nested cwd.
        assert path == chdir_tmp / ".dailybot" / "env.json"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_validation_rejects_missing_required(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import RepoEnvError, save_repo_env

        with pytest.raises(RepoEnvError):
            save_repo_env(
                {"profiles": [{"name": "x"}]},  # missing api_key
                cwd=chdir_tmp,
            )

    def test_validation_rejects_duplicate_names(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import RepoEnvError, save_repo_env

        with pytest.raises(RepoEnvError):
            save_repo_env(
                {
                    "profiles": [
                        {"name": "x", "api_key": "k1"},
                        {"name": "x", "api_key": "k2"},
                    ],
                },
                cwd=chdir_tmp,
            )

    def test_validation_rejects_active_pointing_to_ghost(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import RepoEnvError, save_repo_env

        with pytest.raises(RepoEnvError):
            save_repo_env(
                {
                    "active": "ghost",
                    "profiles": [{"name": "x", "api_key": "k"}],
                },
                cwd=chdir_tmp,
            )

    def test_validation_rejects_unknown_top_level_key(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import RepoEnvError, save_repo_env

        with pytest.raises(RepoEnvError):
            save_repo_env(
                {
                    "profiles": [{"name": "x", "api_key": "k"}],
                    "weird": True,
                },
                cwd=chdir_tmp,
            )

    def test_validation_rejects_unknown_profile_key(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import RepoEnvError, save_repo_env

        with pytest.raises(RepoEnvError):
            save_repo_env(
                {
                    "profiles": [
                        {"name": "x", "api_key": "k", "extra": "no"},
                    ],
                },
                cwd=chdir_tmp,
            )


# --- Mutation helpers -------------------------------------------------------


class TestAddEnvProfile:
    def test_creates_file_when_missing(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import add_env_profile

        subprocess.run(["git", "init", "-q"], cwd=chdir_tmp, check=True)
        path, became_active = add_env_profile(
            name="local",
            api_key="k",
            api_url="http://localhost:8000",
            cwd=chdir_tmp,
        )
        assert path.exists()
        assert became_active is True
        payload: dict[str, Any] = json.loads(path.read_text())
        assert payload["active"] == "local"
        assert payload["profiles"][0]["api_url"] == "http://localhost:8000"

    def test_appends_without_touching_active(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import add_env_profile

        subprocess.run(["git", "init", "-q"], cwd=chdir_tmp, check=True)
        add_env_profile(name="live", api_key="live-k", cwd=chdir_tmp)
        path, became_active = add_env_profile(
            name="local",
            api_key="local-k",
            cwd=chdir_tmp,
        )
        assert became_active is False
        payload: dict[str, Any] = json.loads(path.read_text())
        assert payload["active"] == "live"
        assert [p["name"] for p in payload["profiles"]] == ["live", "local"]

    def test_duplicate_name_raises(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import RepoEnvError, add_env_profile

        subprocess.run(["git", "init", "-q"], cwd=chdir_tmp, check=True)
        add_env_profile(name="live", api_key="k", cwd=chdir_tmp)
        with pytest.raises(RepoEnvError):
            add_env_profile(name="live", api_key="other", cwd=chdir_tmp)

    def test_normalizes_trailing_slash_in_urls(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import add_env_profile

        subprocess.run(["git", "init", "-q"], cwd=chdir_tmp, check=True)
        path, _ = add_env_profile(
            name="local",
            api_key="k",
            api_url="http://localhost:8000/",
            app_url="http://localhost:8090/",
            cwd=chdir_tmp,
        )
        payload: dict[str, Any] = json.loads(path.read_text())
        assert payload["profiles"][0]["api_url"] == "http://localhost:8000"
        assert payload["profiles"][0]["app_url"] == "http://localhost:8090"


class TestSetActiveEnvProfile:
    def test_switches_active(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import (
            add_env_profile,
            get_active_env_profile,
            set_active_env_profile,
        )

        subprocess.run(["git", "init", "-q"], cwd=chdir_tmp, check=True)
        add_env_profile(name="live", api_key="live-k", cwd=chdir_tmp)
        add_env_profile(name="local", api_key="local-k", cwd=chdir_tmp)
        set_active_env_profile("local", cwd=chdir_tmp)
        active: dict[str, Any] | None = get_active_env_profile(chdir_tmp)
        assert active is not None
        assert active["name"] == "local"

    def test_clear_active_with_none(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import (
            add_env_profile,
            get_active_env_profile,
            set_active_env_profile,
        )

        subprocess.run(["git", "init", "-q"], cwd=chdir_tmp, check=True)
        add_env_profile(name="live", api_key="k", cwd=chdir_tmp)
        set_active_env_profile(None, cwd=chdir_tmp)
        assert get_active_env_profile(chdir_tmp) is None

    def test_unknown_name_raises(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import (
            RepoEnvError,
            add_env_profile,
            set_active_env_profile,
        )

        subprocess.run(["git", "init", "-q"], cwd=chdir_tmp, check=True)
        add_env_profile(name="live", api_key="k", cwd=chdir_tmp)
        with pytest.raises(RepoEnvError):
            set_active_env_profile("ghost", cwd=chdir_tmp)

    def test_no_file_raises(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import RepoEnvError, set_active_env_profile

        with pytest.raises(RepoEnvError):
            set_active_env_profile("live", cwd=chdir_tmp)


class TestRemoveEnvProfile:
    def test_removes_and_preserves_active(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import (
            add_env_profile,
            get_active_env_profile,
            remove_env_profile,
        )

        subprocess.run(["git", "init", "-q"], cwd=chdir_tmp, check=True)
        add_env_profile(name="live", api_key="live-k", cwd=chdir_tmp)
        add_env_profile(name="local", api_key="local-k", cwd=chdir_tmp)
        _, cleared = remove_env_profile("local", cwd=chdir_tmp)
        assert cleared is False
        active: dict[str, Any] | None = get_active_env_profile(chdir_tmp)
        assert active is not None
        assert active["name"] == "live"

    def test_removing_active_clears_active(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import (
            add_env_profile,
            get_active_env_profile,
            remove_env_profile,
        )

        subprocess.run(["git", "init", "-q"], cwd=chdir_tmp, check=True)
        add_env_profile(name="live", api_key="k", cwd=chdir_tmp)
        _, cleared = remove_env_profile("live", cwd=chdir_tmp)
        assert cleared is True
        assert get_active_env_profile(chdir_tmp) is None

    def test_unknown_name_raises(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import (
            RepoEnvError,
            add_env_profile,
            remove_env_profile,
        )

        subprocess.run(["git", "init", "-q"], cwd=chdir_tmp, check=True)
        add_env_profile(name="live", api_key="k", cwd=chdir_tmp)
        with pytest.raises(RepoEnvError):
            remove_env_profile("ghost", cwd=chdir_tmp)

    def test_no_file_raises(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import RepoEnvError, remove_env_profile

        with pytest.raises(RepoEnvError):
            remove_env_profile("x", cwd=chdir_tmp)


class TestSetEnvDisabled:
    def test_off_then_on(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import (
            add_env_profile,
            get_active_env_profile,
            load_repo_env,
            set_env_disabled,
        )

        subprocess.run(["git", "init", "-q"], cwd=chdir_tmp, check=True)
        add_env_profile(name="live", api_key="k", cwd=chdir_tmp)
        set_env_disabled(True, cwd=chdir_tmp)
        assert get_active_env_profile(chdir_tmp) is None
        loaded: dict[str, Any] | None = load_repo_env(chdir_tmp)
        assert loaded is not None
        assert loaded["disabled"] is True
        # Turning it back on restores the active profile.
        set_env_disabled(False, cwd=chdir_tmp)
        active: dict[str, Any] | None = get_active_env_profile(chdir_tmp)
        assert active is not None
        assert active["name"] == "live"

    def test_no_file_raises(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import RepoEnvError, set_env_disabled

        with pytest.raises(RepoEnvError):
            set_env_disabled(True, cwd=chdir_tmp)


# --- Precedence in get_api_key / get_api_url / get_app_url ------------------


class TestPrecedence:
    def test_env_json_beats_env_var_for_api_key(
        self, chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dailybot_cli.config import get_api_key

        _write_env(
            chdir_tmp,
            {
                "active": "local",
                "profiles": [{"name": "local", "api_key": "env-json-key"}],
            },
        )
        monkeypatch.setenv("DAILYBOT_API_KEY", "env-var-key")
        assert get_api_key() == "env-json-key"

    def test_env_var_wins_when_env_json_inert(
        self, chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dailybot_cli.config import get_api_key

        _write_env(chdir_tmp, {"profiles": [{"name": "local", "api_key": "j"}]})
        monkeypatch.setenv("DAILYBOT_API_KEY", "env-var-key")
        assert get_api_key() == "env-var-key"

    def test_env_var_wins_when_env_json_disabled(
        self, chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dailybot_cli.config import get_api_key

        _write_env(
            chdir_tmp,
            {
                "disabled": True,
                "active": "local",
                "profiles": [{"name": "local", "api_key": "env-json-key"}],
            },
        )
        monkeypatch.setenv("DAILYBOT_API_KEY", "env-var-key")
        assert get_api_key() == "env-var-key"

    def test_env_json_provides_api_url(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import get_api_url

        _write_env(
            chdir_tmp,
            {
                "active": "local",
                "profiles": [
                    {
                        "name": "local",
                        "api_key": "k",
                        "api_url": "http://localhost:8000",
                    }
                ],
            },
        )
        assert get_api_url() == "http://localhost:8000"

    def test_cli_flag_beats_env_json_for_api_url(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import get_api_url, set_api_url_override

        _write_env(
            chdir_tmp,
            {
                "active": "local",
                "profiles": [
                    {
                        "name": "local",
                        "api_key": "k",
                        "api_url": "http://localhost:8000",
                    }
                ],
            },
        )
        set_api_url_override("https://explicit.example.com")
        try:
            assert get_api_url() == "https://explicit.example.com"
        finally:
            set_api_url_override("")  # reset; empty string clears the override

    def test_env_json_without_api_url_falls_through_to_default(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import DEFAULT_API_URL, get_api_url

        _write_env(
            chdir_tmp,
            {
                "active": "live",
                "profiles": [{"name": "live", "api_key": "k"}],
            },
        )
        assert get_api_url() == DEFAULT_API_URL

    def test_env_json_provides_app_url(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import get_app_url

        _write_env(
            chdir_tmp,
            {
                "active": "local",
                "profiles": [
                    {
                        "name": "local",
                        "api_key": "k",
                        "app_url": "http://localhost:8090",
                    }
                ],
            },
        )
        assert get_app_url() == "http://localhost:8090"


# --- End-to-end: DailyBotClient sees env.json credentials -------------------


class TestClientIntegration:
    def test_client_uses_env_json_credentials(self, chdir_tmp: Path) -> None:
        _write_env(
            chdir_tmp,
            {
                "active": "local",
                "profiles": [
                    {
                        "name": "local",
                        "api_key": "env-json-key",
                        "api_url": "http://localhost:8000",
                    }
                ],
            },
        )
        # Import late so the env.json is picked up on construction.
        from dailybot_cli.api_client import DailyBotClient

        client: DailyBotClient = DailyBotClient()
        assert client.api_key == "env-json-key"
        assert client.api_url == "http://localhost:8000"

    def test_client_falls_back_when_env_json_inert(
        self, chdir_tmp: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_env(
            chdir_tmp,
            {"profiles": [{"name": "local", "api_key": "j"}]},
        )
        monkeypatch.setenv("DAILYBOT_API_KEY", "env-var-key")
        from dailybot_cli.api_client import DailyBotClient

        client: DailyBotClient = DailyBotClient()
        assert client.api_key == "env-var-key"


# --- Committed-guard integration with load_repo_env -------------------------


class TestFatalGuardBubbles:
    def test_load_raises_and_caller_sees_it(self, chdir_tmp: Path) -> None:
        """If env.json is tracked, get_active_env_profile must propagate the fatal."""
        from dailybot_cli.config import RepoEnvError, get_active_env_profile

        subprocess.run(["git", "init", "-q"], cwd=chdir_tmp, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=chdir_tmp,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "T"],
            cwd=chdir_tmp,
            check=True,
        )
        _write_env(chdir_tmp, {"profiles": [{"name": "x", "api_key": "k"}]})
        subprocess.run(
            ["git", "add", "-f", ".dailybot/env.json"],
            cwd=chdir_tmp,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "leak"],
            cwd=chdir_tmp,
            check=True,
        )
        with pytest.raises(RepoEnvError):
            get_active_env_profile(chdir_tmp)


# --- Guard-check mocking ----------------------------------------------------


class TestResolverProvenance:
    """`resolve_active_profile` surfaces env.json fields so `agent profiles
    --resolve` can render the full auth picture."""

    def test_env_json_appears_in_resolution(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import resolve_active_profile

        _write_env(
            chdir_tmp,
            {
                "active": "local",
                "profiles": [
                    {
                        "name": "local",
                        "api_key": "env-json-key",
                        "api_url": "http://localhost:8000",
                        "app_url": "http://localhost:8090",
                    }
                ],
            },
        )
        resolved: dict[str, Any] = resolve_active_profile(None, None, cwd=chdir_tmp)
        assert resolved["env_profile_name"] == "local"
        assert resolved["env_profile_api_url"] == "http://localhost:8000"
        assert resolved["env_profile_app_url"] == "http://localhost:8090"
        assert resolved["api_key"] == "env-json-key"
        assert resolved["resolved_from"]["api_key"] == "env.json"

    def test_env_json_beats_global_profile_key(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import resolve_active_profile

        _write_env(
            chdir_tmp,
            {
                "active": "local",
                "profiles": [{"name": "local", "api_key": "env-json-key"}],
            },
        )
        # A global profile shouldn't win over env.json.
        with patch(
            "dailybot_cli.config.get_default_profile",
            return_value={
                "profile": "default",
                "agent_name": "Bot",
                "api_key": "global-key",
            },
        ):
            resolved: dict[str, Any] = resolve_active_profile(None, None, cwd=chdir_tmp)
        assert resolved["api_key"] == "env-json-key"
        assert resolved["resolved_from"]["api_key"] == "env.json"

    def test_no_env_json_leaves_provenance_untouched(self, chdir_tmp: Path) -> None:
        from dailybot_cli.config import resolve_active_profile

        resolved: dict[str, Any] = resolve_active_profile(None, None, cwd=chdir_tmp)
        assert resolved["env_profile_name"] is None
        assert resolved["env_profile_error"] is None


class TestGuardIsFactoredOut:
    """The git-tracked check must be independently mockable so downstream tests
    can bypass it without needing a real git repo."""

    def test_can_patch_the_guard(self, chdir_tmp: Path) -> None:
        _write_env(chdir_tmp, {"profiles": [{"name": "x", "api_key": "k"}]})
        with patch("dailybot_cli.config._is_env_tracked_by_git", return_value=False):
            from dailybot_cli.config import load_repo_env

            assert load_repo_env(chdir_tmp) is not None
