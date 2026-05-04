"""Agent commands for Dailybot CLI (API key or login session)."""

import re
from pathlib import Path
from typing import Any

import click

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.config import (
    RepoProfileError,
    _slugify,
    find_repo_root,
    get_agent_auth,
    get_default_profile,
    get_profile,
    get_token,
    list_profiles,
    load_agents,
    load_repo_profile,
    resolve_active_profile,
    save_agent_profile,
    write_repo_profile,
)
from dailybot_cli.display import (
    console,
    print_agent_email_sent,
    print_agent_health,
    print_agent_message_sent,
    print_agent_messages,
    print_agent_profiles,
    print_error,
    print_info,
    print_pending_agent_messages,
    print_registration_result,
    print_resolved_profile,
    print_success,
    print_warning,
    print_webhook_result,
)

_NO_AUTH_MSG: str = (
    "No agent profile or authentication found. Use one of:\n"
    '  - dailybot agent configure --name "My Agent"\n'
    "  - DAILYBOT_API_KEY environment variable\n"
    "  - dailybot config key=<KEY>\n"
    "  - dailybot login"
)

# Sentinel for the first-run nudge (`agent update` with no profile configured).
# Module-level on purpose: persists across calls within a single CLI process,
# resets between processes — exactly what we want for a tip that should appear
# at most once per terminal invocation (and never in CI loops that batch many
# `agent update` calls in the same Python interpreter).
_FALLBACK_NAME: str = "CLI Agent"
_NUDGE_SHOWN: bool = False


def _maybe_show_init_nudge(agent_name: str) -> None:
    """Hint the user about `dailybot agent init` when their report is signed
    with the hardcoded fallback name. Shown at most once per process."""
    global _NUDGE_SHOWN
    if _NUDGE_SHOWN or agent_name != _FALLBACK_NAME:
        return
    _NUDGE_SHOWN = True
    print_info(
        f"Tip: this report was signed as '{_FALLBACK_NAME}'. Run `dailybot agent init` "
        "so future reports use your real name."
    )


def _reset_init_nudge() -> None:
    """Test-only hook to reset the per-process nudge flag."""
    global _NUDGE_SHOWN
    _NUDGE_SHOWN = False


# Challenge constants (from backend registration_challenge_service.py)
_CHALLENGE_WORD_COUNT: int = 52
_CHALLENGE_NUMBER_RE: re.Pattern[str] = re.compile(r"session is (\d+)\.")


def _resolve_agent_context(
    profile_flag: str | None,
    name_flag: str | None,
) -> tuple[str, DailyBotClient, dict[str, Any]]:
    """Resolve agent name and build a configured client.

    Resolution order (per-field, highest layer wins):
      1. CLI flags (``--name``, ``--profile``)
      2. Repo file ``.dailybot/profile.json`` (walk-up from cwd, closest wins)
      3. Global default profile from ``agents.json``
      4. Hardcoded fallback ``"CLI Agent"`` for the display name

    Returns ``(agent_name, client, default_metadata)`` — *default_metadata* is
    the repo file's ``default_metadata`` dict (``{}`` when absent), which the
    caller may shallow-merge into the outgoing report metadata.
    """
    try:
        repo: dict[str, Any] = load_repo_profile() or {}
    except RepoProfileError as exc:
        print_error(str(exc))
        raise SystemExit(1)

    repo_name: str | None = repo.get("name")
    repo_profile_slug: str | None = repo.get("profile")
    repo_default_metadata: dict[str, Any] = repo.get("default_metadata") or {}
    repo_path: str | None = repo.get("_path")

    selected_slug: str | None
    selected_from_flag: bool = bool(profile_flag)
    if profile_flag:
        selected_slug = profile_flag
    elif repo_profile_slug:
        selected_slug = repo_profile_slug
    else:
        selected_slug = None

    profile_data: dict[str, Any] | None = None
    if selected_slug:
        profile_data = get_profile(selected_slug)
        if not profile_data:
            if selected_from_flag:
                print_error(f"Profile '{selected_slug}' not found. Run: dailybot agent profiles")
                raise SystemExit(1)
            # Repo-declared slug missing in agents.json — warn once, fall back.
            print_warning(
                f"Profile '{selected_slug}' from {repo_path} not found in agents.json. "
                "Using session credentials instead."
            )
    elif not profile_flag:
        profile_data = get_default_profile()

    # Agent display name: --name > repo `name` > profile.agent_name > "CLI Agent"
    if name_flag:
        agent_name: str = name_flag
    elif repo_name:
        agent_name = repo_name
    elif profile_data and profile_data.get("agent_name"):
        agent_name = profile_data["agent_name"]
    else:
        agent_name = "CLI Agent"

    if profile_data:
        api_key: str | None = profile_data.get("api_key")
        if api_key:
            return agent_name, DailyBotClient(api_key=api_key), repo_default_metadata
        # Profile without key — fall through to Bearer token
        if get_token():
            return agent_name, DailyBotClient(), repo_default_metadata
        print_error(
            f"Profile '{profile_data['profile']}' has no API key and no login session.\n"
            "  Run: dailybot login  or  dailybot agent configure --name ... --key ..."
        )
        raise SystemExit(1)

    # No profile resolved — legacy fallback chain (env/config/login session).
    if not get_agent_auth():
        print_error(_NO_AUTH_MSG)
        raise SystemExit(1)

    return agent_name, DailyBotClient(), repo_default_metadata


def _merge_repo_metadata(
    inline: dict[str, Any] | None,
    default_metadata: dict[str, Any],
) -> dict[str, Any] | None:
    """Shallow-merge repo *default_metadata* under *inline* keys (inline wins)."""
    if not default_metadata:
        return inline
    merged: dict[str, Any] = {**default_metadata, **(inline or {})}
    return merged


# --- Agent group ---


@click.group()
@click.option(
    "--profile", "-p", default=None, help="Agent profile name from agents.json.", hidden=False
)
@click.pass_context
def agent(ctx: click.Context, profile: str | None) -> None:
    """Agent commands (requires API key or login session)."""
    ctx.ensure_object(dict)
    ctx.obj["profile"] = profile


# --- configure & profiles ---


def _parse_metadata_pairs(pairs: tuple[str, ...]) -> dict[str, str]:
    """Parse repeatable ``--metadata key=value`` flags into a dict."""
    result: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            print_error(
                f"Invalid --metadata value '{pair}'. Expected key=value (e.g. team=platform)."
            )
            raise SystemExit(1)
        key, _, value = pair.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            print_error(f"Invalid --metadata value '{pair}'. Key must be non-empty.")
            raise SystemExit(1)
        result[key] = value
    return result


@agent.command(name="configure")
@click.option("--name", "-n", default=None, help="Agent display name.")
@click.option("--key", "-k", default=None, help="API key (optional — omit if using OTP login).")
@click.option(
    "--profile", "profile_name", default=None, help="Profile name (defaults to slugified --name)."
)
@click.option(
    "--repo",
    "repo_mode",
    is_flag=True,
    default=False,
    help="Write to the repo's .dailybot/profile.json instead of the global agents.json.",
)
@click.option(
    "--metadata",
    "-d",
    "metadata_pairs",
    multiple=True,
    help="Default metadata as key=value (repeatable). Only valid with --repo.",
)
@click.pass_context
def agent_configure(
    ctx: click.Context,
    name: str | None,
    key: str | None,
    profile_name: str | None,
    repo_mode: bool,
    metadata_pairs: tuple[str, ...],
) -> None:
    """Configure a named agent profile (global or repo-level).

    \b
    Global (saved to ~/.config/dailybot/agents.json):
      dailybot agent configure --name "Claude Code"
      dailybot agent configure --name "CI Bot" --key abc123
      dailybot agent configure --name "Claude Code" --profile claude

    \b
    Repo-level (writes/merges <repo>/.dailybot/profile.json — committed to git
    so every contributor signs reports under the same identity):
      dailybot agent configure --repo --name "Core Hub Bot"
      dailybot agent configure --repo --name "Core Hub Bot" \\
        --metadata team=platform --metadata service=core-hub
      dailybot agent configure --repo --profile core-hub-bot
    """
    if repo_mode:
        _agent_configure_repo(
            name=name, profile_name=profile_name, key=key, metadata_pairs=metadata_pairs
        )
        return

    if metadata_pairs:
        print_error("--metadata is only valid with --repo.")
        raise SystemExit(1)
    if not name:
        print_error("--name is required (use --repo for repo-level config).")
        raise SystemExit(1)

    slug: str = profile_name or _slugify(name)

    if key:
        # Validate the key
        client: DailyBotClient = DailyBotClient(api_key=key)
        try:
            with console.status("Validating API key..."):
                client.get_agent_health(agent_name=name)
        except APIError as e:
            if e.status_code in (401, 403):
                print_error("API key is invalid or unauthorized.")
                raise SystemExit(1)
            # Non-auth error means the key itself is valid
    else:
        if not get_token():
            print_error(
                "No API key provided and no login session found.\n"
                "  Run: dailybot login  or  provide --key"
            )
            raise SystemExit(1)
        print_info("No API key provided — agent commands will use your login session for auth.")

    save_agent_profile(slug, agent_name=name, api_key=key)
    print_success(f"Agent profile '{slug}' configured. This is now your default agent.")


def _agent_configure_repo(
    *,
    name: str | None,
    profile_name: str | None,
    key: str | None,
    metadata_pairs: tuple[str, ...],
) -> None:
    """Implement `dailybot agent configure --repo`. Writes .dailybot/profile.json."""
    if key:
        print_error(
            "--key cannot be combined with --repo. Repo-level profiles never carry "
            "credentials (they are committed to git). Configure credentials globally "
            "with `dailybot agent configure --name ... --key ...` instead."
        )
        raise SystemExit(1)

    payload: dict[str, Any] = {}
    if name:
        payload["name"] = name
    if profile_name:
        payload["profile"] = profile_name
    if metadata_pairs:
        payload["default_metadata"] = _parse_metadata_pairs(metadata_pairs)

    if not payload:
        print_error("Nothing to write. Pass at least one of --name, --profile, or --metadata.")
        raise SystemExit(1)

    try:
        path: Path = write_repo_profile(payload)
    except RepoProfileError as exc:
        print_error(str(exc))
        raise SystemExit(1)
    except ValueError as exc:
        print_error(str(exc))
        raise SystemExit(1)

    print_success(f"Wrote {path}")
    print_info(
        "Commit this file so every contributor running `dailybot agent ...` from "
        "the repo signs with the same identity."
    )


# --- agent init ---


_INIT_CHOICE_PERSONAL: str = (
    "Personal profile (this machine only — saves to ~/.config/dailybot/agents.json)"
)
_INIT_CHOICE_REPO: str = (
    "Repo profile (writes .dailybot/profile.json — committed to git, shared by every contributor)"
)
_INIT_CHOICE_BOTH: str = "Both"
_INIT_CHOICES: list[str] = [_INIT_CHOICE_PERSONAL, _INIT_CHOICE_REPO, _INIT_CHOICE_BOTH]

_AUTH_CHOICE_LOGIN: str = "Use my login session (recommended for humans)"
_AUTH_CHOICE_KEY: str = "Paste an API key (recommended for CI / dedicated agents)"
_AUTH_CHOICES: list[str] = [_AUTH_CHOICE_LOGIN, _AUTH_CHOICE_KEY]


@agent.command(name="init")
def agent_init() -> None:
    """Interactive wizard — set up your agent profile in under a minute.

    \b
    Walks you through both kinds of profile:
      - Personal (this machine):      ~/.config/dailybot/agents.json
      - Repo-shared (committed):      <repo>/.dailybot/profile.json

    \b
    For non-interactive setup (CI / scripts), use the underlying commands
    directly:
      dailybot agent configure --name "..."           # personal
      dailybot agent configure --repo --name "..."    # repo-level
    """
    import questionary

    console.print()
    console.print("[bold cyan]Dailybot agent setup[/bold cyan]")
    console.print("[dim]This wizard configures who your reports get signed as.[/dim]")
    console.print()

    choice: str | None = questionary.select(
        "What do you want to set up?",
        choices=_INIT_CHOICES,
    ).ask()
    if choice is None:
        print_info("Aborted.")
        return

    setup_personal: bool = choice in (_INIT_CHOICE_PERSONAL, _INIT_CHOICE_BOTH)
    setup_repo: bool = choice in (_INIT_CHOICE_REPO, _INIT_CHOICE_BOTH)

    if setup_personal:
        _init_personal(questionary)
    if setup_repo:
        _init_repo(questionary, defer_login_check=setup_personal)

    console.print()
    print_info("Verify the result with: dailybot agent profiles --resolve")


def _init_personal(questionary: Any) -> None:
    """Wizard step: configure a global profile in ~/.config/dailybot/agents.json."""
    name: str | None = questionary.text(
        "Your agent display name (e.g. 'Sergio Florez', 'Claude Code', 'CI Bot'):",
        validate=lambda v: bool(v.strip()) or "Name is required.",
    ).ask()
    if not name:
        print_info("Aborted.")
        return
    name = name.strip()

    auth_choice: str | None = questionary.select(
        "How will this profile authenticate?",
        choices=_AUTH_CHOICES,
    ).ask()
    if auth_choice is None:
        print_info("Aborted.")
        return

    api_key: str | None = None
    if auth_choice == _AUTH_CHOICE_KEY:
        api_key = questionary.password(
            "Paste your API key:",
            validate=lambda v: bool(v.strip()) or "API key is required.",
        ).ask()
        if not api_key:
            print_info("Aborted.")
            return
        api_key = api_key.strip()
    elif not get_token():
        print_warning(
            "No login session found. Run `dailybot login` first, or rerun this "
            "wizard and choose 'Paste an API key'."
        )
        return

    if api_key:
        # Validate before saving.
        client: DailyBotClient = DailyBotClient(api_key=api_key)
        try:
            with console.status("Validating API key..."):
                client.get_agent_health(agent_name=name)
        except APIError as exc:
            if exc.status_code in (401, 403):
                print_error("API key is invalid or unauthorized. Nothing was saved.")
                raise SystemExit(1)
            # Non-auth error → key is valid; the failure is unrelated.

    slug: str = _slugify(name)
    save_agent_profile(slug, agent_name=name, api_key=api_key)
    print_success(f"Saved global profile '{slug}' (set as default).")


def _init_repo(questionary: Any, *, defer_login_check: bool) -> None:
    """Wizard step: write/merge .dailybot/profile.json."""
    repo_root: Path = find_repo_root()
    console.print()
    console.print(f"[dim]Writing under: {repo_root / '.dailybot'}/[/dim]")

    name: str | None = questionary.text(
        "Display name for this repo (leave empty to inherit the personal profile):",
    ).ask()
    if name is None:  # Ctrl-C
        print_info("Aborted.")
        return
    name = name.strip()

    metadata_raw: str | None = questionary.text(
        "Default metadata as 'key=value, key=value' (optional, press Enter to skip):",
    ).ask()
    if metadata_raw is None:
        print_info("Aborted.")
        return

    metadata: dict[str, str] = {}
    if metadata_raw.strip():
        try:
            pairs: tuple[str, ...] = tuple(p.strip() for p in metadata_raw.split(",") if p.strip())
            metadata = _parse_metadata_pairs(pairs)
        except SystemExit:
            # _parse_metadata_pairs already printed; surface and bail cleanly.
            return

    payload: dict[str, Any] = {}
    if name:
        payload["name"] = name
    if metadata:
        payload["default_metadata"] = metadata

    if not payload:
        print_warning(
            "Nothing to write — both 'name' and 'default_metadata' were empty. Skipping repo profile."
        )
        return

    try:
        path: Path = write_repo_profile(payload, cwd=repo_root)
    except (RepoProfileError, ValueError) as exc:
        print_error(str(exc))
        return

    print_success(f"Wrote {path}")
    print_info("Commit this file so every contributor signs reports the same way.")

    # Soft-warn if the user picked "Repo only" without any auth — the file alone
    # does not authenticate; the user still needs login or an API key.
    if not defer_login_check and not get_agent_auth():
        print_warning(
            "You don't have any credentials configured yet. The repo file pins "
            "*how* reports are signed, but you still need to authenticate with "
            "`dailybot login` (or set DAILYBOT_API_KEY) before sending one."
        )


@agent.command(name="profiles")
@click.option(
    "--resolve",
    "show_resolved",
    is_flag=True,
    default=False,
    help="Show the resolved active profile (CLI > .dailybot/profile.json > global).",
)
@click.pass_context
def agent_profiles(ctx: click.Context, show_resolved: bool) -> None:
    """List all configured agent profiles.

    \b
      dailybot agent profiles
      dailybot agent profiles --resolve
    """
    if show_resolved:
        profile_flag: str | None = ctx.obj.get("profile") if ctx.obj else None
        try:
            resolved: dict[str, Any] = resolve_active_profile(profile_flag, None)
        except RepoProfileError as exc:
            print_error(str(exc))
            raise SystemExit(1)
        print_resolved_profile(resolved)
        return

    profiles: list[dict[str, Any]] = list_profiles()
    # Add masked keys for display
    data: dict[str, Any] = load_agents()
    all_profiles: dict[str, Any] = data.get("profiles", {})
    for p in profiles:
        raw_key: str | None = all_profiles.get(p["profile"], {}).get("api_key")
        if raw_key:
            p["masked_key"] = raw_key[:4] + "****" if len(raw_key) > 4 else "****"
    print_agent_profiles(profiles)


# --- agent update ---


@agent.command(name="update")
@click.argument("content")
@click.option("--name", "-n", default=None, help="Agent worker name.")
@click.option("--profile", "-p", default=None, help="Agent profile name from agents.json.")
@click.option("--json-data", "-j", help="Structured JSON data to include.")
@click.option("--metadata", "-d", help="JSON metadata (e.g. repo, branch, PR).")
@click.option(
    "--milestone", "-m", is_flag=True, default=False, help="Mark as a milestone accomplishment."
)
@click.option(
    "--co-authors",
    "-c",
    multiple=True,
    help="Co-author email or UUID (repeatable, or comma-separated).",
)
@click.pass_context
def agent_update(
    ctx: click.Context,
    content: str,
    name: str | None,
    profile: str | None,
    json_data: str | None,
    metadata: str | None,
    milestone: bool,
    co_authors: tuple[str, ...],
) -> None:
    """Submit an agent activity report.

    \b
      dailybot agent update "Deployed v2.1 to staging"
      dailybot agent update "Built feature X" --name "Claude Code"
      dailybot agent update "Deployed" --profile ci-bot
    """
    profile_flag: str | None = profile or ctx.obj.get("profile")
    agent_name, client, repo_default_metadata = _resolve_agent_context(profile_flag, name)

    import json as json_mod

    structured: dict[str, Any] | None = None
    if json_data:
        try:
            structured = json_mod.loads(json_data)
        except json_mod.JSONDecodeError:
            print_error("Invalid JSON in --json-data.")
            raise SystemExit(1)

    metadata_dict: dict[str, Any] | None = None
    if metadata:
        try:
            metadata_dict = json_mod.loads(metadata)
        except json_mod.JSONDecodeError:
            print_error("Invalid JSON in --metadata.")
            raise SystemExit(1)

    metadata_dict = _merge_repo_metadata(metadata_dict, repo_default_metadata)

    # Flatten comma-separated co-authors
    co_author_list: list[str] = []
    for val in co_authors:
        for part in val.split(","):
            stripped: str = part.strip()
            if stripped:
                co_author_list.append(stripped)

    try:
        with console.status("Submitting agent report..."):
            result: dict[str, Any] = client.submit_agent_report(
                agent_name=agent_name,
                content=content,
                structured=structured,
                metadata=metadata_dict,
                is_milestone=milestone,
                co_authors=co_author_list or None,
            )
        msg: str = f"Report submitted (id: {result.get('id', 'N/A')})"
        if result.get("is_milestone"):
            msg += " [Milestone]"
        co: list[dict[str, Any]] | None = result.get("co_authors")
        if co:
            names: str = ", ".join(a.get("name", a.get("uuid", "?")) for a in co)
            msg += f"\n  Co-authors: {names}"
        print_success(msg)
        pending: list[dict[str, Any]] = result.get("pending_messages", [])
        if pending:
            print_pending_agent_messages(pending)
        _maybe_show_init_nudge(agent_name)
    except APIError as e:
        print_error(e.detail)
        raise SystemExit(1)


# --- agent health ---


@agent.command(name="health")
@click.option("--ok", "report_ok", is_flag=True, default=False, help="Report healthy status.")
@click.option("--fail", "report_fail", is_flag=True, default=False, help="Report unhealthy status.")
@click.option(
    "--status", "query_status", is_flag=True, default=False, help="Query current health status."
)
@click.option("--message", "-m", default=None, help="Optional message to include.")
@click.option("--name", "-n", default=None, help="Agent worker name.")
@click.option("--profile", "-p", default=None, help="Agent profile name from agents.json.")
@click.pass_context
def agent_health(
    ctx: click.Context,
    report_ok: bool,
    report_fail: bool,
    query_status: bool,
    message: str | None,
    name: str | None,
    profile: str | None,
) -> None:
    """Report or query agent health status.

    \b
      dailybot agent health --ok --message "All good"
      dailybot agent health --fail --message "DB unreachable"
      dailybot agent health --status --name "Claude Code"
    """
    flags: int = sum([report_ok, report_fail, query_status])
    if flags != 1:
        print_error("Specify exactly one of --ok, --fail, or --status.")
        raise SystemExit(1)

    profile_flag: str | None = profile or ctx.obj.get("profile")
    agent_name, client, _ = _resolve_agent_context(profile_flag, name)

    try:
        if query_status:
            with console.status("Fetching agent health..."):
                result: dict[str, Any] = client.get_agent_health(agent_name=agent_name)
            print_agent_health(result)
        else:
            with console.status("Submitting agent health..."):
                result = client.submit_agent_health(
                    agent_name=agent_name,
                    ok=report_ok,
                    message=message,
                )
            print_agent_health(result)
    except APIError as e:
        print_error(e.detail)
        raise SystemExit(1)


# --- Webhook subcommand group ---


@agent.group(name="webhook")
def agent_webhook() -> None:
    """Manage agent webhooks."""
    pass


@agent_webhook.command(name="register")
@click.option("--url", required=True, help="Webhook URL to receive POST requests.")
@click.option("--secret", default=None, help="Secret sent as X-Webhook-Secret header.")
@click.option("--name", "-n", default=None, help="Agent worker name.")
@click.option("--profile", "-p", default=None, help="Agent profile name from agents.json.")
@click.pass_context
def webhook_register(
    ctx: click.Context, url: str, secret: str | None, name: str | None, profile: str | None
) -> None:
    """Register a webhook for the agent.

    \b
      dailybot agent webhook register --url https://my-server.com/hook
      dailybot agent webhook register --url https://... --secret my-token
    """
    profile_flag: str | None = profile or ctx.obj.get("profile")
    agent_name, client, _ = _resolve_agent_context(profile_flag, name)

    try:
        with console.status("Registering webhook..."):
            result: dict[str, Any] = client.register_agent_webhook(
                agent_name=agent_name,
                webhook_url=url,
                webhook_secret=secret,
            )
        print_webhook_result(result)
    except APIError as e:
        print_error(e.detail)
        raise SystemExit(1)


@agent_webhook.command(name="unregister")
@click.option("--name", "-n", default=None, help="Agent worker name.")
@click.option("--profile", "-p", default=None, help="Agent profile name from agents.json.")
@click.pass_context
def webhook_unregister(ctx: click.Context, name: str | None, profile: str | None) -> None:
    """Unregister the agent's webhook.

    \b
      dailybot agent webhook unregister
      dailybot agent webhook unregister --name "Claude Code"
    """
    profile_flag: str | None = profile or ctx.obj.get("profile")
    agent_name, client, _ = _resolve_agent_context(profile_flag, name)

    try:
        with console.status("Unregistering webhook..."):
            result: dict[str, Any] = client.unregister_agent_webhook(agent_name=agent_name)
        print_success(result.get("detail", "Webhook unregistered."))
    except APIError as e:
        print_error(e.detail)
        raise SystemExit(1)


# --- Message subcommand group ---


@agent.group(name="message")
def agent_message() -> None:
    """Send, list, and claim agent messages."""
    pass


@agent_message.command(name="send")
@click.option("--to", "to_agent", required=True, help="Target agent name.")
@click.option("--content", required=True, help="Message content.")
@click.option(
    "--type", "message_type", default=None, help="Message type: text, command, or system."
)
@click.option("--name", "-n", default=None, help="Sender agent name.")
@click.option("--profile", "-p", default=None, help="Agent profile name from agents.json.")
@click.option("--json-data", "-j", default=None, help="JSON metadata to include.")
@click.option("--expires-at", default=None, help="ISO 8601 expiration timestamp.")
@click.pass_context
def message_send(
    ctx: click.Context,
    to_agent: str,
    content: str,
    message_type: str | None,
    name: str | None,
    profile: str | None,
    json_data: str | None,
    expires_at: str | None,
) -> None:
    """Send a message to an agent.

    \b
      dailybot agent message send --to "Claude Code" --content "Review PR #42"
      dailybot agent message send --to "Claude Code" --content "Do X" --type command
    """
    profile_flag: str | None = profile or ctx.obj.get("profile")
    agent_name, client, _ = _resolve_agent_context(profile_flag, name)

    metadata: dict[str, Any] | None = None
    if json_data:
        import json

        try:
            metadata = json.loads(json_data)
        except json.JSONDecodeError:
            print_error("Invalid JSON in --json-data.")
            raise SystemExit(1)

    try:
        with console.status("Sending message..."):
            result: dict[str, Any] = client.send_agent_message(
                agent_name=to_agent,
                content=content,
                message_type=message_type,
                metadata=metadata,
                expires_at=expires_at,
                sender_type="agent",
                sender_name=agent_name,
            )
        print_agent_message_sent(result)
    except APIError as e:
        print_error(e.detail)
        raise SystemExit(1)


@agent_message.command(name="list")
@click.option("--name", "-n", default=None, help="Agent name to list messages for.")
@click.option("--profile", "-p", default=None, help="Agent profile name from agents.json.")
@click.option("--pending", is_flag=True, default=False, help="Show only undelivered messages.")
@click.pass_context
def message_list(ctx: click.Context, name: str | None, profile: str | None, pending: bool) -> None:
    """List messages for an agent.

    \b
      dailybot agent message list --name "Claude Code"
      dailybot agent message list --pending
    """
    profile_flag: str | None = profile or ctx.obj.get("profile")
    agent_name, client, _ = _resolve_agent_context(profile_flag, name)

    delivered: bool | None = False if pending else None
    try:
        with console.status("Fetching messages..."):
            messages: list[dict[str, Any]] = client.get_agent_messages(
                agent_name=agent_name,
                delivered=delivered,
            )
        print_agent_messages(messages)
    except APIError as e:
        print_error(e.detail)
        raise SystemExit(1)


@agent_message.command(name="claim")
@click.argument("message_ids", nargs=-1, required=True)
@click.option("--profile", "-p", default=None, help="Agent profile name from agents.json.")
@click.pass_context
def message_claim(ctx: click.Context, message_ids: tuple[str, ...], profile: str | None) -> None:
    """Mark one or more messages as read.

    \b
      dailybot agent message claim abc-123
      dailybot agent message claim abc-123 def-456
    """
    profile_flag: str | None = profile or ctx.obj.get("profile")
    _agent_name, client, _ = _resolve_agent_context(profile_flag, None)

    try:
        with console.status("Marking messages as read..."):
            result: dict[str, Any] = client.mark_agent_messages_read(
                message_ids=list(message_ids),
            )
        count: int = result.get("updated", 0)
        print_success(f"Marked {count} message(s) as read.")
    except APIError as e:
        print_error(e.detail)
        raise SystemExit(1)


@agent_message.command(name="claim-all")
@click.option("--name", "-n", default=None, help="Agent worker name.")
@click.option("--profile", "-p", default=None, help="Agent profile name from agents.json.")
@click.pass_context
def message_claim_all(ctx: click.Context, name: str | None, profile: str | None) -> None:
    """Mark all pending messages as delivered via health check.

    \b
      dailybot agent message claim-all
      dailybot agent message claim-all --name "Claude Code"
    """
    profile_flag: str | None = profile or ctx.obj.get("profile")
    agent_name, client, _ = _resolve_agent_context(profile_flag, name)

    try:
        with console.status("Marking all messages as delivered..."):
            client.submit_agent_health(
                agent_name=agent_name,
                ok=True,
                message=None,
            )
        print_success("All pending messages marked as delivered.")
    except APIError as e:
        print_error(e.detail)
        raise SystemExit(1)


# --- Email subcommand group ---


@agent.group(name="email")
def agent_email() -> None:
    """Send emails through an agent."""
    pass


@agent_email.command(name="send")
@click.option(
    "--to", "recipients", multiple=True, required=True, help="Recipient email (repeatable)."
)
@click.option("--subject", required=True, help="Email subject line.")
@click.option("--body-html", required=True, help="HTML email body.")
@click.option("--name", "-n", default=None, help="Agent name.")
@click.option("--profile", "-p", default=None, help="Agent profile name from agents.json.")
@click.option("--metadata", "-d", default=None, help="JSON metadata to include.")
@click.pass_context
def email_send(
    ctx: click.Context,
    recipients: tuple[str, ...],
    subject: str,
    body_html: str,
    name: str | None,
    profile: str | None,
    metadata: str | None,
) -> None:
    """Send an email through an agent.

    \b
      dailybot agent email send --to user@example.com --subject "Build passed" \\
        --body-html "<p>All green.</p>" --name "Claude Code"
      dailybot agent email send --to a@co.com --to b@co.com --subject "Report" \\
        --body-html "<h1>Done</h1>"
    """
    profile_flag: str | None = profile or ctx.obj.get("profile")
    agent_name, client, repo_default_metadata = _resolve_agent_context(profile_flag, name)

    to_list: list[str] = list(recipients)

    metadata_dict: dict[str, Any] | None = None
    if metadata:
        import json

        try:
            metadata_dict = json.loads(metadata)
        except json.JSONDecodeError:
            print_error("Invalid JSON in --metadata.")
            raise SystemExit(1)

    metadata_dict = _merge_repo_metadata(metadata_dict, repo_default_metadata)

    try:
        with console.status("Sending email..."):
            result: dict[str, Any] = client.send_agent_email(
                agent_name=agent_name,
                to=to_list,
                subject=subject,
                body_html=body_html,
                metadata=metadata_dict,
            )
        print_agent_email_sent(result)
    except APIError as e:
        if e.status_code == 429:
            print_error("Hourly email limit exceeded. Try again later.")
            print_info(e.detail)
        else:
            print_error(e.detail)
        raise SystemExit(1)


# --- Agent register ---


def _solve_challenge(instruction: str) -> int:
    """Extract random_number from challenge instruction and compute the answer."""
    match: re.Match[str] | None = _CHALLENGE_NUMBER_RE.search(instruction)
    if not match:
        print_error("Could not parse challenge. Please report this issue.")
        raise SystemExit(1)
    random_number: int = int(match.group(1))
    return random_number * _CHALLENGE_WORD_COUNT


@agent.command(name="register")
@click.option("--org-name", required=True, help="Organization name to create.")
@click.option("--agent-name", required=True, help="Agent display name.")
@click.option("--email", default=None, help="Human contact email (optional).")
@click.option("--timezone", default="UTC", help="Timezone (default: UTC).")
@click.option(
    "--profile",
    "profile_name",
    default=None,
    help="Profile name to save (defaults to slugified --agent-name).",
)
def agent_register(
    org_name: str,
    agent_name: str,
    email: str | None,
    timezone: str,
    profile_name: str | None,
) -> None:
    """Register a new agent and organization (no existing account needed).

    \b
      dailybot agent register --org-name "My Startup" --agent-name "Claude Code"
      dailybot agent register --org-name "My Startup" --agent-name "Claude Code" --email me@co.com
    """
    client: DailyBotClient = DailyBotClient()
    slug: str = profile_name or _slugify(agent_name)
    reason: str = f"Agent '{agent_name}' registering for org '{org_name}'"

    def _attempt_register() -> dict[str, Any]:
        with console.status("Getting registration challenge..."):
            challenge: dict[str, Any] = client.get_registration_challenge()
        answer: int = _solve_challenge(challenge["instruction"])
        with console.status("Registering agent..."):
            return client.register_agent(
                challenge_id=challenge["challenge_id"],
                answer=answer,
                reason=reason,
                org_name=org_name,
                agent_name=agent_name,
                contact_email=email,
                timezone=timezone,
            )

    try:
        result: dict[str, Any] = _attempt_register()
    except APIError as e:
        if "expired" in e.detail.lower():
            # Auto-retry once with a fresh challenge
            try:
                result = _attempt_register()
            except APIError as retry_e:
                print_error(retry_e.detail)
                raise SystemExit(1)
        elif e.status_code == 429:
            print_error("Rate limited. Try again in a few minutes.")
            raise SystemExit(1)
        else:
            print_error(e.detail)
            raise SystemExit(1)

    # Save profile
    api_key: str | None = result.get("api_key")
    agent_email: str | None = result.get("agent_email")
    save_agent_profile(slug, agent_name=agent_name, api_key=api_key, agent_email=agent_email)

    # Display result
    result["profile"] = slug
    print_registration_result(result)
    claim_url: str = result.get("claim_url", "")
    if claim_url:
        print_info(
            "Share the claim URL with your team admin to connect this org to Slack or Google Chat. The URL expires in 30 days."
        )
