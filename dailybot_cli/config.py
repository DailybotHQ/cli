"""Credential and configuration management for Dailybot CLI."""

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_API_URL: str = "https://api.dailybot.com"
DEFAULT_APP_URL: str = "https://app.dailybot.com"
_api_url_override: str | None = None
_app_url_override: str | None = None


def set_api_url_override(url: str) -> None:
    """Set a CLI-level API URL override (from --api-url flag)."""
    global _api_url_override
    _api_url_override = url.rstrip("/")


def set_app_url_override(url: str) -> None:
    """Set a CLI-level webapp URL override (from --app-url flag)."""
    global _app_url_override
    _app_url_override = url.rstrip("/")


CONFIG_DIR: Path = Path.home() / ".config" / "dailybot"
CREDENTIALS_FILE: Path = CONFIG_DIR / "credentials.json"
CONFIG_FILE: Path = CONFIG_DIR / "config.json"
ORG_CACHE_FILE: Path = CONFIG_DIR / "org_cache.json"
AGENTS_FILE: Path = CONFIG_DIR / "agents.json"


def get_config_dir() -> Path:
    """Return the config directory, creating it if needed.

    Honors ``DAILYBOT_CONFIG_DIR`` when set (e.g. clitest sandboxes). Otherwise
    uses the module-level ``CONFIG_DIR`` (``~/.config/dailybot/``).
    """
    env_override: str | None = os.environ.get("DAILYBOT_CONFIG_DIR")
    path: Path = Path(env_override) if env_override else CONFIG_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _credentials_path() -> Path:
    return get_config_dir() / "credentials.json"


def _config_path() -> Path:
    return get_config_dir() / "config.json"


def _org_cache_path() -> Path:
    return get_config_dir() / "org_cache.json"


def _agents_path() -> Path:
    return get_config_dir() / "agents.json"


def load_credentials() -> dict[str, Any] | None:
    """Load stored credentials from disk."""
    creds_path: Path = _credentials_path()
    if not creds_path.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(creds_path.read_text())
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
    creds_path: Path = _credentials_path()
    get_config_dir()
    creds_path.write_text(
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
    os.chmod(creds_path, 0o600)


def clear_credentials() -> None:
    """Remove stored credentials."""
    creds_path: Path = _credentials_path()
    if creds_path.exists():
        creds_path.unlink()


def get_api_url() -> str:
    """Return the API URL.

    Resolution order (highest layer wins):
      1. ``--api-url`` flag (via :func:`set_api_url_override`)
      2. ``.dailybot/env.json`` active profile's ``api_url`` (walk-up from cwd)
      3. ``DAILYBOT_API_URL`` env var
      4. ``credentials.json::api_url`` (login session's stored URL)
      5. :data:`DEFAULT_API_URL`

    Errors reading env.json are swallowed here (they surface at the CLI
    entry point). This keeps the plumbing side of things resilient.
    """
    if _api_url_override:
        return _api_url_override
    env_profile: dict[str, Any] | None = _safe_active_env_profile()
    if env_profile and env_profile.get("api_url"):
        return str(env_profile["api_url"]).rstrip("/")
    env_url: str | None = os.environ.get("DAILYBOT_API_URL")
    if env_url:
        return env_url.rstrip("/")
    creds: dict[str, Any] | None = load_credentials()
    if creds and creds.get("api_url"):
        return str(creds["api_url"]).rstrip("/")
    return DEFAULT_API_URL


def get_app_url() -> str:
    """Return the webapp URL.

    Resolution order (highest layer wins):
      1. ``--app-url`` flag (via :func:`set_app_url_override`)
      2. ``.dailybot/env.json`` active profile's ``app_url``
      3. ``DAILYBOT_APP_URL`` env var
      4. :data:`DEFAULT_APP_URL`
    """
    if _app_url_override:
        return _app_url_override
    env_profile: dict[str, Any] | None = _safe_active_env_profile()
    if env_profile and env_profile.get("app_url"):
        return str(env_profile["app_url"]).rstrip("/")
    env_url: str | None = os.environ.get("DAILYBOT_APP_URL")
    if env_url:
        return env_url.rstrip("/")
    return DEFAULT_APP_URL


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
    config_path: Path = _config_path()
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text())
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
    config_path: Path = _config_path()
    config_path.write_text(json.dumps(existing, indent=2))
    os.chmod(config_path, 0o600)


def get_api_key() -> str | None:
    """Return the org API key.

    Resolution order (highest layer wins):
      1. ``.dailybot/env.json`` active profile's ``api_key`` (walk-up from cwd)
      2. ``DAILYBOT_API_KEY`` env var
      3. ``config.json::api_key`` (set via ``dailybot config key=...``)
      4. ``None``

    Errors reading env.json are swallowed here so plumbing stays resilient;
    the CLI entry point calls :func:`load_repo_env` explicitly to surface
    fatal misconfigurations (e.g. env.json tracked in git).
    """
    env_profile: dict[str, Any] | None = _safe_active_env_profile()
    if env_profile and env_profile.get("api_key"):
        return str(env_profile["api_key"])
    env_key: str | None = os.environ.get("DAILYBOT_API_KEY")
    if env_key:
        return env_key
    config: dict[str, Any] = load_config()
    return config.get("api_key") or None


def _safe_active_env_profile() -> dict[str, Any] | None:
    """Return the active env.json profile, swallowing any error.

    ``get_api_key`` / ``get_api_url`` / ``get_app_url`` call this on every
    invocation; they must never raise. The CLI entry point calls
    :func:`load_repo_env` directly at startup so fatal errors (e.g. env.json
    tracked in git) still surface loudly — this helper is the resilient
    plumbing-side accessor.
    """
    try:
        return get_active_env_profile()
    except RepoEnvError:
        return None
    except Exception:
        return None


def save_org_cache(email: str, organizations: list[dict[str, Any]]) -> None:
    """Cache the org list from request_code for UUID resolution in step 2."""
    get_config_dir()
    data: dict[str, Any] = {"email": email, "organizations": organizations}
    _org_cache_path().write_text(json.dumps(data))


def load_org_cache(email: str) -> list[dict[str, Any]] | None:
    """Load cached org list for the given email. Returns None if missing or stale."""
    cache_path: Path = _org_cache_path()
    if not cache_path.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("email") != email:
        return None
    return data.get("organizations")


def clear_org_cache() -> None:
    """Remove the org cache file."""
    cache_path: Path = _org_cache_path()
    if cache_path.exists():
        cache_path.unlink()


def _plan_cache_path() -> Path:
    return get_config_dir() / "plan_cache.json"


def save_org_plan(organization_uuid: str, plan: str | None) -> None:
    """Persist the (non-sensitive) plan tier for an org, keyed by org UUID.

    Stored in ``plan_cache.json`` (mode ``0o600``). ``plan=None`` removes the
    entry (back to "unknown"). Never stores tokens or any secret material — only
    the plan-tier string. A malformed existing file is treated as empty.
    """
    if not organization_uuid:
        return
    cache_path: Path = _plan_cache_path()
    data: dict[str, Any] = {}
    if cache_path.exists():
        try:
            loaded: Any = json.loads(cache_path.read_text())
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            data = {}
    if plan is None:
        data.pop(organization_uuid, None)
    else:
        data[organization_uuid] = plan
    cache_path.write_text(json.dumps(data, indent=2))
    os.chmod(cache_path, 0o600)


def get_org_plan(organization_uuid: str | None) -> str | None:
    """Return the cached plan tier for an org UUID, or None if unknown.

    Absent file / unknown org / malformed cache all resolve to ``None``
    (unknown) so callers never assume a plan the server hasn't confirmed.
    """
    if not organization_uuid:
        return None
    cache_path: Path = _plan_cache_path()
    if not cache_path.exists():
        return None
    try:
        data: Any = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    value: Any = data.get(organization_uuid)
    return value if isinstance(value, str) else None


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
    agents_path: Path = _agents_path()
    if not agents_path.exists():
        return {}
    try:
        return json.loads(agents_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_agents(data: dict[str, Any]) -> None:
    """Write agents.json with restricted permissions."""
    get_config_dir()
    agents_path: Path = _agents_path()
    agents_path.write_text(json.dumps(data, indent=2))
    os.chmod(agents_path, 0o600)


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
_VALID_REPO_PROFILE_KEYS: frozenset[str] = frozenset(
    {"name", "profile", "default_metadata", "vars", "report"}
)
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
                        f"{_agents_path()}. Using session credentials instead."
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
    api_key_source: str = "global" if api_key else "absent"

    # env.json takes precedence over the global agent profile for credentials.
    # We surface it so `agent profiles --resolve` shows the full picture.
    env_profile: dict[str, Any] | None = None
    env_profile_error: str | None = None
    if not profile_flag:
        try:
            env_profile = get_active_env_profile(cwd)
        except RepoEnvError as exc:
            env_profile_error = str(exc)
    if env_profile and env_profile.get("api_key"):
        api_key = str(env_profile["api_key"])
        api_key_source = "env.json"

    env_api_url: str | None = (
        str(env_profile["api_url"]).rstrip("/")
        if env_profile and env_profile.get("api_url")
        else None
    )
    env_app_url: str | None = (
        str(env_profile["app_url"]).rstrip("/")
        if env_profile and env_profile.get("app_url")
        else None
    )

    return {
        "agent_name": agent_name,
        "api_key": api_key,
        "default_metadata": repo_default_metadata,
        "global_profile": profile_data,
        "profile_slug": profile_slug,
        "profile_missing_from_flag": profile_missing_from_flag,
        "profile_missing_from_repo": profile_missing_from_repo,
        "repo_profile_path": repo_path,
        "env_profile_name": env_profile.get("name") if env_profile else None,
        "env_profile_api_url": env_api_url,
        "env_profile_app_url": env_app_url,
        "env_profile_error": env_profile_error,
        "resolved_from": {
            "agent_name": name_source,
            "profile": profile_source,
            "api_key": api_key_source,
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


# --- Repo-level env override (.dailybot/env.json) ---
#
# Optional per-repo file that carries API keys + URLs for one or more
# environments (live, local, staging, ...). One profile can be "active" at
# a time; when set, it overrides env vars, config.json, and the login
# Bearer session for that repo. The file is opt-in and MUST NEVER be
# committed to git — the load path enforces this with a fatal guard.
#
# Full schema:
#
#   {
#     "disabled": false,           # optional; true = ignore this file entirely
#     "active": "local org 1",     # optional; empty/null/missing = inert
#     "profiles": [
#       {
#         "name": "live",
#         "api_key": "xxxxxxx"
#       },
#       {
#         "name": "local org 1",
#         "api_key": "xxxxxxx",
#         "api_url": "http://localhost:8000",   # optional
#         "app_url": "http://localhost:8090"    # optional
#       }
#     ]
#   }
#
# See docs/CONFIGURATION.md for the full precedence table and
# docs/SECURITY.md for the security posture.

REPO_ENV_FILENAME: str = "env.json"
_VALID_REPO_ENV_TOP_KEYS: frozenset[str] = frozenset({"active", "disabled", "profiles"})
_VALID_REPO_ENV_PROFILE_KEYS: frozenset[str] = frozenset({"name", "api_key", "api_url", "app_url"})
_REQUIRED_REPO_ENV_PROFILE_KEYS: frozenset[str] = frozenset({"name", "api_key"})
_GIT_CHECK_TIMEOUT_SECS: float = 5.0

_warned_env_paths: set[str] = set()


class RepoEnvError(Exception):
    """Raised when ``.dailybot/env.json`` violates a hard rule.

    Currently only one hard rule: the file must not be tracked by git.
    Write-side validation errors (missing required keys, duplicate names,
    unknown keys) also raise this so callers get a single exception type
    to catch.
    """


def reset_repo_env_warnings() -> None:
    """Clear the per-process warning dedup set. Useful in tests."""
    _warned_env_paths.clear()


def find_repo_env_path(cwd: Path | None = None) -> Path | None:
    """Walk up from *cwd* to find the closest ``.dailybot/env.json``.

    Returns ``None`` when no ancestor contains the file, or when the file is
    non-regular. Mirrors the semantics of :func:`find_repo_profile_path`.
    """
    start: Path = (cwd or Path.cwd()).resolve()
    for ancestor in [start, *start.parents]:
        candidate_dir: Path = ancestor / REPO_PROFILE_DIRNAME
        if not candidate_dir.is_dir():
            continue
        env_path: Path = candidate_dir / REPO_ENV_FILENAME
        if env_path.is_file():
            return env_path
    return None


def _is_env_tracked_by_git(env_path: Path) -> bool:
    """Return ``True`` iff ``env_path`` is tracked by its containing git repo.

    Returns ``False`` when:
      - git is not installed on PATH,
      - the file is not inside a git repository,
      - the file is inside a git repo but is properly untracked
        (``.gitignore`` covers it, or it was never ``git add``ed).

    Only ``True`` is a security violation. Kept as a top-level function so
    tests can patch it without needing a real git repo.
    """
    import shutil
    import subprocess

    if not shutil.which("git"):
        return False

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(env_path.parent),
                "ls-files",
                "--error-unmatch",
                "--",
                env_path.name,
            ],
            capture_output=True,
            timeout=_GIT_CHECK_TIMEOUT_SECS,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _warn_env_once(path_key: str, message: str) -> None:
    """Emit a warning once per *path_key* per process."""
    if path_key in _warned_env_paths:
        return
    _warned_env_paths.add(path_key)
    from dailybot_cli.display import print_warning

    print_warning(message)


def load_repo_env(cwd: Path | None = None) -> dict[str, Any] | None:
    """Load and validate ``.dailybot/env.json``.

    Returns the parsed dict augmented with ``disabled`` (bool) and ``_path``
    (str), or ``None`` when the file is absent or malformed. Raises
    :class:`RepoEnvError` when the file is tracked by git — that is a hard
    security violation and the CLI refuses to operate until it's fixed.

    On the first successful load in a process, the file's permissions are
    tightened to ``0o600`` defensively (in case it was created via an editor
    or ``cp`` that used the default umask).
    """
    path: Path | None = find_repo_env_path(cwd)
    if not path:
        return None

    if _is_env_tracked_by_git(path):
        try:
            rel_path: str = str(path.relative_to(Path.cwd()))
        except ValueError:
            rel_path = str(path)
        raise RepoEnvError(
            f"{path} is tracked by git. This file contains API keys and must "
            "never be committed. Fix with:\n"
            f"  git rm --cached {rel_path}\n"
            "  # ensure your .gitignore ignores .dailybot/env.json\n"
            "  git commit -m 'chore: untrack .dailybot/env.json'\n"
            "The CLI refuses to load env.json while it is tracked."
        )

    # Defensive chmod — an editor or `cp` may have created the file with the
    # default umask (typically 0o644). Bring it back to owner-only quietly.
    import contextlib

    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)

    try:
        raw: str = path.read_text()
        data: Any = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        _warn_env_once(
            f"parse:{path}",
            f"Could not parse {path}: {exc}. Falling back to global auth.",
        )
        return None

    if not isinstance(data, dict):
        _warn_env_once(
            f"shape:{path}",
            f"{path} must contain a JSON object. Falling back to global auth.",
        )
        return None

    unknown_top: set[str] = set(data.keys()) - _VALID_REPO_ENV_TOP_KEYS
    if unknown_top:
        _warn_env_once(
            f"unknown-top:{path}",
            f"{path} has unknown top-level key(s) {sorted(unknown_top)}; ignoring.",
        )

    profiles_raw: Any = data.get("profiles")
    if not isinstance(profiles_raw, list):
        _warn_env_once(
            f"profiles-shape:{path}",
            f"{path} 'profiles' must be a list. Falling back to global auth.",
        )
        return None

    profiles: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for i, entry in enumerate(profiles_raw):
        if not isinstance(entry, dict):
            _warn_env_once(
                f"entry-shape:{path}:{i}",
                f"{path} profiles[{i}] must be an object; skipping.",
            )
            continue
        missing: frozenset[str] = _REQUIRED_REPO_ENV_PROFILE_KEYS - set(entry.keys())
        if missing:
            _warn_env_once(
                f"entry-required:{path}:{i}",
                f"{path} profiles[{i}] missing required key(s) {sorted(missing)}; skipping.",
            )
            continue
        unknown_profile: set[str] = set(entry.keys()) - _VALID_REPO_ENV_PROFILE_KEYS
        if unknown_profile:
            _warn_env_once(
                f"unknown-profile:{path}:{i}",
                f"{path} profiles[{i}] has unknown key(s) {sorted(unknown_profile)}; ignoring.",
            )
        cleaned: dict[str, Any] = {k: entry[k] for k in _VALID_REPO_ENV_PROFILE_KEYS if k in entry}
        name: str = cleaned["name"]
        if name in seen_names:
            _warn_env_once(
                f"entry-duplicate:{path}:{i}",
                f"{path} profiles[{i}] duplicate name '{name}'; keeping the first.",
            )
            continue
        seen_names.add(name)
        profiles.append(cleaned)

    active_raw: Any = data.get("active")
    active: str | None = active_raw if isinstance(active_raw, str) and active_raw else None

    disabled_raw: Any = data.get("disabled", False)
    disabled: bool = bool(disabled_raw) if isinstance(disabled_raw, bool) else False

    return {
        "active": active,
        "disabled": disabled,
        "profiles": profiles,
        "_path": str(path),
    }


def get_active_env_profile(cwd: Path | None = None) -> dict[str, Any] | None:
    """Return the active profile from ``.dailybot/env.json``, or ``None``.

    Returns ``None`` when:
      - the env.json file does not exist,
      - the file has ``disabled: true``,
      - the file has no ``active`` field (or it's empty/null),
      - ``active`` points at a name that does not exist in ``profiles``.

    Raises :class:`RepoEnvError` when the file is tracked by git (fatal).
    """
    data: dict[str, Any] | None = load_repo_env(cwd)
    if not data:
        return None
    if data.get("disabled"):
        return None
    active_name: str | None = data.get("active")
    if not active_name:
        return None
    for profile in data["profiles"]:
        if profile.get("name") == active_name:
            return profile
    return None


def _validate_env_payload(payload: dict[str, Any]) -> None:
    """Raise :class:`RepoEnvError` if the payload cannot be safely written."""
    unknown_top: set[str] = set(payload.keys()) - _VALID_REPO_ENV_TOP_KEYS
    if unknown_top:
        raise RepoEnvError(
            f"Unknown top-level key(s): {sorted(unknown_top)}. "
            f"Allowed: {sorted(_VALID_REPO_ENV_TOP_KEYS)}."
        )

    profiles: Any = payload.get("profiles", [])
    if not isinstance(profiles, list):
        raise RepoEnvError("'profiles' must be a list.")

    seen_names: set[str] = set()
    for i, entry in enumerate(profiles):
        if not isinstance(entry, dict):
            raise RepoEnvError(f"profiles[{i}] must be an object.")
        missing: frozenset[str] = _REQUIRED_REPO_ENV_PROFILE_KEYS - set(entry.keys())
        if missing:
            raise RepoEnvError(f"profiles[{i}] missing required key(s) {sorted(missing)}.")
        unknown: set[str] = set(entry.keys()) - _VALID_REPO_ENV_PROFILE_KEYS
        if unknown:
            raise RepoEnvError(
                f"profiles[{i}] has unknown key(s) {sorted(unknown)}. "
                f"Allowed: {sorted(_VALID_REPO_ENV_PROFILE_KEYS)}."
            )
        name: Any = entry["name"]
        if not isinstance(name, str) or not name.strip():
            raise RepoEnvError(f"profiles[{i}]['name'] must be a non-empty string.")
        if name in seen_names:
            raise RepoEnvError(f"Duplicate profile name '{name}'.")
        seen_names.add(name)

    active: Any = payload.get("active")
    if active is not None and active != "":
        if not isinstance(active, str):
            raise RepoEnvError("'active' must be a string.")
        if active not in seen_names:
            raise RepoEnvError(f"'active' points to '{active}' but no profile has that name.")

    disabled: Any = payload.get("disabled")
    if disabled is not None and not isinstance(disabled, bool):
        raise RepoEnvError("'disabled' must be a boolean.")


def save_repo_env(payload: dict[str, Any], *, cwd: Path | None = None) -> Path:
    """Write ``.dailybot/env.json`` at the repo root and return the path.

    Validates *payload* via :func:`_validate_env_payload` before writing.
    Anchors at the git repo root (``find_repo_root``) so the file lives at
    a stable location regardless of where the caller ran from. Always sets
    mode ``0o600`` per the credential-hygiene rules in AGENTS.md.
    """
    _validate_env_payload(payload)

    repo_root: Path = find_repo_root(cwd)
    env_dir: Path = repo_root / REPO_PROFILE_DIRNAME
    env_dir.mkdir(parents=True, exist_ok=True)
    env_path: Path = env_dir / REPO_ENV_FILENAME
    env_path.write_text(json.dumps(_normalize_env_payload(payload), indent=2) + "\n")
    os.chmod(env_path, 0o600)
    return env_path


def _normalize_env_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a payload with keys in stable order for reproducible writes.

    The on-disk order is intentional so a diff between two writes stays
    minimal (helps humans spot real changes when the file is inspected).
    """
    ordered: dict[str, Any] = {}
    if payload.get("disabled"):
        ordered["disabled"] = True
    active: Any = payload.get("active")
    if active is not None and active != "":
        ordered["active"] = active
    else:
        # Explicit null keeps the intent visible (developer can flip it back
        # with an editor if the CLI is unavailable).
        ordered["active"] = None
    profiles: list[dict[str, Any]] = payload.get("profiles", []) or []
    ordered["profiles"] = [_normalize_env_entry(p) for p in profiles]
    return ordered


def _normalize_env_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a profile entry with a canonical key order."""
    out: dict[str, Any] = {"name": entry["name"], "api_key": entry["api_key"]}
    if entry.get("api_url"):
        out["api_url"] = str(entry["api_url"]).rstrip("/")
    if entry.get("app_url"):
        out["app_url"] = str(entry["app_url"]).rstrip("/")
    return out


def _read_or_init_env(cwd: Path | None) -> dict[str, Any]:
    """Return the existing env.json as an editable dict, or a fresh skeleton."""
    path: Path | None = find_repo_env_path(cwd)
    if not path:
        return {"active": None, "disabled": False, "profiles": []}
    data: dict[str, Any] | None = load_repo_env(cwd)
    if not data:
        return {"active": None, "disabled": False, "profiles": []}
    return {
        "active": data.get("active"),
        "disabled": bool(data.get("disabled")),
        "profiles": [dict(p) for p in data.get("profiles", [])],
    }


def add_env_profile(
    name: str,
    api_key: str,
    api_url: str | None = None,
    app_url: str | None = None,
    *,
    cwd: Path | None = None,
) -> tuple[Path, bool]:
    """Add a profile to ``.dailybot/env.json``, creating the file if needed.

    Returns ``(path, became_active)``. When the file did not previously
    exist (or had no active profile), the new profile is auto-set as active
    and ``became_active`` is ``True``.
    """
    data: dict[str, Any] = _read_or_init_env(cwd)
    profiles: list[dict[str, Any]] = data["profiles"]

    if any(p.get("name") == name for p in profiles):
        raise RepoEnvError(
            f"A profile named '{name}' already exists in .dailybot/env.json. "
            "Use `dailybot env remove` first, or pick a different name."
        )

    entry: dict[str, Any] = {"name": name, "api_key": api_key}
    if api_url:
        entry["api_url"] = api_url.rstrip("/")
    if app_url:
        entry["app_url"] = app_url.rstrip("/")
    profiles.append(entry)

    became_active: bool = False
    if not data.get("active"):
        data["active"] = name
        became_active = True

    path: Path = save_repo_env(
        {
            "disabled": bool(data.get("disabled")),
            "active": data.get("active"),
            "profiles": profiles,
        },
        cwd=cwd,
    )
    return path, became_active


def remove_env_profile(name: str, *, cwd: Path | None = None) -> tuple[Path, bool]:
    """Remove a profile from ``.dailybot/env.json``.

    Returns ``(path, cleared_active)`` where ``cleared_active`` is ``True``
    when the removed profile was the currently active one. Raises
    :class:`RepoEnvError` if the file does not exist or the profile is not
    present.
    """
    path: Path | None = find_repo_env_path(cwd)
    if not path:
        raise RepoEnvError("No .dailybot/env.json found in the current directory or its ancestors.")
    data: dict[str, Any] | None = load_repo_env(cwd)
    if not data:
        raise RepoEnvError(f"{path} is malformed; cannot remove profile.")

    if not any(p.get("name") == name for p in data["profiles"]):
        raise RepoEnvError(f"No profile named '{name}' in {path}.")

    new_profiles: list[dict[str, Any]] = [
        dict(p) for p in data["profiles"] if p.get("name") != name
    ]
    active: str | None = data.get("active")
    cleared_active: bool = False
    if active == name:
        active = None
        cleared_active = True

    save_path: Path = save_repo_env(
        {
            "disabled": bool(data.get("disabled")),
            "active": active,
            "profiles": new_profiles,
        },
        cwd=cwd,
    )
    return save_path, cleared_active


def set_active_env_profile(name: str | None, *, cwd: Path | None = None) -> Path:
    """Set (or clear) the active profile in ``.dailybot/env.json``.

    ``name=None`` clears the active profile (the file stays, but the CLI
    falls through to global auth). Raises :class:`RepoEnvError` if the
    file does not exist or *name* does not match any known profile.
    """
    path: Path | None = find_repo_env_path(cwd)
    if not path:
        raise RepoEnvError("No .dailybot/env.json found. Run `dailybot env add ...` first.")
    data: dict[str, Any] | None = load_repo_env(cwd)
    if not data:
        raise RepoEnvError(f"{path} is malformed; cannot set active profile.")
    if name is not None and not any(p.get("name") == name for p in data["profiles"]):
        available: str = ", ".join(sorted(str(p["name"]) for p in data["profiles"])) or "(none)"
        raise RepoEnvError(f"No profile named '{name}' in {path}. Available: {available}")
    return save_repo_env(
        {
            "disabled": bool(data.get("disabled")),
            "active": name,
            "profiles": [dict(p) for p in data["profiles"]],
        },
        cwd=cwd,
    )


def set_env_disabled(disabled: bool, *, cwd: Path | None = None) -> Path:
    """Toggle the ``disabled`` kill-switch in ``.dailybot/env.json``.

    Preserves the ``active`` selection so that turning the file back on
    restores the previously chosen profile. Raises :class:`RepoEnvError`
    when the file does not exist.
    """
    path: Path | None = find_repo_env_path(cwd)
    if not path:
        raise RepoEnvError("No .dailybot/env.json found. Run `dailybot env add ...` first.")
    data: dict[str, Any] | None = load_repo_env(cwd)
    if not data:
        raise RepoEnvError(f"{path} is malformed; cannot toggle disabled state.")
    return save_repo_env(
        {
            "disabled": bool(disabled),
            "active": data.get("active"),
            "profiles": [dict(p) for p in data["profiles"]],
        },
        cwd=cwd,
    )
