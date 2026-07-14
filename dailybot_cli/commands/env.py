"""Per-repo environment override commands (``dailybot env``).

The ``env`` command group manages ``.dailybot/env.json`` — the opt-in,
gitignored file that carries API keys + URLs for one or more environments
(live, local, staging, ...). One profile can be *active* at a time; when set,
it overrides ``DAILYBOT_API_KEY`` / ``config.json`` / the login Bearer session
for the enclosing repo.

Full docs (schema, precedence, security posture): ``docs/CONFIGURATION.md``
section "Repo-level env override".
"""

import subprocess
from pathlib import Path
from typing import Any

import click

from dailybot_cli.config import (
    REPO_ENV_FILENAME,
    REPO_PROFILE_DIRNAME,
    RepoEnvError,
    add_env_profile,
    find_repo_env_path,
    find_repo_root,
    get_active_env_profile,
    load_repo_env,
    remove_env_profile,
    set_active_env_profile,
    set_env_disabled,
)
from dailybot_cli.display import (
    console,
    print_env_profile,
    print_env_profiles_table,
    print_error,
    print_info,
    print_success,
    print_warning,
)


def _mask_key(value: str) -> str:
    """Mask everything after the first 4 characters (safe display)."""
    if not value:
        return "****"
    if len(value) <= 4:
        return value[0] + "****"
    return value[:4] + "****"


def _warn_if_env_json_not_gitignored(env_path: Path) -> None:
    """Best-effort warning when ``.dailybot/env.json`` is not gitignored.

    Fires only when git is installed AND the enclosing directory is a git
    repository AND the file is not currently ignored. If any of those
    prerequisites is missing, we stay silent — there's nothing to warn about.
    """
    import shutil

    if not shutil.which("git"):
        return
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(env_path.parent),
                "check-ignore",
                "--quiet",
                "--",
                env_path.name,
            ],
            capture_output=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return
    # exit 0 = ignored (safe), exit 1 = NOT ignored (unsafe),
    # exit 128 = not a git repo (nothing to warn about).
    if result.returncode == 1:
        print_warning(
            f"{env_path} is NOT gitignored. This file contains API keys and "
            "must never be committed. Add `.dailybot/*` (except "
            "`!.dailybot/profile.json`) to your .gitignore before committing."
        )


def _handle_env_error(exc: RepoEnvError) -> None:
    """Uniform error handling for ``env`` subcommands."""
    print_error(str(exc))
    raise SystemExit(1)


# --- Group ------------------------------------------------------------------


@click.group(name="env")
def env() -> None:
    """Manage per-repo API key overrides in ``.dailybot/env.json``.

    \b
    The file is opt-in and MUST be gitignored — it carries API keys for one
    or more environments (live, local, staging). One profile is *active* at
    a time; when set, it overrides DAILYBOT_API_KEY, config.json, and the
    login Bearer session for this repo.

    \b
    Common workflow:
      dailybot env add --name local --key sk_xxx --api-url http://localhost:8000
      dailybot env add --name staging --key sk_yyy --api-url https://staging-api.example.com
      dailybot env use staging      # switch active
      dailybot env show             # inspect current
      dailybot env off              # temporarily disable (preserves active)
      dailybot env on               # re-enable
      dailybot env list             # all configured profiles
      dailybot env remove staging   # delete a profile

    \b
    Precedence (highest wins):
      1. --api-url / --app-url / --profile CLI flags
      2. .dailybot/env.json active profile   <-- this file
      3. .dailybot/profile.json + agents.json
      4. DAILYBOT_API_KEY env var
      5. config.json (dailybot config key=...)
      6. Login session Bearer token

    Full docs: docs/CONFIGURATION.md § "Repo-level env override".
    """


# --- env add ----------------------------------------------------------------


@env.command(name="add")
@click.option("--name", "-n", required=True, help="Profile name (unique per env.json).")
@click.option("--key", "-k", required=True, help="API key for this environment.")
@click.option(
    "--api-url",
    "api_url",
    default=None,
    help="Optional API base URL for this profile (e.g. http://localhost:8000).",
)
@click.option(
    "--app-url",
    "app_url",
    default=None,
    help="Optional webapp/dashboard URL for this profile.",
)
def env_add(name: str, key: str, api_url: str | None, app_url: str | None) -> None:
    """Add a profile to ``.dailybot/env.json``, creating the file if needed.

    \b
    The first profile added is automatically set as active. Subsequent adds
    keep the current active profile — switch with `dailybot env use <name>`.

    \b
    Examples:
      dailybot env add --name local --key sk_local_xxx \\
        --api-url http://localhost:8000 --app-url http://localhost:8090
      dailybot env add --name live --key sk_live_yyy
    """
    try:
        path, became_active = add_env_profile(
            name=name, api_key=key, api_url=api_url, app_url=app_url
        )
    except RepoEnvError as exc:
        _handle_env_error(exc)
        return  # unreachable, for type checkers

    if became_active:
        print_success(f"Created {path} and added profile '{name}' (set as active).")
    else:
        print_success(f"Added profile '{name}' to {path}.")
        print_info(f"Active profile unchanged. Switch with: dailybot env use {name}")

    _warn_if_env_json_not_gitignored(path)


# --- env use ----------------------------------------------------------------


@env.command(name="use")
@click.argument("name", required=True)
def env_use(name: str) -> None:
    """Set the active profile in ``.dailybot/env.json``.

    \b
    Pass an empty string to clear the active profile (the file stays, but
    the CLI falls through to global auth):

      dailybot env use local
      dailybot env use ""       # clear active
    """
    try:
        target: str | None = name or None
        path: Path = set_active_env_profile(target)
    except RepoEnvError as exc:
        _handle_env_error(exc)
        return

    if target is None:
        print_success(f"Cleared active profile in {path}.")
        print_info("The CLI will now fall back to global auth (env var, config, or login).")
    else:
        print_success(f"Active profile is now '{target}' in {path}.")


# --- env show ---------------------------------------------------------------


@env.command(name="show")
def env_show() -> None:
    """Show the currently resolved env.json profile (API key masked)."""
    env_path: Path | None = find_repo_env_path()
    if not env_path:
        # Non-error: the file is optional. Point the user at the setup command.
        candidate: Path = find_repo_root() / REPO_PROFILE_DIRNAME / REPO_ENV_FILENAME
        print_info(f"No {candidate} found. Run `dailybot env add ...` to create one.")
        return

    try:
        data: dict[str, Any] | None = load_repo_env()
    except RepoEnvError as exc:
        _handle_env_error(exc)
        return

    if not data:
        print_warning(f"{env_path} is malformed. Fix or remove it.")
        return

    if data.get("disabled"):
        preserved: str = str(data.get("active") or "(none)")
        console.print(
            f"[bold yellow]env.json is disabled[/bold yellow] "
            f"(active would be: [dim]{preserved}[/dim])"
        )
        print_info(f"Path: {env_path}")
        print_info("Re-enable with: dailybot env on")
        return

    active_profile: dict[str, Any] | None = get_active_env_profile()
    if not active_profile:
        active_raw: str = str(data.get("active") or "")
        if active_raw:
            print_warning(
                f"active='{active_raw}' but no profile in {env_path} matches "
                f"that name. Set with: dailybot env use <name>"
            )
        else:
            print_info(f"{env_path} exists but has no active profile.")
            print_info("Choose one with: dailybot env use <name>")
        return

    print_env_profile(active_profile, env_path, _mask_key)


# --- env list ---------------------------------------------------------------


@env.command(name="list")
def env_list() -> None:
    """List every profile in ``.dailybot/env.json`` (active marked)."""
    env_path: Path | None = find_repo_env_path()
    if not env_path:
        print_info("No .dailybot/env.json found. Create one with `dailybot env add ...`.")
        return

    try:
        data: dict[str, Any] | None = load_repo_env()
    except RepoEnvError as exc:
        _handle_env_error(exc)
        return

    if not data:
        print_warning(f"{env_path} is malformed.")
        return

    profiles: list[dict[str, Any]] = data.get("profiles", [])
    if not profiles:
        print_info(f"{env_path} has no profiles. Add one with `dailybot env add ...`.")
        return

    print_env_profiles_table(
        profiles=profiles,
        active=data.get("active"),
        disabled=bool(data.get("disabled")),
        path=env_path,
        mask=_mask_key,
    )


# --- env remove -------------------------------------------------------------


@env.command(name="remove")
@click.argument("name", required=True)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip the interactive confirmation.",
)
def env_remove(name: str, yes: bool) -> None:
    """Remove a profile from ``.dailybot/env.json``.

    \b
    If the removed profile was the active one, the active pointer is cleared
    and the CLI falls back to global auth until you run `dailybot env use`.
    """
    if not yes and not click.confirm(f"Remove profile '{name}' from env.json?"):
        print_info("Cancelled.")
        return

    try:
        path, cleared = remove_env_profile(name)
    except RepoEnvError as exc:
        _handle_env_error(exc)
        return

    if cleared:
        print_success(f"Removed profile '{name}' from {path} (was active — active cleared).")
        print_info("The CLI will fall back to global auth until you run `dailybot env use`.")
    else:
        print_success(f"Removed profile '{name}' from {path}.")


# --- env off / on ----------------------------------------------------------


@env.command(name="off")
def env_off() -> None:
    """Disable ``.dailybot/env.json`` without deleting it (preserves active)."""
    try:
        path: Path = set_env_disabled(True)
    except RepoEnvError as exc:
        _handle_env_error(exc)
        return

    print_success(f"Disabled {path}. The CLI now uses global auth.")
    print_info("Re-enable with: dailybot env on")


@env.command(name="on")
def env_on() -> None:
    """Re-enable ``.dailybot/env.json`` (restores the previously active profile)."""
    try:
        path: Path = set_env_disabled(False)
    except RepoEnvError as exc:
        _handle_env_error(exc)
        return

    print_success(f"Enabled {path}.")
    active: dict[str, Any] | None = get_active_env_profile()
    if active:
        print_info(f"Active profile: {active['name']}")
    else:
        print_info("No active profile set. Choose one with: dailybot env use <name>")
