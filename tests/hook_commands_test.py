"""Tests for the `dailybot hook` lifecycle command group."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from dailybot_cli import ledger
from dailybot_cli.main import cli

NOW: datetime = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def _git(*args: str, cwd: Path) -> str:
    proc: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return proc.stdout.strip()


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "Test User", cwd=path)
    (path / "README.md").write_text("hello\n")
    _git("add", ".", cwd=path)
    _git("commit", "-m", "initial", cwd=path)
    _git("remote", "add", "origin", "https://github.com/Acme/widget.git", cwd=path)
    return path


def _commit(repo: Path, filename: str = "file.txt") -> None:
    (repo / filename).write_text("x\n")
    _git("add", ".", cwd=repo)
    _git("commit", "-m", f"add {filename}", cwd=repo)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg: Path = tmp_path / "config"
    monkeypatch.setenv("DAILYBOT_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("DAILYBOT_API_KEY", raising=False)
    monkeypatch.delenv("DAILYBOT_CLI_TOKEN", raising=False)
    return cfg


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path: Path = _make_repo(tmp_path / "widget")
    monkeypatch.chdir(path)
    return path


@pytest.fixture
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> dict[str, datetime]:
    clock: dict[str, datetime] = {"now": NOW}
    monkeypatch.setattr(ledger, "_now", lambda: clock["now"])
    return clock


class TestHookStop:
    def test_non_git_dir_silent(
        self,
        runner: CliRunner,
        config_dir: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plain: Path = tmp_path / "plain"
        plain.mkdir()
        monkeypatch.chdir(plain)
        result = runner.invoke(cli, ["hook", "stop"])
        assert result.exit_code == 0
        assert result.output == ""

    def test_first_sight_silent(
        self, runner: CliRunner, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        result = runner.invoke(cli, ["hook", "stop"])
        assert result.exit_code == 0
        assert result.output == ""

    def test_commit_nudge_claude_format(
        self, runner: CliRunner, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        runner.invoke(cli, ["hook", "stop"])  # baseline
        _commit(repo)
        result = runner.invoke(cli, ["hook", "stop", "--format", "claude"])
        assert result.exit_code == 0
        payload: dict = json.loads(result.output)
        assert payload["decision"] == "block"
        assert "1 commit" in payload["reason"]
        assert "dailybot agent update" in payload["reason"]

    def test_commit_nudge_cursor_format(
        self, runner: CliRunner, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        runner.invoke(cli, ["hook", "stop"])
        _commit(repo)
        result = runner.invoke(cli, ["hook", "stop", "--format", "cursor"])
        payload: dict = json.loads(result.output)
        assert "commit" in payload["followup_message"]

    def test_commit_nudge_generic_format(
        self, runner: CliRunner, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        runner.invoke(cli, ["hook", "stop"])
        _commit(repo)
        result = runner.invoke(cli, ["hook", "stop"])
        assert result.output.startswith("Dailybot reminder:")

    def test_soft_nudge_mentions_dismiss_and_non_commit_work(
        self, runner: CliRunner, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        runner.invoke(cli, ["hook", "stop"])  # baseline
        runner.invoke(cli, ["hook", "activity"])
        frozen_now["now"] = NOW + timedelta(minutes=ledger.DEFAULT_MIN_INTERVAL_MINUTES + 1)
        result = runner.invoke(cli, ["hook", "stop"])
        assert "research" in result.output
        assert "dailybot hook dismiss" in result.output

    def test_internal_error_still_exits_zero(
        self,
        runner: CliRunner,
        config_dir: Path,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _boom() -> None:
            raise RuntimeError("ledger exploded")

        monkeypatch.setattr(ledger, "evaluate_stop", lambda: _boom())
        result = runner.invoke(cli, ["hook", "stop"])
        assert result.exit_code == 0
        assert result.output == ""


class TestHookSignals:
    def test_post_commit_then_stop_nudges(
        self, runner: CliRunner, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        _commit(repo)
        result = runner.invoke(cli, ["hook", "post-commit"])
        assert result.exit_code == 0
        assert result.output == ""
        result = runner.invoke(cli, ["hook", "stop", "--format", "claude"])
        payload: dict = json.loads(result.output)
        assert payload["decision"] == "block"

    def test_dismiss_silences(
        self, runner: CliRunner, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        runner.invoke(cli, ["hook", "stop"])  # baseline
        runner.invoke(cli, ["hook", "activity"])
        result = runner.invoke(cli, ["hook", "dismiss"])
        assert result.exit_code == 0
        assert "snoozed" in result.output.lower()
        frozen_now["now"] = NOW + timedelta(minutes=ledger.DEFAULT_MIN_INTERVAL_MINUTES + 1)
        result = runner.invoke(cli, ["hook", "stop"])
        assert result.output == ""


class TestHookSessionStart:
    def test_login_nudge_claude_format(
        self, runner: CliRunner, config_dir: Path, repo: Path, frozen_now: dict
    ) -> None:
        result = runner.invoke(cli, ["hook", "session-start", "--format", "claude"])
        assert result.exit_code == 0
        payload: dict = json.loads(result.output)
        context: str = payload["hookSpecificOutput"]["additionalContext"]
        assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "dailybot login" in context

    def test_silent_when_authenticated_and_clean(
        self,
        runner: CliRunner,
        config_dir: Path,
        repo: Path,
        frozen_now: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DAILYBOT_API_KEY", "k-1234")
        result = runner.invoke(cli, ["hook", "session-start"])
        assert result.exit_code == 0
        assert result.output == ""

    def test_leftover_work_mentioned(
        self,
        runner: CliRunner,
        config_dir: Path,
        repo: Path,
        frozen_now: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DAILYBOT_API_KEY", "k-1234")
        runner.invoke(cli, ["hook", "stop"])  # baseline
        _commit(repo)
        result = runner.invoke(cli, ["hook", "session-start"])
        assert "1 unreported commit" in result.output
