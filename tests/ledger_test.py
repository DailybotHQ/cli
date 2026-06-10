"""Tests for the local report ledger (dailybot_cli/ledger.py)."""

import json
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from dailybot_cli import ledger

NOW: datetime = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def _git(*args: str, cwd: Path) -> str:
    """Run git in *cwd* and return stripped stdout."""
    proc: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return proc.stdout.strip()


def _make_repo(path: Path, remote: str | None = "https://github.com/Acme/widget.git") -> Path:
    """Create a git repo with one commit and an optional origin remote."""
    path.mkdir(parents=True, exist_ok=True)
    _git("init", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "Test User", cwd=path)
    (path / "README.md").write_text("hello\n")
    _git("add", ".", cwd=path)
    _git("commit", "-m", "initial", cwd=path)
    if remote:
        _git("remote", "add", "origin", remote, cwd=path)
    return path


def _commit(repo: Path, filename: str = "file.txt", content: str = "x\n") -> str:
    """Add a commit to *repo* and return its sha."""
    (repo / filename).write_text(content)
    _git("add", ".", cwd=repo)
    _git("commit", "-m", f"add {filename}", cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo)


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the config dir and strip ambient auth env vars."""
    cfg: Path = tmp_path / "config"
    monkeypatch.setenv("DAILYBOT_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("DAILYBOT_API_KEY", raising=False)
    monkeypatch.delenv("DAILYBOT_CLI_TOKEN", raising=False)
    return cfg


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _make_repo(tmp_path / "widget")


@pytest.fixture
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> dict[str, datetime]:
    """Freeze ledger time at NOW; tests mutate clock['now'] to advance."""
    clock: dict[str, datetime] = {"now": NOW}
    monkeypatch.setattr(ledger, "_now", lambda: clock["now"])
    return clock


class TestRepoSlug:
    def test_https_remote(self, repo: Path) -> None:
        assert ledger.repo_slug(repo) == "github.com__Acme__widget"

    def test_ssh_remote_matches_https(self, tmp_path: Path) -> None:
        repo: Path = _make_repo(tmp_path / "ssh-repo", remote="git@github.com:Acme/widget.git")
        assert ledger.repo_slug(repo) == "github.com__Acme__widget"

    def test_no_remote_uses_local_prefix(self, tmp_path: Path) -> None:
        repo: Path = _make_repo(tmp_path / "lonely", remote=None)
        slug: str | None = ledger.repo_slug(repo)
        assert slug is not None
        assert slug.startswith("local__lonely__")

    def test_non_git_dir_returns_none(self, tmp_path: Path) -> None:
        plain: Path = tmp_path / "plain"
        plain.mkdir()
        assert ledger.repo_slug(plain) is None

    def test_subdirectory_resolves_same_slug(self, repo: Path) -> None:
        sub: Path = repo / "src" / "deep"
        sub.mkdir(parents=True)
        assert ledger.repo_slug(sub) == "github.com__Acme__widget"


class TestDisabled:
    def test_disabled_marker_found_from_subdir(self, repo: Path) -> None:
        (repo / ".dailybot").mkdir()
        (repo / ".dailybot" / "disabled").touch()
        sub: Path = repo / "src"
        sub.mkdir()
        assert ledger.is_disabled(sub) is True

    def test_no_marker(self, repo: Path) -> None:
        assert ledger.is_disabled(repo) is False


class TestEntryIO:
    def test_roundtrip_and_permissions(self, config_dir: Path) -> None:
        entry: dict = ledger.load_entry("github.com__Acme__widget")
        entry["work_pending"] = True
        ledger.save_entry("github.com__Acme__widget", entry)

        loaded: dict = ledger.load_entry("github.com__Acme__widget")
        assert loaded["work_pending"] is True

        path: Path = ledger.get_ledger_dir() / "github.com__Acme__widget.json"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(ledger.get_ledger_dir().stat().st_mode) == 0o700

    def test_corrupt_file_returns_defaults(self, config_dir: Path) -> None:
        ledger.get_ledger_dir().joinpath("bad.json").write_text("{not json")
        entry: dict = ledger.load_entry("bad")
        assert entry["work_pending"] is False
        assert entry["last_report_at"] is None


class TestSignals:
    def test_record_activity_sets_pending(
        self, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        ledger.record_activity(repo)
        entry: dict = ledger.load_entry("github.com__Acme__widget")
        assert entry["work_pending"] is True
        assert entry["last_activity_at"] is not None

    def test_mark_reported_clears_signals(
        self, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        ledger.record_activity(repo)
        ledger.mark_reported(repo, reported_by="claude-code")
        entry: dict = ledger.load_entry("github.com__Acme__widget")
        assert entry["work_pending"] is False
        assert entry["turns_since_report"] == 0
        assert entry["reported_by"] == "claude-code"
        assert entry["last_reported_commit"] == _git("rev-parse", "HEAD", cwd=repo)

    def test_mark_reported_outside_repo_is_noop(
        self, config_dir: Path, tmp_path: Path, frozen_now: dict
    ) -> None:
        plain: Path = tmp_path / "plain"
        plain.mkdir()
        ledger.mark_reported(plain)  # must not raise
        assert list(ledger.get_ledger_dir().glob("*.json")) == []


class TestEvaluateStop:
    def test_first_sight_initializes_baseline_silently(
        self, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        assert ledger.evaluate_stop(repo) is None
        entry: dict = ledger.load_entry("github.com__Acme__widget")
        assert entry["last_reported_commit"] == _git("rev-parse", "HEAD", cwd=repo)

    def test_new_commit_triggers_strong_nudge(
        self, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        ledger.evaluate_stop(repo)  # baseline
        _commit(repo)
        result: dict | None = ledger.evaluate_stop(repo)
        assert result is not None
        assert result["kind"] == "commits"
        assert result["commit_count"] == 1

    def test_nudge_cooldown_suppresses_repeat(
        self, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        ledger.evaluate_stop(repo)
        _commit(repo)
        assert ledger.evaluate_stop(repo) is not None
        assert ledger.evaluate_stop(repo) is None  # within cooldown
        frozen_now["now"] = NOW + timedelta(minutes=ledger.NUDGE_COOLDOWN_MINUTES + 1)
        assert ledger.evaluate_stop(repo) is not None  # cooldown elapsed

    def test_min_interval_after_report(
        self, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        ledger.evaluate_stop(repo)
        ledger.mark_reported(repo)
        _commit(repo)
        assert ledger.evaluate_stop(repo) is None  # reported < 30 min ago
        frozen_now["now"] = NOW + timedelta(minutes=ledger.DEFAULT_MIN_INTERVAL_MINUTES + 1)
        result: dict | None = ledger.evaluate_stop(repo)
        assert result is not None and result["kind"] == "commits"

    def test_activity_without_commits_soft_nudge_after_interval(
        self, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        ledger.evaluate_stop(repo)  # baseline at NOW
        ledger.record_activity(repo)
        assert ledger.evaluate_stop(repo) is None  # interval since first_seen not met
        frozen_now["now"] = NOW + timedelta(minutes=ledger.DEFAULT_MIN_INTERVAL_MINUTES + 1)
        result: dict | None = ledger.evaluate_stop(repo)
        assert result is not None
        assert result["kind"] == "soft"

    def test_turn_threshold_soft_nudge_without_any_signal(
        self, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        for _ in range(ledger.SOFT_NUDGE_TURN_THRESHOLD):
            ledger.evaluate_stop(repo)
        frozen_now["now"] = NOW + timedelta(minutes=ledger.DEFAULT_MIN_INTERVAL_MINUTES + 1)
        result: dict | None = ledger.evaluate_stop(repo)
        assert result is not None
        assert result["kind"] == "soft"

    def test_quiet_session_stays_silent(
        self, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        ledger.evaluate_stop(repo)
        frozen_now["now"] = NOW + timedelta(hours=2)
        assert ledger.evaluate_stop(repo) is None  # no commits, no activity, few turns

    def test_dismiss_snoozes(self, config_dir: Path, repo: Path, frozen_now: dict) -> None:
        ledger.evaluate_stop(repo)
        ledger.record_activity(repo)
        ledger.dismiss(repo)
        frozen_now["now"] = NOW + timedelta(minutes=ledger.DEFAULT_MIN_INTERVAL_MINUTES + 1)
        assert ledger.evaluate_stop(repo) is None  # snoozed
        ledger.record_activity(repo)
        frozen_now["now"] = NOW + timedelta(minutes=ledger.DEFAULT_SNOOZE_MINUTES + 31)
        result: dict | None = ledger.evaluate_stop(repo)
        assert result is not None and result["kind"] == "soft"

    def test_disabled_repo_is_silent(self, config_dir: Path, repo: Path, frozen_now: dict) -> None:
        ledger.evaluate_stop(repo)
        _commit(repo)
        (repo / ".dailybot").mkdir(exist_ok=True)
        (repo / ".dailybot" / "disabled").touch()
        assert ledger.evaluate_stop(repo) is None

    def test_repo_policy_nudge_false_is_silent(
        self, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        ledger.evaluate_stop(repo)
        _commit(repo)
        (repo / ".dailybot").mkdir(exist_ok=True)
        (repo / ".dailybot" / "profile.json").write_text(json.dumps({"report": {"nudge": False}}))
        assert ledger.evaluate_stop(repo) is None

    def test_repo_policy_custom_interval(
        self, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        (repo / ".dailybot").mkdir(exist_ok=True)
        (repo / ".dailybot" / "profile.json").write_text(
            json.dumps({"report": {"min_interval_minutes": 5}})
        )
        ledger.evaluate_stop(repo)
        ledger.mark_reported(repo)
        _commit(repo)
        frozen_now["now"] = NOW + timedelta(minutes=6)
        result: dict | None = ledger.evaluate_stop(repo)
        assert result is not None and result["kind"] == "commits"

    def test_non_git_dir_is_silent(
        self, config_dir: Path, tmp_path: Path, frozen_now: dict
    ) -> None:
        plain: Path = tmp_path / "plain"
        plain.mkdir()
        assert ledger.evaluate_stop(plain) is None


class TestEvaluateSessionStart:
    def test_login_nudge_when_unauthenticated(
        self, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        result: dict | None = ledger.evaluate_session_start(repo)
        assert result is not None
        assert result["login_needed"] is True

    def test_login_nudge_rate_limited(self, config_dir: Path, repo: Path, frozen_now: dict) -> None:
        assert ledger.evaluate_session_start(repo) is not None
        assert ledger.evaluate_session_start(repo) is None  # same day → silent
        frozen_now["now"] = NOW + timedelta(hours=ledger.LOGIN_NUDGE_INTERVAL_HOURS + 1)
        result: dict | None = ledger.evaluate_session_start(repo)
        assert result is not None and result["login_needed"] is True

    def test_no_login_nudge_with_api_key(
        self,
        config_dir: Path,
        repo: Path,
        frozen_now: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DAILYBOT_API_KEY", "k-1234")
        assert ledger.evaluate_session_start(repo) is None

    def test_leftover_work_reported(
        self,
        config_dir: Path,
        repo: Path,
        frozen_now: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DAILYBOT_API_KEY", "k-1234")
        ledger.evaluate_stop(repo)  # baseline
        _commit(repo)
        result: dict | None = ledger.evaluate_session_start(repo)
        assert result is not None
        assert result["login_needed"] is False
        assert result["unreported_commit_count"] == 1

    def test_disabled_repo_silent(self, config_dir: Path, repo: Path, frozen_now: dict) -> None:
        (repo / ".dailybot").mkdir()
        (repo / ".dailybot" / "disabled").touch()
        assert ledger.evaluate_session_start(repo) is None
