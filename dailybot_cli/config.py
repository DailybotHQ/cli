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


# --- Repo-level profile (.dailybot/profile.json) ---

REPO_PROFILE_DIRNAME: str = ".dailybot"
REPO_PROFILE_FILENAME: str = "profile.json"
_VALID_REPO_PROFILE_KEYS: frozenset[str] = frozenset({"name", "profile", "default_metadata"})
_REPO_PROFILE_PATH_KEY: str = "_path"

_warned_repo_paths: set[str] = set()
_warned_repo_missing_slugs: set[str] = set()


class RepoProfileError(Exception):
    """Raised when ``.dailybot/profile.json`` violates a hard rule (e.g. carries a key)."""


def reset_repo_profile_warnings() -> None:
    """Clear the per-process warning dedup sets. Useful in tests."""
    _warned_repo_paths.clear()
    _warned_repo_missing_slugs.clear()


def find_repo_profile_path(cwd: Path | None = None) -> Path | None:
    """Walk up from *cwd* to find the closest ``.dailybot/profile.json``.

    Returns ``None`` if no ancestor contains the file, if ``.dailybot`` exists
    along the path as a regular file rather than a directory, or if the file
    itself is missing or non-regular.
    """
    start: Path = (cwd or Path.cwd()).resolve()
    for ancestor in [start, *start.parents]:
        candidate_dir: Path = ancestor / REPO_PROFILE_DIRNAME
        if not candidate_dir.is_dir():
            continue
        profile_path: Path = candidate_dir / REPO_PROFILE_FILENAME
        if profile_path.is_file():
            return profile_path
    return None


def _warn_once(path_key: str, message: str) -> None:
    """Emit a warning once per *path_key* per process."""
    if path_key in _warned_repo_paths:
        return
    _warned_repo_paths.add(path_key)
    from dailybot_cli.display import print_warning

    print_warning(message)


def load_repo_profile(cwd: Path | None = None) -> dict[str, Any] | None:
    """Load and validate ``.dailybot/profile.json``.

    Returns the parsed dict (with the resolved file path stored under
    ``_path``) or ``None`` when no file is found, the file is malformed, or
    its top-level value is not a JSON object. Unknown top-level keys are
    dropped with a one-line warning. A ``key`` field always raises
    :class:`RepoProfileError` — credentials must never live in the repo file.
    """
    path: Path | None = find_repo_profile_path(cwd)
    if not path:
        return None

    try:
        raw: str = path.read_text()
        data: Any = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        _warn_once(
            f"parse:{path}",
            f"Could not parse {path}: {exc}. Falling back to global config.",
        )
        return None

    if not isinstance(data, dict):
        _warn_once(
            f"shape:{path}",
            f"{path} must contain a JSON object. Falling back to global config.",
        )
        return None

    if "key" in data:
        raise RepoProfileError(
            f"{path} contains a 'key' field. Credentials must never be committed to "
            "the repo. Remove the 'key' field; use a global profile, "
            "DAILYBOT_API_KEY, or 'dailybot login' instead."
        )

    unknown: set[str] = set(data.keys()) - _VALID_REPO_PROFILE_KEYS
    if unknown:
        _warn_once(
            f"unknown:{path}",
            f"{path} has unknown key(s) {sorted(unknown)}; ignoring (forward-compat).",
        )

    cleaned: dict[str, Any] = {k: data[k] for k in _VALID_REPO_PROFILE_KEYS if k in data}
    cleaned[_REPO_PROFILE_PATH_KEY] = str(path)
    return cleaned


def resolve_active_profile(
    profile_flag: str | None = None,
    name_flag: str | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Resolve the active agent profile across CLI flags, repo file, and global.

    Pure resolution — does not raise on missing global slugs (callers decide
    how to react). Raises :class:`RepoProfileError` when the repo file carries
    a ``key`` field.

    Returns a dict with:
      - ``agent_name``: resolved display name
      - ``api_key``: API key from the global profile, or ``None``
      - ``default_metadata``: merged repo-level default metadata (may be ``{}``)
      - ``global_profile``: the matched entry from ``agents.json`` or ``None``
      - ``profile_slug``: the slug actually used to look up the global entry
      - ``profile_missing_from_flag``: ``True`` if ``--profile`` did not resolve
      - ``profile_missing_from_repo``: ``True`` if repo's ``profile`` did not resolve
      - ``repo_profile_path``: path to the repo file, or ``None``
      - ``resolved_from``: provenance per field (``flag`` / ``repo`` / ``global`` / ``default``)
    """
    repo: dict[str, Any] = load_repo_profile(cwd) or {}
    repo_name: str | None = repo.get("name")
    repo_profile_slug: str | None = repo.get("profile")
    repo_default_metadata: dict[str, Any] = repo.get("default_metadata") or {}
    repo_path: str | None = repo.get(_REPO_PROFILE_PATH_KEY)

    profile_slug: str | None
    profile_source: str
    if profile_flag:
        profile_slug, profile_source = profile_flag, "flag"
    elif repo_profile_slug:
        profile_slug, profile_source = repo_profile_slug, "repo"
    else:
        profile_slug, profile_source = None, "default"

    profile_data: dict[str, Any] | None = None
    profile_missing_from_flag: bool = False
    profile_missing_from_repo: bool = False
    if profile_slug:
        profile_data = get_profile(profile_slug)
        if not profile_data:
            if profile_source == "flag":
                profile_missing_from_flag = True
            else:
                profile_missing_from_repo = True
                if profile_slug not in _warned_repo_missing_slugs:
                    _warned_repo_missing_slugs.add(profile_slug)
                    from dailybot_cli.display import print_warning

                    print_warning(
                        f"Profile '{profile_slug}' from {repo_path} not found in "
                        f"{AGENTS_FILE}. Using session credentials instead."
                    )
    else:
        profile_data = get_default_profile()

    name_source: str
    agent_name: str
    if name_flag:
        agent_name, name_source = name_flag, "flag"
    elif repo_name:
        agent_name, name_source = repo_name, "repo"
    elif profile_data and profile_data.get("agent_name"):
        agent_name, name_source = profile_data["agent_name"], "global"
    else:
        agent_name, name_source = "CLI Agent", "default"

    api_key: str | None = profile_data.get("api_key") if profile_data else None

    return {
        "agent_name": agent_name,
        "api_key": api_key,
        "default_metadata": repo_default_metadata,
        "global_profile": profile_data,
        "profile_slug": profile_slug,
        "profile_missing_from_flag": profile_missing_from_flag,
        "profile_missing_from_repo": profile_missing_from_repo,
        "repo_profile_path": repo_path,
        "resolved_from": {
            "agent_name": name_source,
            "profile": profile_source,
            "default_metadata": "repo" if repo_default_metadata else "absent",
        },
    }


def find_repo_root(start: Path | None = None) -> Path:
    """Return the git repo root containing *start*, or *start* itself.

    Used to anchor a freshly-written ``.dailybot/profile.json`` at the
    "natural" repo root rather than wherever the user happened to ``cd``.
    Falls back silently to the starting directory when there is no
    ``.git`` ancestor — the caller still gets a writable directory.
    """
    base: Path = (start or Path.cwd()).resolve()
    for ancestor in [base, *base.parents]:
        if (ancestor / ".git").exists():
            return ancestor
    return base


def write_repo_profile(
    payload: dict[str, Any],
    *,
    cwd: Path | None = None,
) -> Path:
    """Write or merge ``.dailybot/profile.json`` and return the file path.

    Merge semantics — keeps the file friendly to repeated runs from CI:
      - Top-level scalar keys (``name``, ``profile``) overwrite.
      - ``default_metadata`` is shallow-merged: incoming keys win, missing
        keys carry over from the existing file.
      - Keys outside the v1 schema in *payload* raise :class:`ValueError`
        (forward-compat warnings only apply to *reading*, not writing).
      - A ``key`` field always raises — credentials must never be
        committed; this mirrors the read-side guard in
        :func:`load_repo_profile`.

    The target directory is the git repo root containing *cwd*, or *cwd*
    itself if there is no ``.git`` ancestor.
    """
    if "key" in payload:
        raise RepoProfileError(
            "Refusing to write a 'key' field to .dailybot/profile.json — "
            "credentials must never be committed. Configure credentials with "
            "`dailybot login` or `dailybot agent configure --name ... --key ...` "
            "(global, written to ~/.config/dailybot/agents.json) instead."
        )
    unknown: set[str] = set(payload.keys()) - _VALID_REPO_PROFILE_KEYS
    if unknown:
        raise ValueError(
            f"Unknown repo-profile key(s): {sorted(unknown)}. "
            f"Allowed: {sorted(_VALID_REPO_PROFILE_KEYS)}."
        )

    repo_root: Path = find_repo_root(cwd)
    profile_dir: Path = repo_root / REPO_PROFILE_DIRNAME
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_path: Path = profile_dir / REPO_PROFILE_FILENAME

    existing: dict[str, Any] = {}
    if profile_path.is_file():
        try:
            raw: Any = json.loads(profile_path.read_text())
            if isinstance(raw, dict):
                existing = {k: raw[k] for k in _VALID_REPO_PROFILE_KEYS if k in raw}
        except (OSError, json.JSONDecodeError):
            # Corrupt or unreadable existing file → start fresh rather than
            # propagating an error the user can't act on.
            existing = {}

    merged: dict[str, Any] = dict(existing)
    for k, v in payload.items():
        if k == "default_metadata" and isinstance(v, dict):
            base_meta: dict[str, Any] = dict(existing.get("default_metadata") or {})
            base_meta.update(v)
            merged["default_metadata"] = base_meta
        else:
            merged[k] = v

    profile_path.write_text(json.dumps(merged, indent=2) + "\n")
    return profile_path
