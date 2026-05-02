"""Agent commands for Dailybot CLI (API key or login session)."""

import re
from typing import Any, Optional

import click

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.config import (
    _slugify,
    get_agent_auth,
    get_default_profile,
    get_profile,
    get_token,
    list_profiles,
    load_agents,
    save_agent_profile,
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
    print_success,
    print_webhook_result,
)

_NO_AUTH_MSG: str = (
    "No agent profile or authentication found. Use one of:\n"
    '  - dailybot agent configure --name "My Agent"\n'
    "  - DAILYBOT_API_KEY environment variable\n"
    "  - dailybot config key=<KEY>\n"
    "  - dailybot login"
)

# Challenge constants (from backend registration_challenge_service.py)
_CHALLENGE_WORD_COUNT: int = 52
_CHALLENGE_NUMBER_RE: re.Pattern[str] = re.compile(r"session is (\d+)\.")


def _resolve_agent_context(
    profile_flag: Optional[str],
    name_flag: Optional[str],
) -> tuple[str, DailyBotClient]:
    """Resolve agent name and build a configured client.

    Resolution order:
      1. --profile explicitly passed → that profile from agents.json
      2. No --profile → default profile from agents.json (if exists)
      3. No profile → DAILYBOT_API_KEY env var
      4. No env var → config.json api_key (legacy)
      5. No api_key → Bearer token from credentials.json
      6. Nothing → error

    agent_name: profile.agent_name > --name flag > "CLI Agent"
    """
    # Try profile
    profile_data: Optional[dict[str, Any]] = None
    if profile_flag:
        profile_data = get_profile(profile_flag)
        if not profile_data:
            print_error(f"Profile '{profile_flag}' not found. Run: dailybot agent profiles")
            raise SystemExit(1)
    else:
        profile_data = get_default_profile()

    if profile_data:
        agent_name: str = name_flag or profile_data.get("agent_name", "CLI Agent")
        api_key: Optional[str] = profile_data.get("api_key")
        if api_key:
            return agent_name, DailyBotClient(api_key=api_key)
        # Profile without key — fall through to Bearer token
        if get_token():
            return agent_name, DailyBotClient()
        print_error(
            f"Profile '{profile_data['profile']}' has no API key and no login session.\n"
            "  Run: dailybot login  or  dailybot agent configure --name ... --key ..."
        )
        raise SystemExit(1)

    # No profile — legacy fallback
    if not get_agent_auth():
        print_error(_NO_AUTH_MSG)
        raise SystemExit(1)

    agent_name = name_flag or "CLI Agent"
    return agent_name, DailyBotClient()


# --- Agent group ---


@click.group()
@click.option(
    "--profile", "-p", default=None, help="Agent profile name from agents.json.", hidden=False
)
@click.pass_context
def agent(ctx: click.Context, profile: Optional[str]) -> None:
    """Agent commands (requires API key or login session)."""
    ctx.ensure_object(dict)
    ctx.obj["profile"] = profile


# --- configure & profiles ---


@agent.command(name="configure")
@click.option("--name", "-n", required=True, help="Agent display name.")
@click.option("--key", "-k", default=None, help="API key (optional — omit if using OTP login).")
@click.option(
    "--profile", "profile_name", default=None, help="Profile name (defaults to slugified --name)."
)
@click.pass_context
def agent_configure(
    ctx: click.Context, name: str, key: Optional[str], profile_name: Optional[str]
) -> None:
    """Configure a named agent profile.

    \b
      dailybot agent configure --name "Claude Code"
      dailybot agent configure --name "CI Bot" --key abc123
      dailybot agent configure --name "Claude Code" --profile claude
    """
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


@agent.command(name="profiles")
def agent_profiles() -> None:
    """List all configured agent profiles."""
    profiles: list[dict[str, Any]] = list_profiles()
    # Add masked keys for display
    data: dict[str, Any] = load_agents()
    all_profiles: dict[str, Any] = data.get("profiles", {})
    for p in profiles:
        raw_key: Optional[str] = all_profiles.get(p["profile"], {}).get("api_key")
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
    name: Optional[str],
    profile: Optional[str],
    json_data: Optional[str],
    metadata: Optional[str],
    milestone: bool,
    co_authors: tuple[str, ...],
) -> None:
    """Submit an agent activity report.

    \b
      dailybot agent update "Deployed v2.1 to staging"
      dailybot agent update "Built feature X" --name "Claude Code"
      dailybot agent update "Deployed" --profile ci-bot
    """
    profile_flag: Optional[str] = profile or ctx.obj.get("profile")
    agent_name, client = _resolve_agent_context(profile_flag, name)

    import json as json_mod

    structured: Optional[dict[str, Any]] = None
    if json_data:
        try:
            structured = json_mod.loads(json_data)
        except json_mod.JSONDecodeError:
            print_error("Invalid JSON in --json-data.")
            raise SystemExit(1)

    metadata_dict: Optional[dict[str, Any]] = None
    if metadata:
        try:
            metadata_dict = json_mod.loads(metadata)
        except json_mod.JSONDecodeError:
            print_error("Invalid JSON in --metadata.")
            raise SystemExit(1)

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
        co: Optional[list[dict[str, Any]]] = result.get("co_authors")
        if co:
            names: str = ", ".join(a.get("name", a.get("uuid", "?")) for a in co)
            msg += f"\n  Co-authors: {names}"
        print_success(msg)
        pending: list[dict[str, Any]] = result.get("pending_messages", [])
        if pending:
            print_pending_agent_messages(pending)
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
    message: Optional[str],
    name: Optional[str],
    profile: Optional[str],
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

    profile_flag: Optional[str] = profile or ctx.obj.get("profile")
    agent_name, client = _resolve_agent_context(profile_flag, name)

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
    ctx: click.Context, url: str, secret: Optional[str], name: Optional[str], profile: Optional[str]
) -> None:
    """Register a webhook for the agent.

    \b
      dailybot agent webhook register --url https://my-server.com/hook
      dailybot agent webhook register --url https://... --secret my-token
    """
    profile_flag: Optional[str] = profile or ctx.obj.get("profile")
    agent_name, client = _resolve_agent_context(profile_flag, name)

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
def webhook_unregister(ctx: click.Context, name: Optional[str], profile: Optional[str]) -> None:
    """Unregister the agent's webhook.

    \b
      dailybot agent webhook unregister
      dailybot agent webhook unregister --name "Claude Code"
    """
    profile_flag: Optional[str] = profile or ctx.obj.get("profile")
    agent_name, client = _resolve_agent_context(profile_flag, name)

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
    message_type: Optional[str],
    name: Optional[str],
    profile: Optional[str],
    json_data: Optional[str],
    expires_at: Optional[str],
) -> None:
    """Send a message to an agent.

    \b
      dailybot agent message send --to "Claude Code" --content "Review PR #42"
      dailybot agent message send --to "Claude Code" --content "Do X" --type command
    """
    profile_flag: Optional[str] = profile or ctx.obj.get("profile")
    agent_name, client = _resolve_agent_context(profile_flag, name)

    metadata: Optional[dict[str, Any]] = None
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
def message_list(
    ctx: click.Context, name: Optional[str], profile: Optional[str], pending: bool
) -> None:
    """List messages for an agent.

    \b
      dailybot agent message list --name "Claude Code"
      dailybot agent message list --pending
    """
    profile_flag: Optional[str] = profile or ctx.obj.get("profile")
    agent_name, client = _resolve_agent_context(profile_flag, name)

    delivered: Optional[bool] = False if pending else None
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
def message_claim(ctx: click.Context, message_ids: tuple[str, ...], profile: Optional[str]) -> None:
    """Mark one or more messages as read.

    \b
      dailybot agent message claim abc-123
      dailybot agent message claim abc-123 def-456
    """
    profile_flag: Optional[str] = profile or ctx.obj.get("profile")
    _agent_name, client = _resolve_agent_context(profile_flag, None)

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
def message_claim_all(ctx: click.Context, name: Optional[str], profile: Optional[str]) -> None:
    """Mark all pending messages as delivered via health check.

    \b
      dailybot agent message claim-all
      dailybot agent message claim-all --name "Claude Code"
    """
    profile_flag: Optional[str] = profile or ctx.obj.get("profile")
    agent_name, client = _resolve_agent_context(profile_flag, name)

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
    name: Optional[str],
    profile: Optional[str],
    metadata: Optional[str],
) -> None:
    """Send an email through an agent.

    \b
      dailybot agent email send --to user@example.com --subject "Build passed" \\
        --body-html "<p>All green.</p>" --name "Claude Code"
      dailybot agent email send --to a@co.com --to b@co.com --subject "Report" \\
        --body-html "<h1>Done</h1>"
    """
    profile_flag: Optional[str] = profile or ctx.obj.get("profile")
    agent_name, client = _resolve_agent_context(profile_flag, name)

    to_list: list[str] = list(recipients)

    metadata_dict: Optional[dict[str, Any]] = None
    if metadata:
        import json

        try:
            metadata_dict = json.loads(metadata)
        except json.JSONDecodeError:
            print_error("Invalid JSON in --metadata.")
            raise SystemExit(1)

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
    match: Optional[re.Match[str]] = _CHALLENGE_NUMBER_RE.search(instruction)
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
    email: Optional[str],
    timezone: str,
    profile_name: Optional[str],
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
    api_key: Optional[str] = result.get("api_key")
    agent_email: Optional[str] = result.get("agent_email")
    save_agent_profile(slug, agent_name=agent_name, api_key=api_key, agent_email=agent_email)

    # Display result
    result["profile"] = slug
    print_registration_result(result)
    claim_url: str = result.get("claim_url", "")
    if claim_url:
        print_info(
            "Share the claim URL with your team admin to connect this org to Slack or Google Chat. The URL expires in 30 days."
        )
