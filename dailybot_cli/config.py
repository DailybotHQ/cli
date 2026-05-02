"""Credential and configuration management for Dailybot CLI."""

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_API_URL: str = "https://api.dailybot.com"
_api_url_override: str | None = None


def set_api_url_override(url: str) -> None:
    """Set a CLI-level API URL override (from --api-url flag)."""
    global _api_url_override
    _api_url_override = url.rstrip("/")


CONFIG_DIR: Path = Path.home() / ".config" / "dailybot"
CREDENTIALS_FILE: Path = CONFIG_DIR / "credentials.json"
CONFIG_FILE: Path = CONFIG_DIR / "config.json"
ORG_CACHE_FILE: Path = CONFIG_DIR / "org_cache.json"
AGENTS_FILE: Path = CONFIG_DIR / "agents.json"


def get_config_dir() -> Path:
    """Return the config directory, creating it if needed."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


def load_credentials() -> dict[str, Any] | None:
    """Load stored credentials from disk."""
    if not CREDENTIALS_FILE.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(CREDENTIALS_FILE.read_text())
        return data if data.get("token") else None
    except (json.JSONDecodeError, KeyError):
        return None


def save_credentials(
    token: str,
    email: str,
    organization: str,
    organization_uuid: str,
    api_url: str = DEFAULT_API_URL,
) -> None:
    """Save credentials to disk."""
    get_config_dir()
    CREDENTIALS_FILE.write_text(
        json.dumps(
            {
                "token": token,
                "email": email,
                "organization": organization,
                "organization_uuid": organization_uuid,
                "api_url": api_url,
            },
            indent=2,
        )
    )
    # Restrict file permissions (owner read/write only)
    os.chmod(CREDENTIALS_FILE, 0o600)


def clear_credentials() -> None:
    """Remove stored credentials."""
    if CREDENTIALS_FILE.exists():
        CREDENTIALS_FILE.unlink()


def get_api_url() -> str:
    """Return the API URL (--api-url flag > env var > credentials > default)."""
    if _api_url_override:
        return _api_url_override
    env_url: str | None = os.environ.get("DAILYBOT_API_URL")
    if env_url:
        return env_url.rstrip("/")
    creds: dict[str, Any] | None = load_credentials()
    if creds and creds.get("api_url"):
        return str(creds["api_url"]).rstrip("/")
    return DEFAULT_API_URL


def get_token() -> str | None:
    """Return the stored auth token, or the DAILYBOT_CLI_TOKEN env var."""
    env_token: str | None = os.environ.get("DAILYBOT_CLI_TOKEN")
    if env_token:
        return env_token
    creds: dict[str, Any] | None = load_credentials()
    if creds:
        return creds.get("token")
    return None


def load_config() -> dict[str, Any]:
    """Read config.json, return {} if missing."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, KeyError):
        return {}


def save_config(data: dict[str, Any]) -> None:
    """Merge *data* into existing config. Keys set to None are removed."""
    existing: dict[str, Any] = load_config()
    for key, value in data.items():
        if value is None:
            existing.pop(key, None)
        else:
            existing[key] = value
    get_config_dir()
    CONFIG_FILE.write_text(json.dumps(existing, indent=2))
    os.chmod(CONFIG_FILE, 0o600)


def get_api_key() -> str | None:
    """Return the org API key (env var > stored config > None)."""
    env_key: str | None = os.environ.get("DAILYBOT_API_KEY")
    if env_key:
        return env_key
    config: dict[str, Any] = load_config()
    return config.get("api_key") or None


def save_org_cache(email: str, organizations: list[dict[str, Any]]) -> None:
    """Cache the org list from request_code for UUID resolution in step 2."""
    get_config_dir()
    data: dict[str, Any] = {"email": email, "organizations": organizations}
    ORG_CACHE_FILE.write_text(json.dumps(data))


def load_org_cache(email: str) -> list[dict[str, Any]] | None:
    """Load cached org list for the given email. Returns None if missing or stale."""
    if not ORG_CACHE_FILE.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(ORG_CACHE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("email") != email:
        return None
    return data.get("organizations")


def clear_org_cache() -> None:
    """Remove the org cache file."""
    if ORG_CACHE_FILE.exists():
        ORG_CACHE_FILE.unlink()


def get_agent_auth() -> str | None:
    """Return the auth mode available for agent commands.

    Returns ``"api_key"`` if an API key is available (env or config),
    ``"bearer"`` if a login token exists, or ``None``.
    """
    if get_api_key():
        return "api_key"
    if get_token():
        return "bearer"
    return None


# --- Agent profiles ---


def _slugify(name: str) -> str:
    """Convert a display name to a simple slug for profile keys."""
    import re

    slug: str = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "default"


def load_agents() -> dict[str, Any]:
    """Read agents.json, return {} if missing."""
    if not AGENTS_FILE.exists():
        return {}
    try:
        return json.loads(AGENTS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_agents(data: dict[str, Any]) -> None:
    """Write agents.json with restricted permissions."""
    get_config_dir()
    AGENTS_FILE.write_text(json.dumps(data, indent=2))
    os.chmod(AGENTS_FILE, 0o600)


def save_agent_profile(
    profile_name: str,
    agent_name: str,
    api_key: str | None = None,
    agent_email: str | None = None,
) -> None:
    """Upsert an agent profile. Sets as default if no default exists."""
    data: dict[str, Any] = load_agents()
    profiles: dict[str, Any] = data.setdefault("profiles", {})
    entry: dict[str, str] = {"agent_name": agent_name}
    if api_key:
        entry["api_key"] = api_key
    if agent_email:
        entry["agent_email"] = agent_email
    profiles[profile_name] = entry
    if not data.get("default"):
        data["default"] = profile_name
    _save_agents(data)


def get_default_profile() -> dict[str, Any] | None:
    """Return the default profile dict with its name, or None."""
    data: dict[str, Any] = load_agents()
    default_name: str | None = data.get("default")
    if not default_name:
        return None
    profiles: dict[str, Any] = data.get("profiles", {})
    profile: dict[str, Any] | None = profiles.get(default_name)
    if not profile:
        return None
    return {"profile": default_name, **profile}


def get_profile(name: str) -> dict[str, Any] | None:
    """Return a specific profile dict, or None."""
    data: dict[str, Any] = load_agents()
    profiles: dict[str, Any] = data.get("profiles", {})
    profile: dict[str, Any] | None = profiles.get(name)
    if not profile:
        return None
    return {"profile": name, **profile}


def list_profiles() -> list[dict[str, Any]]:
    """Return all profiles as a list of dicts with metadata."""
    data: dict[str, Any] = load_agents()
    default_name: str | None = data.get("default")
    profiles: dict[str, Any] = data.get("profiles", {})
    result: list[dict[str, Any]] = []
    for name, entry in profiles.items():
        result.append(
            {
                "profile": name,
                "agent_name": entry.get("agent_name", ""),
                "agent_email": entry.get("agent_email", ""),
                "has_key": bool(entry.get("api_key")),
                "is_default": name == default_name,
            }
        )
    return result
