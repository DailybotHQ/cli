"""Authentication commands for Dailybot CLI."""

from typing import Any

import click
import questionary

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.config import (
    RepoEnvError,
    clear_credentials,
    clear_org_cache,
    get_active_env_profile,
    get_api_key,
    get_api_url,
    get_token,
    load_org_cache,
    save_credentials,
    save_org_cache,
    save_org_plan,
)
from dailybot_cli.display import (
    console,
    print_error,
    print_info,
    print_success,
    print_warning,
)


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


def _prompt_org_selection_numbered(organizations: list[dict[str, Any]]) -> dict[str, Any]:
    """Numbered org picker — fallback when questionary TUI is unavailable."""
    print_info("You belong to multiple organizations. Select one by number:")
    for index, org in enumerate(organizations, start=1):
        org_name: str = org.get("name", "Unknown")
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
        questionary.Choice(title=org.get("name", "Unknown"), value=org) for org in organizations
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


def _verify_and_save(
    client: DailyBotClient,
    email: str,
    code: str,
    organization_id: int | None,
    *,
    allow_interactive_org_pick: bool = False,
) -> None:
    """Verify OTP code and save credentials."""
    try:
        with console.status("Verifying code..."):
            result: dict[str, Any] = client.verify_code(
                email, code, organization_id=organization_id
            )
    except APIError as e:
        print_error(e.detail)
        raise SystemExit(1)

    # If the API says org selection is required, auto-select or prompt
    if result.get("requires_organization_selection"):
        organizations: list[dict[str, Any]] = result.get("organizations", [])
        if len(organizations) == 1:
            # Auto-select the only org and retry
            auto_org_id: int = organizations[0]["id"]
            print_info(f"Auto-selecting organization: {organizations[0].get('name', 'Unknown')}")
            _verify_and_save(
                client,
                email,
                code,
                auto_org_id,
                allow_interactive_org_pick=allow_interactive_org_pick,
            )
            return
        elif organizations:
            if allow_interactive_org_pick:
                selected_org: dict[str, Any] = _prompt_org_selection(organizations)
                _verify_and_save(
                    client,
                    email,
                    code,
                    selected_org["id"],
                    allow_interactive_org_pick=True,
                )
                return
            _print_org_list(organizations)
            print_info(f"Run: dailybot login --email={email} --code={code} --org=ORG_UUID")
        else:
            print_error("Organization selection required but no organizations returned.")
        raise SystemExit(1)

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

    # Step 1: Request OTP code
    try:
        with console.status("Sending verification code..."):
            request_result: dict[str, Any] = client.request_code(email)
    except APIError as e:
        print_error(e.detail)
        raise SystemExit(1)

    print_success(f"Verification code sent to {email}")
    print_info("Check your inbox (including spam folder).")

    is_multi_org: bool = request_result.get("is_multi_org", False)
    organizations: list[dict[str, Any]] = request_result.get("organizations", [])

    # Step 2: Pick organization before the code prompt so questionary TUI works
    # reliably (click.prompt can break questionary if it runs afterward).
    organization_id: int | None = None
    if is_multi_org and len(organizations) > 1:
        selected_org: dict[str, Any] = _prompt_org_selection(organizations)
        organization_id = selected_org["id"]
    elif len(organizations) == 1:
        organization_id = organizations[0].get("id")

    # Step 3: Enter code
    code: str = click.prompt("Enter the 6-digit code", type=str)
    code = code.strip()

    # Step 4: Verify code and save credentials
    _verify_and_save(
        client,
        email,
        code,
        organization_id,
        allow_interactive_org_pick=True,
    )


def _request_code_non_interactive(email: str) -> None:
    """Non-interactive step 1: request OTP and print next-step instructions."""
    client: DailyBotClient = DailyBotClient()

    try:
        with console.status("Sending verification code..."):
            request_result: dict[str, Any] = client.request_code(email)
    except APIError as e:
        print_error(e.detail)
        raise SystemExit(1)

    print_success(f"Verification code sent to {email}")
    print_info("Check your inbox (including spam folder).")

    is_multi_org: bool = request_result.get("is_multi_org", False)
    organizations: list[dict[str, Any]] = request_result.get("organizations", [])

    if is_multi_org and len(organizations) > 1:
        save_org_cache(email, organizations)
        _print_org_list(organizations)
        print_info(f"Run: dailybot login --email={email} --code=CODE --org=ORG_UUID")
    else:
        print_info(f"Run: dailybot login --email={email} --code=CODE")


def _verify_non_interactive(email: str, code: str, org_uuid: str | None) -> None:
    """Non-interactive step 2: verify code, handle missing --org for multi-org."""
    client: DailyBotClient = DailyBotClient()

    organization_id: int | None = None
    if org_uuid is not None:
        # Resolve UUID → integer ID from the cached org list (saved in step 1).
        # This avoids calling request_code or verify_code without org_id,
        # which would consume/invalidate the OTP.
        cached_orgs: list[dict[str, Any]] | None = load_org_cache(email)
        if cached_orgs is None:
            print_error("No cached organization list found. Run step 1 first:")
            print_info(f"  dailybot login --email={email}")
            raise SystemExit(1)

        organization_id = _resolve_org_uuid(cached_orgs, org_uuid)
        if organization_id is None:
            print_error(f"Organization with uuid '{org_uuid}' not found.")
            _print_org_list(cached_orgs)
            raise SystemExit(1)

    _verify_and_save(client, email, code.strip(), organization_id)
    clear_org_cache()


@click.command()
@click.option("--email", prompt="Email", help="Your Dailybot account email.")
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
@click.pass_context
def login(ctx: click.Context, email: str, code: str | None, org_uuid: str | None) -> None:
    """Authenticate with Dailybot via email OTP.

    \b
    Non-interactive usage (for scripts and AI agents):
      Step 1: Request a code
        dailybot login --email=user@example.com
      Step 2: Verify the code
        dailybot login --email=user@example.com --code=123456
      Multi-org: pass --org with the UUID shown in step 1
        dailybot login --email=user@example.com --code=123456 --org=abc-123
    """
    email_from_flag: bool = (
        ctx.get_parameter_source("email") == click.core.ParameterSource.COMMANDLINE
    )

    _warn_if_env_json_redirects_login()

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

    client: DailyBotClient = DailyBotClient()
    try:
        with console.status("Logging out..."):
            client.logout()
    except APIError:
        pass  # Revoke best-effort; clear local credentials regardless

    clear_credentials()
    print_success("Logged out.")
