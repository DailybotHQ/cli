"""Shared pytest fixtures for the Dailybot CLI test suite."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep every test away from the developer's real environment.

    Two leaks are closed here:

    - ``~/.config/dailybot/`` — commands with local side effects (e.g.
      ``agent update`` resetting the report ledger) would otherwise write to
      the real config dir during test runs.
    - The repo checkout's own ``.dailybot/profile.json`` — repo-profile
      resolution walks up from the current directory, so running pytest from
      a checkout with a local (gitignored) profile leaked its ``name`` and
      ``default_metadata`` into command tests and failed them.

    Tests that need a specific location still win: setting the
    ``DAILYBOT_CONFIG_DIR`` env var, re-patching ``CONFIG_DIR``, or calling
    ``monkeypatch.chdir(...)`` inside a test/fixture overrides this baseline.
    """
    config_dir: Path = tmp_path / "isolated-dailybot-config"
    monkeypatch.delenv("DAILYBOT_CONFIG_DIR", raising=False)
    monkeypatch.setattr("dailybot_cli.config.CONFIG_DIR", config_dir)
    cwd: Path = tmp_path / "isolated-cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return config_dir
