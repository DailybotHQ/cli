"""Tests for config module."""

import os
from pathlib import Path
from typing import Any

import pytest

from dailybot_cli.config import (
    clear_credentials,
    get_agent_auth,
    get_api_key,
    get_api_url,
    get_app_url,
    get_token,
    load_config,
    load_credentials,
    save_config,
    save_credentials,
)


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override config paths to use a temp directory."""
    config_dir: Path = tmp_path / ".config" / "dailybot"
    creds_file: Path = config_dir / "credentials.json"
    config_file: Path = config_dir / "config.json"
    monkeypatch.setattr("dailybot_cli.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("dailybot_cli.config.CREDENTIALS_FILE", creds_file)
    monkeypatch.setattr("dailybot_cli.config.CONFIG_FILE", config_file)
    return config_dir


def test_save_and_load_credentials(tmp_config: Path) -> None:
    save_credentials(
        token="tok123",
        email="user@example.com",
        organization="MyOrg",
        organization_uuid="org-uuid-42",
    )
    creds: dict[str, Any] | None = load_credentials()
    assert creds is not None
    assert creds["token"] == "tok123"
    assert creds["email"] == "user@example.com"
    assert creds["organization"] == "MyOrg"
    assert creds["organization_uuid"] == "org-uuid-42"


def test_load_credentials_no_file(tmp_config: Path) -> None:
    assert load_credentials() is None


def test_clear_credentials(tmp_config: Path) -> None:
    save_credentials(token="t", email="e", organization="o", organization_uuid="uuid-1")
    clear_credentials()
    assert load_credentials() is None


def test_get_api_url_default(tmp_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DAILYBOT_API_URL", raising=False)
    assert get_api_url() == "https://api.dailybot.com"


def test_get_api_url_from_env(tmp_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILYBOT_API_URL", "http://localhost:8600/")
    assert get_api_url() == "http://localhost:8600"


def test_get_app_url_default(tmp_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DAILYBOT_APP_URL", raising=False)
    monkeypatch.setattr("dailybot_cli.config._app_url_override", None)
    assert get_app_url() == "https://app.dailybot.com"


def test_get_app_url_from_env(tmp_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILYBOT_APP_URL", "http://localhost:8090/")
    assert get_app_url() == "http://localhost:8090"


def test_get_token_from_env(tmp_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILYBOT_CLI_TOKEN", "env_token")
    assert get_token() == "env_token"


def test_get_token_from_credentials(tmp_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DAILYBOT_CLI_TOKEN", raising=False)
    save_credentials(token="file_token", email="e", organization="o", organization_uuid="uuid-1")
    assert get_token() == "file_token"


def test_get_api_key_from_env(tmp_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILYBOT_API_KEY", "apikey123")
    assert get_api_key() == "apikey123"


def test_get_api_key_not_set(tmp_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DAILYBOT_API_KEY", raising=False)
    assert get_api_key() is None


def test_get_api_key_from_config(tmp_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DAILYBOT_API_KEY", raising=False)
    save_config({"api_key": "stored-key"})
    assert get_api_key() == "stored-key"


def test_get_api_key_env_overrides_config(
    tmp_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DAILYBOT_API_KEY", "env-key")
    save_config({"api_key": "stored-key"})
    assert get_api_key() == "env-key"


def test_credentials_file_permissions(tmp_config: Path) -> None:
    save_credentials(token="t", email="e", organization="o", organization_uuid="uuid-1")
    creds_file: Path = tmp_config / "credentials.json"
    mode: int = os.stat(creds_file).st_mode & 0o777
    assert mode == 0o600


# --- Config storage tests ---


def test_save_and_load_config(tmp_config: Path) -> None:
    save_config({"api_key": "abc123"})
    data: dict[str, Any] = load_config()
    assert data["api_key"] == "abc123"


def test_load_config_no_file(tmp_config: Path) -> None:
    assert load_config() == {}


def test_save_config_merges(tmp_config: Path) -> None:
    save_config({"api_key": "key1"})
    save_config({"other": "value"})
    data: dict[str, Any] = load_config()
    assert data["api_key"] == "key1"
    assert data["other"] == "value"


def test_save_config_removes_none(tmp_config: Path) -> None:
    save_config({"api_key": "key1", "other": "val"})
    save_config({"api_key": None})
    data: dict[str, Any] = load_config()
    assert "api_key" not in data
    assert data["other"] == "val"


def test_config_file_permissions(tmp_config: Path) -> None:
    save_config({"api_key": "secret"})
    config_file: Path = tmp_config / "config.json"
    mode: int = os.stat(config_file).st_mode & 0o777
    assert mode == 0o600


# --- get_agent_auth tests ---


def test_get_agent_auth_api_key(tmp_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILYBOT_API_KEY", "key")
    monkeypatch.delenv("DAILYBOT_CLI_TOKEN", raising=False)
    assert get_agent_auth() == "api_key"


def test_get_agent_auth_bearer(tmp_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DAILYBOT_API_KEY", raising=False)
    monkeypatch.delenv("DAILYBOT_CLI_TOKEN", raising=False)
    save_credentials(token="tok", email="e", organization="o", organization_uuid="uuid-1")
    assert get_agent_auth() == "bearer"


def test_get_agent_auth_none(tmp_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DAILYBOT_API_KEY", raising=False)
    monkeypatch.delenv("DAILYBOT_CLI_TOKEN", raising=False)
    assert get_agent_auth() is None


def test_save_and_get_org_plan(tmp_config: Path) -> None:
    from dailybot_cli.config import get_org_plan, save_org_plan

    save_org_plan("org-uuid-1", "free")
    assert get_org_plan("org-uuid-1") == "free"


def test_get_org_plan_unknown_is_none(tmp_config: Path) -> None:
    from dailybot_cli.config import get_org_plan

    # Missing file → unknown
    assert get_org_plan("never-seen") is None


def test_save_org_plan_none_removes_entry(tmp_config: Path) -> None:
    from dailybot_cli.config import get_org_plan, save_org_plan

    save_org_plan("org-x", "paid")
    save_org_plan("org-x", None)
    assert get_org_plan("org-x") is None


def test_plan_cache_is_0600(tmp_config: Path) -> None:
    from dailybot_cli.config import _plan_cache_path, save_org_plan

    save_org_plan("org-perm", "free")
    mode: int = _plan_cache_path().stat().st_mode & 0o777
    assert mode == 0o600


def test_get_org_plan_none_uuid(tmp_config: Path) -> None:
    from dailybot_cli.config import get_org_plan

    assert get_org_plan(None) is None


def test_plan_cache_tolerates_malformed_file(tmp_config: Path) -> None:
    from dailybot_cli.config import _plan_cache_path, get_org_plan

    _plan_cache_path().write_text("{ not json")
    assert get_org_plan("org-any") is None


class TestSecretFilesFromTheFirstByte:
    """CLI-8: secret stores are created 0o600 by os.open, not tightened afterwards."""

    @pytest.fixture
    def no_chmod(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # With chmod disabled and a permissive umask, only a 0o600 create passes.
        monkeypatch.setattr("dailybot_cli.config.os.chmod", lambda *_a, **_k: None)
        previous: int = os.umask(0)
        yield
        os.umask(previous)

    def _mode(self, path: Path) -> int:
        return path.stat().st_mode & 0o777

    def test_credentials(self, tmp_config: Path, no_chmod: None) -> None:
        save_credentials(
            token="test-token", email="me@example.com", organization="O", organization_uuid="org-1"
        )
        assert self._mode(tmp_config / "credentials.json") == 0o600

    def test_config(self, tmp_config: Path, no_chmod: None) -> None:
        save_config({"api_key": "test-key"})
        assert self._mode(tmp_config / "config.json") == 0o600

    def test_agents(self, tmp_config: Path, no_chmod: None) -> None:
        from dailybot_cli.config import save_agent_profile

        save_agent_profile("bot", agent_name="Bot", api_key="test-key")
        assert self._mode(tmp_config / "agents.json") == 0o600

    def test_org_and_plan_caches(self, tmp_config: Path, no_chmod: None) -> None:
        from dailybot_cli.config import save_org_cache, save_org_plan

        save_org_cache("me@example.com", [{"uuid": "org-1", "name": "O"}])
        save_org_plan("org-1", "free")
        for path in tmp_config.iterdir():
            assert self._mode(path) == 0o600, path.name

    def test_a_new_config_dir_is_owner_only(self, tmp_config: Path, no_chmod: None) -> None:
        save_credentials(
            token="test-token", email="me@example.com", organization="O", organization_uuid="org-1"
        )
        assert self._mode(tmp_config) == 0o700

    def test_an_existing_loose_file_is_tightened(self, tmp_config: Path) -> None:
        tmp_config.mkdir(parents=True)
        creds: Path = tmp_config / "credentials.json"
        creds.write_text("{}")
        os.chmod(creds, 0o644)
        save_credentials(
            token="test-token", email="me@example.com", organization="O", organization_uuid="org-1"
        )
        assert self._mode(creds) == 0o600


def test_a_loose_secret_file_is_tightened_before_the_secret_is_written(
    tmp_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mode is fixed on the descriptor, so no byte lands under the old 0o644."""
    tmp_config.mkdir(parents=True)
    creds: Path = tmp_config / "credentials.json"
    creds.write_text("{}")
    os.chmod(creds, 0o644)
    modes_at_write: list[int] = []
    real_fdopen: Any = os.fdopen

    def _spy_fdopen(fd: int, *args: Any, **kwargs: Any) -> Any:
        modes_at_write.append(os.fstat(fd).st_mode & 0o777)
        return real_fdopen(fd, *args, **kwargs)

    monkeypatch.setattr("dailybot_cli.config.os.fdopen", _spy_fdopen)
    save_credentials(
        token="test-token", email="me@example.com", organization="O", organization_uuid="org-1"
    )
    assert modes_at_write == [0o600]
