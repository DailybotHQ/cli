"""Rich console output helpers for Dailybot CLI."""

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console: Console = Console()
error_console: Console = Console(stderr=True)


def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[bold green]OK[/bold green] {message}")


def print_error(message: str) -> None:
    """Print an error message to stderr."""
    error_console.print(f"[bold red]Error:[/bold red] {message}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[bold yellow]Warning:[/bold yellow] {message}")


def print_info(message: str) -> None:
    """Print an info message."""
    console.print(f"[dim]{message}[/dim]")


def print_version_info(
    version: str,
    python_version: str,
    install_path: str,
    latest_version: str | None = None,
) -> None:
    """Render the rich `dailybot version` panel.

    Shows the installed CLI version, the host Python version, where the package
    is installed on disk, and a link to the matching GitHub release. When
    ``latest_version`` is provided, also indicates whether the install is
    up-to-date or an update is available.
    """
    table: Table = Table.grid(padding=(0, 2))
    table.add_column(justify="right", style="dim")
    table.add_column()
    table.add_row("Version:", f"[bold]{version}[/bold]")
    table.add_row("Python:", python_version)
    table.add_row("Installed:", install_path)
    table.add_row(
        "Release notes:",
        f"https://github.com/DailyBotHQ/cli/releases/tag/v{version}",
    )

    if latest_version is not None:
        if latest_version == version:
            table.add_row("Update check:", "[green]up-to-date[/green]")
        else:
            table.add_row(
                "Update check:",
                f"[yellow]update available: {latest_version}[/yellow]",
            )

    console.print(Panel(table, title="Dailybot CLI", border_style="cyan", expand=False))

    if latest_version is not None and latest_version != version:
        console.print()
        console.print("[dim]Upgrade with one of:[/dim]")
        console.print("  [cyan]brew upgrade dailybot[/cyan]                       (macOS)")
        console.print(
            "  [cyan]curl -sSL https://cli.dailybot.com/install.sh | bash[/cyan]  (Linux x86_64)"
        )
        console.print("  [cyan]pipx upgrade dailybot-cli[/cyan]                    (any OS, pipx)")
        console.print("  [cyan]pip install --upgrade dailybot-cli[/cyan]           (any OS, pip)")


def _format_sender(msg: dict[str, Any]) -> str:
    """Format sender prefix for a message: [type] name: or [type]:

    Brackets are escaped for Rich markup (\\[ renders as literal [).
    """
    sender_type: str = msg.get("sender_type", "")
    sender_name: str = msg.get("sender_name") or ""
    if sender_name:
        return f"\\[{sender_type}] {sender_name}:"
    if sender_type:
        return f"\\[{sender_type}]:"
    return ""


def print_auth_status(data: dict[str, Any]) -> None:
    """Display auth status information."""
    user_raw: Any = data.get("user", "")
    email: str = (
        user_raw.get("email", "")
        if isinstance(user_raw, dict)
        else str(user_raw or data.get("email", ""))
    )
    org_raw: Any = data.get("organization", "")
    org_name: str = org_raw.get("name", "") if isinstance(org_raw, dict) else str(org_raw)
    org_uuid: str = org_raw.get("uuid", "") if isinstance(org_raw, dict) else ""
    table: Table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Email", email)
    table.add_row("Organization", org_name)
    if org_uuid:
        table.add_row("Org UUID", org_uuid)
    console.print(Panel(table, title="[bold]Auth Status[/bold]", border_style="green"))


def print_pending_checkins(checkins: list[dict[str, Any]]) -> None:
    """Display pending check-ins."""
    if not checkins:
        print_info("No pending check-ins for today.")
        return

    for checkin in checkins:
        name: str = checkin.get("followup_name", "Check-in")
        questions: list[dict[str, Any]] = checkin.get("template_questions", [])
        content: Text = Text()
        for i, q in enumerate(questions):
            prefix: str = f"  {i + 1}. "
            content.append(prefix, style="dim")
            content.append(str(q.get("question", "")))
            if q.get("is_blocker"):
                content.append(" [blocker]", style="bold red")
            content.append("\n")
        console.print(
            Panel(
                content,
                title=f"[bold]{name}[/bold]",
                border_style="cyan",
            )
        )


def print_agent_health(data: dict[str, Any]) -> None:
    """Display agent health status."""
    agent_name: str = data.get("agent_name", "Unknown")
    status: str = data.get("status", "unknown")
    last_check: str = data.get("last_check", "N/A")

    style: str = "green" if status == "healthy" else "red" if status == "unhealthy" else "yellow"
    status_display: str = f"[bold {style}]{status}[/bold {style}]"

    table: Table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Agent", agent_name)
    table.add_row("Status", status_display)
    table.add_row("Last Check", last_check)
    console.print(Panel(table, title="[bold]Agent Health[/bold]", border_style=style))

    history: list[dict[str, Any]] = data.get("history", [])
    if history:
        hist_table: Table = Table(title="Recent History", border_style="dim")
        hist_table.add_column("Timestamp", style="dim")
        hist_table.add_column("Status")
        hist_table.add_column("Message")
        for entry in history:
            entry_status: str = entry.get("status", "")
            entry_style: str = "green" if entry_status == "healthy" else "red"
            hist_table.add_row(
                entry.get("timestamp", ""),
                Text(entry_status, style=entry_style),
                entry.get("message", ""),
            )
        console.print(hist_table)

    pending: list[dict[str, Any]] = data.get("pending_messages", [])
    print_pending_agent_messages(pending)


def print_pending_agent_messages(messages: list[dict[str, Any]]) -> None:
    """Display pending messages with IDs for agent consumption."""
    if not messages:
        return
    console.print(f"\n--- Pending messages from Dailybot ({len(messages)}) ---")
    for msg in messages:
        msg_id: str = msg.get("id", "?")
        sender: str = _format_sender(msg)
        content: str = msg.get("content", "")
        line: str = (
            f"\\[id:{msg_id}] {sender} {content}" if sender else f"\\[id:{msg_id}] {content}"
        )
        console.print(line)
    console.print("[dim]Claim: dailybot agent message claim <id>[/dim]")


def print_webhook_result(data: dict[str, Any]) -> None:
    """Display webhook registration result."""
    table: Table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Agent", data.get("agent_name", ""))
    table.add_row("Webhook URL", data.get("webhook_url", ""))
    console.print(Panel(table, title="[bold]Webhook Registered[/bold]", border_style="green"))


def print_agent_messages(messages: list[dict[str, Any]]) -> None:
    """Display a list of agent messages."""
    if not messages:
        print_info("No messages found.")
        return
    table: Table = Table(title="Agent Messages", border_style="cyan")
    table.add_column("Type", style="dim")
    table.add_column("Sender")
    table.add_column("Content")
    table.add_column("Delivered")
    table.add_column("Created", style="dim")
    for msg in messages:
        delivered: bool = msg.get("delivered", False)
        delivered_text: str = "[green]yes[/green]" if delivered else "[yellow]no[/yellow]"
        sender_type: str = msg.get("sender_type", "")
        sender_name: str = msg.get("sender_name") or ""
        sender_display: str = f"{sender_name} ({sender_type})" if sender_name else sender_type
        table.add_row(
            msg.get("message_type", "text"),
            sender_display,
            msg.get("content", ""),
            delivered_text,
            msg.get("created_at", ""),
        )
    console.print(table)


def print_agent_message_sent(data: dict[str, Any]) -> None:
    """Display the result of sending an agent message."""
    table: Table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("ID", data.get("id", "N/A"))
    table.add_row("To", data.get("agent_name", ""))
    table.add_row("From", data.get("sender_name") or data.get("sender_type", ""))
    table.add_row("Type", data.get("message_type", "text"))
    table.add_row("Content", data.get("content", ""))
    console.print(Panel(table, title="[bold]Message Sent[/bold]", border_style="green"))


def print_agent_email_sent(data: dict[str, Any]) -> None:
    """Display the result of sending an agent email."""
    table: Table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row(
        "Sent", f"{data.get('sent_count', 0)} of {data.get('total_recipients', 0)} recipients"
    )
    reply_to: str = data.get("reply_to", "")
    if reply_to:
        table.add_row("Reply-to", reply_to)
    console.print(Panel(table, title="[bold]Email Sent[/bold]", border_style="green"))


def print_agent_profiles(profiles: list[dict[str, Any]]) -> None:
    """Display agent profiles in a table."""
    if not profiles:
        print_info('No agent profiles configured. Run: dailybot agent configure --name "My Agent"')
        return
    table: Table = Table(title="Agent Profiles", border_style="cyan")
    table.add_column("Profile", style="bold")
    table.add_column("Agent Name")
    table.add_column("Email")
    table.add_column("Auth")
    table.add_column("Default")
    for p in profiles:
        auth: str = "login token"
        if p.get("has_key"):
            auth = p.get("masked_key", "****")
        default: str = "[green]yes[/green]" if p.get("is_default") else ""
        table.add_row(p["profile"], p["agent_name"], p.get("agent_email", ""), auth, default)
    console.print(table)


def print_resolved_profile(resolved: dict[str, Any]) -> None:
    """Display the resolved active agent profile with field provenance."""
    table: Table = Table(title="Resolved Agent Profile", border_style="cyan")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_column("Source", style="dim")

    sources: dict[str, str] = resolved.get("resolved_from", {})
    table.add_row("Agent name", str(resolved.get("agent_name", "")), sources.get("agent_name", ""))

    slug: str = resolved.get("profile_slug") or "(none)"
    table.add_row("Profile slug", slug, sources.get("profile", ""))

    api_key: str | None = resolved.get("api_key")
    table.add_row("API key", "set" if api_key else "(none)", "global" if api_key else "")

    repo_path: str | None = resolved.get("repo_profile_path")
    table.add_row("Repo file", repo_path or "(not found)", "walk-up" if repo_path else "")

    metadata: dict[str, Any] = resolved.get("default_metadata") or {}
    if metadata:
        table.add_row(
            "Default metadata",
            ", ".join(f"{k}={v}" for k, v in metadata.items()),
            sources.get("default_metadata", ""),
        )
    else:
        table.add_row("Default metadata", "(none)", "")

    console.print(table)

    if resolved.get("profile_missing_from_repo"):
        print_warning(
            f"Repo declared profile '{resolved.get('profile_slug')}' but it is not "
            "in agents.json. Falling back to session credentials."
        )


def print_registration_result(data: dict[str, Any]) -> None:
    """Display agent registration result."""
    table: Table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column(no_wrap=True, overflow="fold")
    table.add_row("Agent", data.get("agent_name", ""))
    agent_email: str = data.get("agent_email", "")
    if agent_email:
        table.add_row("Email", f"[bold]{agent_email}[/bold]")
    table.add_row("Org", data.get("org_name", ""))
    if data.get("profile"):
        table.add_row("Profile", data["profile"])
    claim_url: str = data.get("claim_url", "")
    if claim_url:
        table.add_row("Claim URL", f"[bold cyan]{claim_url}[/bold cyan]")
    console.print(Panel(table, title="[bold]Agent Registered[/bold]", border_style="green"))
    if claim_url:
        console.print(f"\nClaim URL: {claim_url}")


def print_update_result(data: dict[str, Any]) -> None:
    """Display the result of submitting an update."""
    count: int = data.get("followups_count", 0)
    attached: list[dict[str, Any]] = data.get("attached_followups", [])
    if count == 0:
        print_warning("Update submitted but no check-ins were matched.")
        return
    print_success(f"Update submitted to {count} check-in(s)")
    for followup in attached:
        name: str = followup.get("followup_name", "")
        action: str = followup.get("action", "created")
        label: str = "Updated" if action == "updated" else "Submitted"
        console.print(f"  [dim]-[/dim] {name} [dim]({label})[/dim]")


def print_checkin_list_overview(count: int, checkins: list[dict[str, Any]]) -> None:
    """Display a summary table of pending check-ins with UUIDs."""
    if not checkins:
        print_info("No pending check-ins for today.")
        return

    table: Table = Table(title=f"Pending Check-ins ({count})", border_style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Followup UUID", style="dim")
    table.add_column("Questions", justify="right")
    for checkin in checkins:
        table.add_row(
            str(checkin.get("followup_name", "Check-in")),
            str(checkin.get("followup_uuid", "")),
            str(len(checkin.get("template_questions", []))),
        )
    console.print(table)


def print_checkin_complete_result(followup_name: str, data: dict[str, Any]) -> None:
    """Display the result of completing a check-in."""
    response_id: str = str(data.get("uuid") or data.get("id") or "N/A")
    print_success(f'Check-in completed for "{followup_name}"')
    print_info(f"Response ID: {response_id}")


def print_forms_table(forms: list[dict[str, Any]]) -> None:
    """Display visible forms in a table."""
    if not forms:
        print_info("No forms visible to you.")
        return

    table: Table = Table(title="Forms", border_style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Form UUID", style="dim")
    table.add_column("Questions", style="dim", justify="right")
    for form in forms:
        form_id: str = str(form.get("id") or "")
        if not form_id:
            continue
        question_count: int = len(
            form.get("questions") or form.get("template_questions") or form.get("fields") or []
        )
        count_str: str = str(question_count) if question_count else "—"
        table.add_row(
            str(form.get("name", "")),
            form_id,
            count_str,
        )
    console.print(table)


def print_form_submit_result(form_name: str, data: dict[str, Any]) -> None:
    """Display the result of submitting a form response."""
    response_id: str = str(data.get("uuid") or data.get("id") or "N/A")
    print_success(f'Form response submitted for "{form_name}"')
    print_info(f"Response ID: {response_id}")


def print_kudos_result(receiver_name: str, data: dict[str, Any]) -> None:
    """Display the result of giving kudos."""
    kudos_id: str = str(data.get("uuid") or data.get("id") or "N/A")
    print_success(f"Kudos sent to {receiver_name}")
    print_info(f"Kudos ID: {kudos_id}")


def print_users_table(users: list[dict[str, Any]]) -> None:
    """Display organization members in a table."""
    if not users:
        print_info("No team members found.")
        return

    table: Table = Table(title="Team members", border_style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("User UUID", style="dim")
    for user in users:
        table.add_row(
            str(user.get("full_name") or user.get("uuid") or ""),
            str(user.get("uuid") or ""),
        )
    console.print(table)
