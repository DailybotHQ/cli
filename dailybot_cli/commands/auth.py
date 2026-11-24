"""Authentication commands for Dailybot CLI."""

import os
import re
from typing import Any, NoReturn

import click
import questionary

from dailybot_cli import __version__
from dailybot_cli.api_client import AUTH_BACKEND_UNAVAILABLE_CODE, APIError, DailyBotClient
from dailybot_cli.commands import _device_login
from dailybot_cli.commands.public_api_helpers import (
    ERROR_CODE_MESSAGES,
    EXIT_RATE_LIMITED,
    exit_for_api_error,
    retry_after_seconds,
)
from dailybot_cli.config import (
    RepoEnvError,
    clear_credentials,
    clear_org_cache,
    get_active_env_profile,
    get_api_key,
    get_api_url,
    get_refresh_token_for,
    get_token,
    is_access_token_expired,
    load_credentials,
    load_org_cache,
    login_token_origin_url,
    save_credentials,
    save_org_cache,
    save_org_plan,
)
from dailybot_cli.display import (
    console,
    plain_text,
    print_cli_auth_deprecation,
    print_error,
    print_info,
    print_sign_in_refusal,
    print_success,
    print_warning,
)

CLI_AUTH_DEPRECATED_CODE: str = "cli_auth_deprecated"
HTTP_TOO_MANY_REQUESTS: int = 429
# Shown in the next-step hints instead of the code itself, so it never reaches
# scrollback, logs or a transcript.
CODE_PLACEHOLDER: str = "CODE"
LOGIN_RATE_LIMITED_FALLBACK: str = "Too many sign-in requests for this email right now."
_LEADING_DIGITS: re.Pattern[str] = re.compile(r"^(\d+)")

# One notice per `dailybot login` run, even when two doors both carry the field.
_deprecation_noticed: bool = False


def _version_parts(version: str) -> tuple[int, ...] | None:
    """``"3.29.0rc1"`` → ``(3, 29, 0)``; ``None`` when the first part is not numeric."""
    parts: list[int] = []
    for segment in version.strip().split("."):
        match: re.Match[str] | None = _LEADING_DIGITS.match(segment)
        if match is None:
            break
        parts.append(int(match.group(1)))
    return tuple(parts) if parts else None


def is_version_below(current: str, minimum: str) -> bool:
    """Whether ``current`` is older than ``minimum``; ``False`` when either is unreadable."""
    have: tuple[int, ...] | None = _version_parts(current)
    need: tuple[int, ...] | None = _version_parts(minimum)
    if have is None or need is None:
        return False
    width: int = max(len(have), len(need))
    return have + (0,) * (width - len(have)) < need + (0,) * (width - len(need))


def _notice_deprecation(body: dict[str, Any] | None) -> None:
    """Show the `cli_auth_deprecated` notice once, if the body (or error extra) carries it."""
    global _deprecation_noticed
    deprecation: Any = (body or {}).get("deprecation")
    if _deprecation_noticed or not isinstance(deprecation, dict):
        return
    if deprecation.get("code") != CLI_AUTH_DEPRECATED_CODE:
        return
    minimum: str = str(deprecation.get("min_version") or "")
    print_cli_auth_deprecation(
        sunset=str(deprecation.get("sunset") or ""),
        upgrade_to=minimum if minimum and is_version_below(__version__, minimum) else None,
    )
    _deprecation_noticed = True


def _warn_if_env_json_redirects_login() -> None:
    """Warn when an active ``.dailybot/env.json`` profile redirects the login.

    Login writes the resolved ``api_url`` (and the token issued by that
    server) to the GLOBAL ``~/.config/dailybot/credentials.json`` — a
    repo-local env.json must never rewrite the user's global session
    silently. The login still proceeds; the developer just gets told
    where it is going and how to opt out.
    """
    try:
        env_profile: dict[str, Any] | None = get_active_env_profile()
    except RepoEnvError:
        # The root cli() guard already aborted on fatal states; stay quiet.
        return
    if (
        env_profile
        and env_profile.get("api_url")
        and get_api_url() == str(env_profile["api_url"]).rstrip("/")
    ):
        print_warning(
            f"This repo's .dailybot/env.json (profile '{env_profile['name']}') points "
            f"the CLI at {get_api_url()}. Logging in will authenticate against that "
            "server and update your GLOBAL session for every repo. Run `dailybot env "
            "off` first if you meant to log into your default server."
        )


STANDALONE_ORG_HINT: str = " (Dailybot)"


def org_choice_label(org: dict[str, Any]) -> str:
    """An org's name in a picker, marking a standalone Dailybot organization.

    The frozen marker is ``standalone: true`` (W2), never ``platform == "dailybot"``
    alone: agent organizations are ``dailybot`` too and are not standalone. It tells
    apart a Slack workspace and the standalone organization that share a name.
    """
    name: str = str(org.get("name", "Unknown"))
    return f"{name}{STANDALONE_ORG_HINT}" if org.get("standalone") is True else name


def _prompt_org_selection_numbered(organizations: list[dict[str, Any]]) -> dict[str, Any]:
    """Numbered org picker — fallback when questionary TUI is unavailable."""
    print_info("You belong to multiple organizations. Select one by number:")
    for index, org in enumerate(organizations, start=1):
        org_name: str = org_choice_label(org)
        org_uuid: str = org.get("uuid", "")
        click.echo(f"  {index}. {org_name} (uuid: {org_uuid})")

    while True:
        choice: int = click.prompt("Organization number", type=int)
        if 1 <= choice <= len(organizations):
            return organizations[choice - 1]
        print_error(f"Enter a number between 1 and {len(organizations)}.")


def _prompt_org_selection(organizations: list[dict[str, Any]]) -> dict[str, Any]:
    """Display orgs and prompt the user to pick one."""
    choices: list[questionary.Choice] = [
        questionary.Choice(title=org_choice_label(org), value=org) for org in organizations
    ]
    selected: dict[str, Any] | None = questionary.select(
        "You belong to multiple organizations. Select one:",
        choices=choices,
    ).ask()
    if selected is not None:
        return selected

    # questionary returns None when cancelled or when the TUI cannot render
    # (common after click.prompt in some terminals) — fall back to numbered input.
    return _prompt_org_selection_numbered(organizations)


def _print_org_list(organizations: list[dict[str, Any]]) -> None:
    """Print organizations with UUIDs and names for non-interactive use."""
    print_info("You belong to multiple organizations. Use --org=UUID to select one:")
    for org in organizations:
        org_uuid: str = org.get("uuid", "")
        org_name: str = org.get("name", "Unknown")
        click.echo(f"  {org_name} (uuid: {org_uuid})")


def _resolve_org_uuid(organizations: list[dict[str, Any]], org_uuid: str) -> int | None:
    """Find the integer ID for an org given its UUID."""
    for org in organizations:
        if org.get("uuid") == org_uuid:
            return org["id"]
    return None


def _exit_for_login_door_error(error: APIError) -> NoReturn:
    """Render a refusal from the email-code doors and exit; never retried here.

    A 429 (too many requests for this email, or a cooldown between codes) shows the
    server's sentence and the wait, and exits with the rate-limit status, so it is
    never mistaken for a wrong code. Anything else keeps the long-standing output.
    """
    if error.status_code == HTTP_TOO_MANY_REQUESTS:
        fallback: str = ERROR_CODE_MESSAGES.get(error.code or "") or LOGIN_RATE_LIMITED_FALLBACK
        print_sign_in_refusal(error.detail.strip() or fallback, retry_after_seconds(error))
        _notice_deprecation(error.extra)
        raise SystemExit(EXIT_RATE_LIMITED)
    print_error(error.detail)
    _notice_deprecation(error.extra)
    raise SystemExit(1)


def _print_code_requested(email: str, request_result: dict[str, Any]) -> None:
    """Confirm the code request with the server's own sentence when it sends one."""
    detail: Any = request_result.get("detail")
    if isinstance(detail, str) and detail.strip():
        print_success(plain_text(detail))
    else:
        print_success(f"Verification code sent to {email}")
    print_info("Check your inbox (including spam folder).")


def _org_rerun_hint(email: str) -> None:
    """How to finish a non-interactive sign-in with an organization (code not repeated)."""
    print_info(f"Run: dailybot login --email={email} --code={CODE_PLACEHOLDER} --org=ORG_UUID")


def _verify_and_save(
    client: DailyBotClient,
    email: str,
    code: str,
    organization_id: int | None = None,
    *,
    organization_uuid: str | None = None,
    allow_interactive_org_pick: bool = False,
    picked: bool = False,
) -> None:
    """Verify the code, choose the organization if the server asks, save credentials.

    The organization always comes from verify-code's ``requires_organization_selection``
    answer (the code is not spent by that answer; the pick is a second call with the
    same code). ``picked`` marks that second call, so a repeated selection answer
    stops instead of looping.
    """
    org_kwargs: dict[str, Any] = {"organization_id": organization_id}
    if organization_uuid is not None:
        org_kwargs["organization_uuid"] = organization_uuid
    try:
        with console.status("Verifying code..."):
            result: dict[str, Any] = client.verify_code(email, code, **org_kwargs)
    except APIError as e:
        _exit_for_login_door_error(e)
    _notice_deprecation(result)

    if result.get("requires_organization_selection"):
        raw_orgs: Any = result.get("organizations")
        organizations: list[dict[str, Any]] = (
            [org for org in raw_orgs if isinstance(org, dict)] if isinstance(raw_orgs, list) else []
        )
        if organizations:
            # A later `--org` rerun resolves against this list (finite life).
            save_org_cache(email, organizations)
        choice: dict[str, Any] | None = None
        if not organizations:
            print_error("Organization selection required but no organizations returned.")
        elif picked:
            print_error("The organization could not be selected. Pick one from this list:")
            _print_org_list(organizations)
            _org_rerun_hint(email)
        elif organization_uuid is not None:
            choice = next((o for o in organizations if o.get("uuid") == organization_uuid), None)
            if choice is None:
                print_error(
                    f"Organization '{plain_text(organization_uuid)}' is not one of this "
                    "account's organizations."
                )
                _print_org_list(organizations)
                _org_rerun_hint(email)
        elif len(organizations) == 1:
            choice = organizations[0]
            print_info(f"Auto-selecting organization: {choice.get('name', 'Unknown')}")
        elif allow_interactive_org_pick:
            choice = _prompt_org_selection(organizations)
        else:
            _print_org_list(organizations)
            _org_rerun_hint(email)
        if choice is None:
            raise SystemExit(1)
        choice_uuid: Any = choice.get("uuid")
        _verify_and_save(
            client,
            email,
            code,
            choice.get("id"),
            organization_uuid=str(choice_uuid) if choice_uuid else None,
            allow_interactive_org_pick=allow_interactive_org_pick,
            picked=True,
        )
        return

    token: str | None = result.get("token")
    if not token:
        print_error("Authentication failed: no token received.")
        raise SystemExit(1)

    org_raw: Any = result.get("organization", "")
    org_name: str = org_raw.get("name", "") if isinstance(org_raw, dict) else str(org_raw)
    org_uuid: str = (
        org_raw.get("uuid", "")
        if isinstance(org_raw, dict)
        else result.get("organization_uuid", "")
    )
    save_credentials(
        token=token,
        email=email,
        organization=org_name,
        organization_uuid=org_uuid,
        api_url=client.api_url,
    )
    clear_org_cache()
    # Cache the (non-sensitive) plan tier when the login response exposes it, so
    # non-allowlisted commands can short-circuit on a free plan. Absent = unknown.
    plan_tier: Any = (org_raw.get("plan") if isinstance(org_raw, dict) else None) or result.get(
        "plan"
    )
    if isinstance(plan_tier, str) and org_uuid:
        save_org_plan(org_uuid, plan_tier)
    print_success(f"Logged in as {email} ({org_name})")


def _do_login(email: str) -> None:
    """Shared login logic for 'dailybot login' and interactive mode."""
    client: DailyBotClient = DailyBotClient()

    # Step 1: Request the code. Its answer is never needed to pick the organization.
    try:
        with console.status("Sending verification code..."):
            request_result: dict[str, Any] = client.request_code(email)
    except APIError as e:
        _exit_for_login_door_error(e)
    _notice_deprecation(request_result)
    _print_code_requested(email, request_result)

    # Step 2: Enter the code (not shown while typing).
    code: str = click.prompt("Enter the 6-digit code", type=str, hide_input=True)
    code = code.strip()

    # Step 3: Verify; the organization is picked here if the account has several.
    _verify_and_save(client, email, code, allow_interactive_org_pick=True)


def _request_code_non_interactive(email: str) -> None:
    """Non-interactive step 1: request OTP and print next-step instructions."""
    client: DailyBotClient = DailyBotClient()

    try:
        with console.status("Sending verification code..."):
            request_result: dict[str, Any] = client.request_code(email)
    except APIError as e:
        _exit_for_login_door_error(e)
    _notice_deprecation(request_result)
    _print_code_requested(email, request_result)

    is_multi_org: bool = request_result.get("is_multi_org", False)
    raw_orgs: Any = request_result.get("organizations")
    organizations: list[dict[str, Any]] = raw_orgs if isinstance(raw_orgs, list) else []

    if is_multi_org and len(organizations) > 1:
        # Servers that still list organizations here: keep the familiar output.
        save_org_cache(email, organizations)
        _print_org_list(organizations)
        _org_rerun_hint(email)
        return
    print_info(f"Run: dailybot login --email={email} --code={CODE_PLACEHOLDER}")
    if not organizations:
        print_info(
            "If you belong to several organizations, that step lists them; "
            "pick one with --org=ORG_UUID."
        )


def _verify_non_interactive(email: str, code: str, org_uuid: str | None) -> None:
    """Non-interactive step 2: verify the code, with the organization from ``--org``.

    ``--org`` is sent as ``organization_uuid``. When a recent organization list is
    cached (from step 1 or an earlier selection answer) its integer id is sent too,
    for servers that only read ``organization_id``.
    """
    client: DailyBotClient = DailyBotClient()

    organization_id: int | None = None
    if org_uuid is not None:
        cached_orgs: list[dict[str, Any]] | None = load_org_cache(email)
        if cached_orgs:
            organization_id = _resolve_org_uuid(cached_orgs, org_uuid)

    _verify_and_save(client, email, code.strip(), organization_id, organization_uuid=org_uuid)


@click.command()
@click.option("--email", default=None, help="Your Dailybot account email (email-code sign-in).")
@click.option(
    "--code",
    default=None,
    help="6-digit OTP code from email. If omitted, the CLI requests a code and prompts interactively.",
)
@click.option(
    "--org",
    "org_uuid",
    default=None,
    type=str,
    help="Organization UUID to log in to (for multi-org accounts). Shown after requesting a code.",
)
@click.option(
    "--device",
    "use_device",
    is_flag=True,
    default=False,
    help="Sign in through the browser: approve a short code at a Dailybot link. "
    "Falls back to the email code on servers that do not offer it yet.",
)
def login(email: str | None, code: str | None, org_uuid: str | None, use_device: bool) -> None:
    """Authenticate with Dailybot via email OTP, or in the browser with --device.

    \b
    Browser sign-in (prints a link and a code to approve; works over SSH):
      dailybot login --device

    \b
    Non-interactive usage (for scripts and AI agents):
      Step 1: Request a code
        dailybot login --email=user@example.com
      Step 2: Verify the code
        dailybot login --email=user@example.com --code=123456
      Multi-org: pass --org with the UUID shown in step 1
        dailybot login --email=user@example.com --code=123456 --org=abc-123
    """
    if use_device and (code is not None or org_uuid is not None):
        raise click.UsageError("--device cannot be combined with --code or --org.")

    global _deprecation_noticed
    _deprecation_noticed = False

    _warn_if_env_json_redirects_login()

    browser: bool = use_device or (
        _device_login.DEVICE_LOGIN_IS_DEFAULT and email is None and code is None
    )
    if browser:
        try:
            _device_login.device_login(DailyBotClient())
            return
        except _device_login.DeviceFlowUnsupported:
            print_info(
                "This Dailybot server does not offer browser sign-in yet. "
                "Continuing with an email code."
            )

    email_from_flag: bool = email is not None
    if email is None:
        email = click.prompt("Email", type=str)

    if code is not None:
        # Non-interactive step 2: verify code directly
        _verify_non_interactive(email, code, org_uuid)
    elif email_from_flag:
        # Non-interactive step 1: request code, print instructions, exit
        _request_code_non_interactive(email)
    else:
        # Fully interactive (email was prompted)
        _do_login(email)


@click.command()
def logout() -> None:
    """Log out and revoke the current token."""
    # Logout is a Bearer-session operation: /v1/cli/auth/logout/ is Bearer-only.
    # An API key has no session to revoke, so we never send X-API-KEY here.
    token: str | None = get_token()
    if not token:
        if get_api_key():
            print_info(
                "Logout applies to a login session; API-key auth has no session to "
                "revoke. Run `dailybot login` if you meant to start a session."
            )
        else:
            print_info("Not logged in.")
        return

    # Revoke on the host that issued the session, not on whatever `env.json`
    # or `--api-url` points at: the token is only valid (and only sent) there.
    # Revoke every session this invocation knows: a DAILYBOT_CLI_TOKEN on the
    # current API (the caller's explicit session), and a stored login on the
    # host that issued it. Best-effort each; local credentials are cleared after.
    # A device-flow pair is revoked as a whole family: with the Bearer access, or
    # with the refresh token alone once the access has expired.
    targets: list[tuple[str, str, str | None]] = []
    env_token: str | None = os.environ.get("DAILYBOT_CLI_TOKEN")
    if env_token:
        targets.append((get_api_url(), env_token, None))
    stored: dict[str, Any] | None = load_credentials()
    if stored and stored.get("token"):
        origin: str = login_token_origin_url()
        targets.append((origin, str(stored["token"]), get_refresh_token_for(origin)))
    if not targets:
        targets.append((login_token_origin_url(), token, None))
    access_expired: bool = is_access_token_expired()
    unrevoked_pair: bool = False
    for api_url, session_token, refresh in targets:
        client: DailyBotClient = DailyBotClient(api_url=api_url, token=session_token)
        client.api_key = None
        try:
            with console.status("Logging out..."):
                client.logout(refresh=refresh, access_expired=access_expired and bool(refresh))
        except APIError as error:
            if error.code == AUTH_BACKEND_UNAVAILABLE_CODE:
                # Transient: keep the session so logout can be retried and revoke it.
                exit_for_api_error(error, json_mode=False)
            # Revoke best-effort; clear local credentials regardless
            unrevoked_pair = unrevoked_pair or bool(refresh)

    clear_credentials()
    if unrevoked_pair:
        print_warning(
            "Could not revoke the session on the server; it stays valid there until it "
            "expires. The local credentials were removed."
        )
    print_success("Logged out.")
