"""Rich console output helpers for Dailybot CLI.

Messages passed to the print_* helpers routinely carry server-controlled text
(API error details, form/check-in content). Rich treats ``[...]`` as a style
tag, so every such message is escaped before interpolation.
"""

from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from dailybot_cli.api_client import resource_uuid

console: Console = Console()
error_console: Console = Console(stderr=True)


def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[bold green]OK[/bold green] {escape(message)}")


def print_error(message: str) -> None:
    """Print an error message to stderr."""
    error_console.print(f"[bold red]Error:[/bold red] {escape(message)}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[bold yellow]Warning:[/bold yellow] {escape(message)}")


def print_info(message: str) -> None:
    """Print an info message."""
    console.print(f"[dim]{escape(message)}[/dim]")


def print_kudos_table(kudos: list[dict[str, Any]]) -> None:
    """Render a compact table of kudos (giver → receivers, message, date)."""
    if not kudos:
        console.print("[dim]No kudos found.[/dim]")
        return
    table: Table = Table(title="Kudos", show_lines=False)
    table.add_column("From", style="cyan", no_wrap=True)
    table.add_column("To", style="green")
    table.add_column("Message")
    table.add_column("Date", style="dim", no_wrap=True)
    for item in kudos:
        giver_raw: Any = item.get("user") or {}
        giver: str = (
            "Anonymous" if item.get("is_anonymous") else str(giver_raw.get("full_name", "—"))
        )
        receivers_raw: Any = item.get("receivers") or []
        receivers: str = ", ".join(str(r.get("full_name", "?")) for r in receivers_raw) or "—"
        content: str = str(item.get("content", "")).strip() or "—"
        created: str = str(item.get("created_at", ""))[:10]
        table.add_row(giver, receivers, content, created)
    console.print(table)


def print_workflows_table(workflows: list[dict[str, Any]]) -> None:
    """Render a compact table of workflows (name, trigger, active, runs)."""
    if not workflows:
        console.print("[dim]No workflows found.[/dim]")
        return
    table: Table = Table(title="Workflows")
    table.add_column("Name", style="cyan")
    table.add_column("UUID", style="dim", no_wrap=True)
    table.add_column("Trigger")
    table.add_column("Active", justify="center")
    table.add_column("Runs", justify="right")
    for wf in workflows:
        active: str = "[green]yes[/green]" if wf.get("active") else "[dim]no[/dim]"
        table.add_row(
            str(wf.get("name", "—")),
            str(wf.get("uuid", "—")),
            str(wf.get("trigger_type", "—")),
            active,
            str(wf.get("total_runs", 0)),
        )
    console.print(table)


def print_detail_panel(title: str, data: dict[str, Any], fields: list[tuple[str, str]]) -> None:
    """Render a titled key/value panel from selected ``data`` fields.

    ``fields`` is a list of ``(label, key)`` pairs; missing/empty values are shown
    as a dim dash. Used by ``me`` / ``org`` / ``user get``.
    """
    table: Table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("Field", style="bold cyan", no_wrap=True)
    table.add_column("Value")
    for label, key in fields:
        raw: Any = data.get(key)
        value: str = str(raw) if raw not in (None, "") else "[dim]—[/dim]"
        table.add_row(label, value)
    console.print(Panel(table, title=title, border_style="cyan", expand=False))


def print_pagination_footer(
    shown: int,
    total: int | None = None,
    *,
    has_more: bool = False,
    more_hint: str = "use --all to fetch every page",
) -> None:
    """Render a compact 'Showing X of N' footer for a list command.

    ``total`` is the envelope ``count`` when known; ``has_more`` appends
    ``more_hint``. Commands where ``--all`` means something else (``form
    responses``, ``checkin history``) pass their own hint. Goes to stdout.
    """
    if total is not None and total != shown:
        text: str = f"Showing {shown} of {total}"
    else:
        noun: str = "result" if shown == 1 else "results"
        text = f"Showing {shown} {noun}"
    if has_more:
        text += f" — {more_hint}"
    console.print(f"[dim]{text}[/dim]")


def print_ai_answer(content: str) -> None:
    """Print a Dailybot AI answer to stdout verbatim.

    Markup interpretation is off and wrapping is soft, so arbitrary AI text
    (brackets, long lines) survives intact when piped into another tool.
    """
    console.print(content, markup=False, highlight=False, soft_wrap=True)


def print_interactive_chat_welcome(version: str, session_id: str) -> None:
    """Display the conversational terminal session header."""
    console.print(
        Panel(
            "Your Dailybot companion in the terminal.\n"
            "Ask a question or type `/help` for commands.",
            title=f"Dailybot interactive v{version}",
            border_style="cyan",
        )
    )
    console.print(f"[dim]Session: {session_id}[/dim]")


def print_interactive_chat_help(help_text: str) -> None:
    """Display conversational terminal slash-command help."""
    console.print(Markdown(help_text))


def print_interactive_chat_message(content: str) -> None:
    """Display one assistant message in the conversational terminal."""
    console.print(Panel(Markdown(content), title="Dailybot", border_style="green"))


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


def print_agent_messages(messages: list[Any]) -> None:
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
        if not isinstance(msg, dict):
            table.add_row("text", "", str(msg), "", "")
            continue
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


def print_chat_message_result(data: dict[str, Any], *, updated: bool = False) -> None:
    """Display the result of sending (or updating) a chat platform message."""
    bot_message_id: str = str(data.get("bot_message_id", ""))
    thread_ids: list[Any] = data.get("thread_responses") or []
    title: str = "Message Updated" if updated else "Message Sent"
    table: Table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    if bot_message_id:
        table.add_row("Message ID", bot_message_id)
        for i, reply_id in enumerate(thread_ids, start=1):
            table.add_row(f"Thread reply {i}", str(reply_id))
        table.add_row(
            "",
            Text(
                "Reuse any id with 'dailybot chat update <id>' to edit that "
                "message (parent or reply).",
                style="dim",
            ),
        )
    else:
        table.add_row("Status", "Enqueued")
    console.print(Panel(table, title=f"[bold]{title}[/bold]", border_style="green"))


def print_conversation_result(
    channel: str,
    participants: list[tuple[str, str]],
    *,
    message_sent: bool = False,
) -> None:
    """Display the opened Slack group conversation and its participants.

    ``participants`` is a list of ``(uuid, display_name)`` pairs. ``message_sent``
    flags whether a message was posted to the group right after opening it.
    """
    table: Table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column()
    table.add_row("Channel", channel)
    table.add_row("Participants", ", ".join(name for _uuid, name in participants) or "[dim]—[/dim]")
    if message_sent:
        table.add_row("Message", "Sent to the group")
    console.print(Panel(table, title="[bold]Group Conversation[/bold]", border_style="green"))


def print_agent_report_result(result: dict[str, Any]) -> None:
    """Display the result of submitting an agent activity report.

    Surfaces the report ID, milestone flag, the web-app placement link
    (when the backend returns one), and any co-authors.
    """
    msg: str = f"Report submitted (id: {result.get('id', 'N/A')})"
    if result.get("is_milestone"):
        msg += " [Milestone]"
    print_success(msg)

    url: str = result.get("url") or ""
    if url:
        # soft_wrap keeps the label and the (unbreakable) URL on one logical
        # line; without it Rich word-wraps at 80 cols and orphans "View:".
        console.print(f"  [cyan]View:[/cyan] {url}", soft_wrap=True)

    co_authors: list[dict[str, Any]] | None = result.get("co_authors")
    if co_authors:
        names: str = ", ".join(a.get("name", a.get("uuid", "?")) for a in co_authors)
        console.print(f"  Co-authors: {names}")


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
    response_id: str = resource_uuid(data) or "N/A"
    print_success(f'Check-in completed for "{followup_name}"')
    print_info(f"Response ID: {response_id}")


def _checkin_uuid(checkin: dict[str, Any]) -> str:
    """Best-effort check-in identifier (the API mixes uuid / followup_uuid / id)."""
    return str(checkin.get("uuid") or checkin.get("followup_uuid") or checkin.get("id") or "")


def _checkin_name(checkin: dict[str, Any]) -> str:
    return str(checkin.get("name") or checkin.get("followup_name") or "Check-in")


def print_checkin_status_table(checkins: list[dict[str, Any]], *, date_label: str) -> None:
    """Display each check-in with its pending/completed state for a date."""
    if not checkins:
        print_info(f"No check-ins for {date_label}.")
        return
    table: Table = Table(title=f"Check-ins — {date_label}", border_style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Followup UUID", style="dim")
    table.add_column("Questions", justify="right")
    for checkin in checkins:
        completed: bool = bool(
            checkin.get("response_completed")
            or checkin.get("is_completed")
            or checkin.get("completed")
        )
        status: str = "[green]completed[/green]" if completed else "[yellow]pending[/yellow]"
        questions: list[Any] = checkin.get("template_questions") or checkin.get("questions") or []
        table.add_row(
            _checkin_name(checkin),
            status,
            _checkin_uuid(checkin),
            str(len(questions)) if questions else "—",
        )
    console.print(table)


def _print_participants(participants: dict[str, Any]) -> None:
    """Render resolved check-in participants (users/teams with names)."""
    users: list[dict[str, Any]] = participants.get("users") or []
    teams: list[dict[str, Any]] = participants.get("teams") or []
    if not users and not teams:
        return
    table: Table = Table(title="Participants", border_style="cyan")
    table.add_column("Type")
    table.add_column("Name", style="bold")
    table.add_column("UUID", style="dim")
    for user in users:
        table.add_row("user", str(user.get("name") or ""), str(user.get("uuid") or ""))
    for team in teams:
        table.add_row("team", str(team.get("name") or ""), str(team.get("uuid") or ""))
    console.print(table)


def _print_attached_channels(channels: list[dict[str, Any]]) -> None:
    """Render report channels attached to a form/check-in.

    Detail returns ``{id, name, platform, type, reporting_enabled}``. Legacy
    entries written before names were resolved carry empty ``name``/``platform``,
    so the channel id is shown as a fallback.
    """
    if not channels:
        return
    table: Table = Table(title="Report Channels", border_style="cyan")
    table.add_column("Channel", style="bold")
    table.add_column("Platform")
    table.add_column("Channel ID", style="dim")
    table.add_column("Reporting")
    for channel in channels:
        channel_id: str = str(channel.get("id") or channel.get("uuid") or "")
        name: str = str(channel.get("name") or "")
        display_name: str = f"#{name}" if name else channel_id
        table.add_row(
            display_name,
            str(channel.get("platform") or ""),
            channel_id,
            "on" if channel.get("reporting_enabled", True) else "off",
        )
    console.print(table)


def _checkin_config_lines(detail: dict[str, Any]) -> list[str]:
    """Summarize the scheduling/behavior config for the check-in panel.

    Only surfaces fields that are present and meaningful, so pre-config check-ins
    render exactly as before.
    """
    lines: list[str] = []
    freq: Any = detail.get("frequency_type")
    every: Any = detail.get("frequency")
    if freq:
        lines.append(f"Frequency: {freq}" + (f" (every {every})" if every and every != 1 else ""))
    advanced: Any = detail.get("frequency_advanced")
    if advanced and advanced != "disabled":
        cron: Any = detail.get("frequency_cron")
        lines.append(f"Advanced: {advanced}" + (f" ({cron})" if cron else ""))
    if detail.get("start_on"):
        span: str = str(detail.get("start_on"))
        if detail.get("end_on"):
            span += f" → {detail.get('end_on')}"
        lines.append(f"Runs: {span}")
    if detail.get("use_participant_timezone"):
        lines.append("Timezone: each participant's own")
    reminders: Any = detail.get("reminders_max_count")
    if isinstance(reminders, int) and reminders > 0:
        interval: Any = detail.get("reminders_frequency_time")
        cond: Any = detail.get("reminders_trigger_condition")
        extra: str = f" every {interval}m" if interval else ""
        extra += f" ({cond})" if cond else ""
        tone: Any = detail.get("reminder_tone")
        extra += f", {tone} tone" if tone else ""
        lines.append(f"Reminders: {reminders}{extra}")
    elif reminders == 0:
        lines.append("Reminders: off")
    if detail.get("is_smart_checkin"):
        ai_bits: list[str] = ["smart"]
        if detail.get("is_intelligence_enabled"):
            ai_bits.append("intelligence")
        clarifying: Any = detail.get("max_clarifying_questions")
        if isinstance(clarifying, int) and clarifying > 0:
            ai_bits.append(f"{clarifying} clarifying Qs")
        lines.append("AI: " + ", ".join(ai_bits))
    flags: list[str] = []
    if detail.get("is_anonymous"):
        flags.append("anonymous")
    if detail.get("use_user_defined_work_days"):
        flags.append("respects work days")
    if detail.get("allow_past_responses") is False:
        flags.append("no past reports")
    if detail.get("allow_future_responses") is False:
        flags.append("no future reports")
    if flags:
        lines.append("Options: " + ", ".join(flags))
    privacy: Any = detail.get("privacy")
    if privacy:
        lines.append(f"Privacy: {privacy}")
    return lines


def print_checkin_detail(detail: dict[str, Any]) -> None:
    """Display a check-in from the canonical ``/detail/`` endpoint.

    Consumes ``{name, schedule, questions, participants, report_channels,
    is_archived}`` with the canonical question shape shared with forms.
    """
    name: str = str(detail.get("name") or "")
    uuid: str = resource_uuid(detail)
    lines: list[str] = [f"[bold]{name}[/bold]", f"UUID: {uuid}"]
    if detail.get("is_archived"):
        lines.append("[yellow]archived[/yellow]")
    schedule: dict[str, Any] = detail.get("schedule") or {}
    days: Any = schedule.get("days")
    if days is not None:
        lines.append(f"Days: {days}")
    for label, key in (("Time", "time"), ("Timezone", "timezone")):
        value: Any = schedule.get(key)
        if value:
            lines.append(f"{label}: {value}")
    lines.extend(_checkin_config_lines(detail))
    console.print(Panel("\n".join(lines), title="Check-in", border_style="cyan"))

    _print_participants(detail.get("participants") or {})
    _print_attached_channels(detail.get("report_channels") or [])

    questions: list[dict[str, Any]] = detail.get("questions") or []
    if not questions:
        print_info("No questions defined for this check-in.")
        return
    console.print(_question_rows(questions))


def _checkin_response_participant(response: dict[str, Any]) -> str:
    """Best-effort participant label for a check-in response row."""
    user: Any = response.get("user")
    if isinstance(user, dict):
        return str(user.get("full_name") or user.get("name") or user.get("email") or "").strip()
    return str(response.get("user_full_name") or response.get("user_name") or "").strip()


def print_checkin_history_table(responses: list[dict[str, Any]]) -> None:
    """Display a check-in's response history over a date range."""
    if not responses:
        print_info("No responses found in that range.")
        return
    # Check-in history defaults to all participants; show a Participant column only
    # when the payload carries who authored each response (single-user views stay clean).
    show_participant: bool = any(_checkin_response_participant(r) for r in responses)
    table: Table = Table(title=f"Response history ({len(responses)})", border_style="cyan")
    table.add_column("Date")
    if show_participant:
        table.add_column("Participant")
    table.add_column("Completed")
    table.add_column("Answers")
    for response in responses:
        raw_date: str = str(response.get("response_date") or "")
        if not raw_date:
            raw_date = str(response.get("created_at") or "")[:10]
        completed: str = "yes" if response.get("response_completed") else "no"
        answers: list[dict[str, Any]] = response.get("responses") or []
        summary: str = "; ".join(
            str(answer.get("response") or "") for answer in answers if answer.get("response")
        )
        row: list[str] = [raw_date or "—"]
        if show_participant:
            row.append(_checkin_response_participant(response) or "—")
        row.extend([completed, (summary[:80] or "—")])
        table.add_row(*row)
    console.print(table)


def print_forms_table(forms: list[dict[str, Any]]) -> None:
    """Display visible forms in a table."""
    if not forms:
        print_info("No forms visible to you.")
        return

    show_status: bool = any(form.get("is_archived") for form in forms)
    table: Table = Table(title="Forms", border_style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Form UUID", style="dim")
    table.add_column("Questions", style="dim", justify="right")
    if show_status:
        table.add_column("Status")
    for form in forms:
        form_id: str = resource_uuid(form)
        if not form_id:
            continue
        question_count: int = len(
            form.get("questions") or form.get("template_questions") or form.get("fields") or []
        )
        count_str: str = str(question_count) if question_count else "—"
        row: list[Any] = [str(form.get("name", "")), form_id, count_str]
        if show_status:
            row.append(
                Text("archived", style="yellow")
                if form.get("is_archived")
                else Text("active", style="green")
            )
        table.add_row(*row)
    console.print(table)


def print_form_submit_result(form_name: str, data: dict[str, Any]) -> None:
    """Display the result of submitting a form response."""
    response_id: str = resource_uuid(data) or "N/A"
    print_success(f'Form response submitted for "{form_name}"')
    print_info(f"Response ID: {response_id}")


def print_kudos_result(receiver_name: str, data: dict[str, Any]) -> None:
    """Display the result of giving kudos."""
    kudos_id: str = resource_uuid(data) or "N/A"
    print_success(f"Kudos sent to {receiver_name}")
    print_info(f"Kudos ID: {kudos_id}")


def _state_label_lookup(form_data: dict[str, Any]) -> dict[str, str]:
    """Map workflow state key → human label using the form's workflow_config."""
    config: Any = form_data.get("workflow_config") or {}
    states: Any = config.get("states") if isinstance(config, dict) else []
    if not isinstance(states, list):
        return {}
    return {str(s.get("key")): str(s.get("label") or s.get("key")) for s in states if s.get("key")}


def _audience_label(audience: Any) -> str:
    """Render a form permission audience (``who_can_edit`` etc.) for the panel."""
    if not isinstance(audience, dict):
        return str(audience or "")
    mode: str = str(audience.get("mode") or "")
    if mode == "restricted":
        users: int = len(audience.get("user_uuids") or [])
        teams: int = len(audience.get("team_uuids") or [])
        return f"restricted ({users} user(s), {teams} team(s))"
    return mode


def _form_workflow(form_data: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    """Return (enabled, states) from the canonical nested ``workflow`` object."""
    workflow: Any = form_data.get("workflow")
    if isinstance(workflow, dict):
        return bool(workflow.get("enabled")), list(workflow.get("states") or [])
    return False, []


def print_form_detail(form_data: dict[str, Any]) -> None:
    """Render a form payload — metadata, config, workflow states, and questions."""
    table: Table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Name", str(form_data.get("name", "")))
    table.add_row("UUID", resource_uuid(form_data))
    if form_data.get("is_active") is False:
        table.add_row("Status", "[yellow]inactive[/yellow]")
    if form_data.get("is_archived"):
        table.add_row("Status", "[yellow]archived[/yellow]")
    enabled, states = _form_workflow(form_data)
    table.add_row("Workflow", "[green]enabled[/green]" if enabled else "disabled")
    if enabled:
        table.add_row(
            "Reopen from final",
            "yes" if form_data.get("allow_reopen_from_final_state") else "no",
        )
    if form_data.get("command_enabled") and form_data.get("command"):
        table.add_row("Command", f"@dailybot {form_data.get('command')}")
    behaviors: list[str] = []
    if form_data.get("is_anonymous"):
        behaviors.append("anonymous")
    if form_data.get("allow_public_responses"):
        public: str = "public"
        if form_data.get("brand_with_logo"):
            public += " +brand"
        if form_data.get("require_email_and_name"):
            public += " +identity"
        behaviors.append(public)
    if form_data.get("use_for_approval"):
        behaviors.append("approval flow")
    if behaviors:
        table.add_row("Settings", ", ".join(behaviors))
    if form_data.get("public_url"):
        table.add_row("Public URL", str(form_data.get("public_url")))
    for label, key in (
        ("Can edit", "who_can_edit"),
        ("Can see", "who_can_see_responses"),
        ("Can change states", "who_can_change_states"),
    ):
        audience: str = _audience_label(form_data.get(key))
        if audience:
            table.add_row(label, audience)
    console.print(Panel(table, title="[bold]Form[/bold]", border_style="cyan"))

    _print_attached_channels(form_data.get("report_channels") or [])

    if enabled and states:
        states_table: Table = Table(title="Workflow States", border_style="cyan")
        states_table.add_column("Order", style="dim", justify="right")
        states_table.add_column("Key", style="bold")
        states_table.add_column("Label")
        states_table.add_column("Color", style="dim")
        for index, state in enumerate(states):
            states_table.add_row(
                str(state.get("order", index)),
                str(state.get("key", "")),
                str(state.get("label", "")),
                str(state.get("color", "")),
            )
        console.print(states_table)

    questions: list[dict[str, Any]] = list(form_data.get("questions", []) or [])
    if questions:
        console.print(_question_rows(questions))


def print_form_response_state(
    data: dict[str, Any], form_data: dict[str, Any] | None = None
) -> None:
    """Render the workflow-state surface of a form response after a mutation."""
    response_id: str = resource_uuid(data)
    current_state: str = str(data.get("current_state") or "")
    state_history: list[dict[str, Any]] = list(data.get("state_history") or [])
    previous_state: str = ""
    last_note: str = ""
    if state_history:
        last_entry: dict[str, Any] = state_history[-1]
        previous_state = str(last_entry.get("from_state") or "")
        last_note = str(last_entry.get("note") or "")

    allowed: list[dict[str, Any]] = list(data.get("allowed_transitions") or [])
    can_change: Any = data.get("can_change_state")

    labels: dict[str, str] = _state_label_lookup(form_data or {})

    def label_for(key: str) -> str:
        return labels.get(key, key) if key else ""

    table: Table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Response", response_id)

    state_cell: str = label_for(current_state) or current_state or "(none)"
    if previous_state and previous_state != current_state:
        state_cell = (
            f"{state_cell}  [dim](from {label_for(previous_state) or previous_state})[/dim]"
        )
    table.add_row("Current state", state_cell)

    if last_note:
        table.add_row("Note", last_note)

    if allowed:
        # Show the state key, not the label: the key is the token `form transition`
        # accepts. The label follows in parens when it differs.
        def state_token(entry: dict[str, Any]) -> str:
            key: str = str(entry.get("to_state") or "")
            label: str = str(entry.get("label") or label_for(key))
            if label and label.lower() != key.lower():
                return f"{key} [dim]({label})[/dim]"
            return key

        next_states: str = ", ".join(state_token(entry) for entry in allowed)
        table.add_row("Next states", f"{next_states}  [dim](use `dailybot form transition`)[/dim]")

    if can_change is not None:
        table.add_row("You can change", "yes" if can_change else "no")

    console.print(Panel(table, title="[bold]Form Response[/bold]", border_style="green"))


def print_form_responses_table(
    form_uuid: str,
    responses: list[dict[str, Any]],
    form_data: dict[str, Any] | None = None,
) -> None:
    """Render the response list for a form."""
    if not responses:
        print_info(f"No responses on form {form_uuid}.")
        return

    labels: dict[str, str] = _state_label_lookup(form_data or {})
    table: Table = Table(title="Form Responses", border_style="cyan")
    table.add_column("Response UUID", style="dim")
    table.add_column("Current state")
    table.add_column("Edited")
    table.add_column("Created", style="dim")
    for response in responses:
        state_key: str = str(response.get("current_state") or "")
        state_display: str = labels.get(state_key, state_key) if state_key else "—"
        edited_flag: bool = bool(response.get("edited"))
        table.add_row(
            resource_uuid(response),
            state_display,
            "yes" if edited_flag else "no",
            str(response.get("created_at") or ""),
        )
    console.print(table)


def print_form_response_detail(
    data: dict[str, Any],
    form_data: dict[str, Any] | None = None,
) -> None:
    """Render a single response payload — workflow surface + answers + history."""
    print_form_response_state(data, form_data)

    content: Any = data.get("content")
    if isinstance(content, dict) and content:
        ans_table: Table = Table(title="Answers", border_style="cyan")
        ans_table.add_column("Question UUID", style="dim")
        ans_table.add_column("Answer")
        for question_uuid, answer in content.items():
            ans_table.add_row(str(question_uuid), str(answer))
        console.print(ans_table)

    history: list[dict[str, Any]] = list(data.get("state_history") or [])
    if history:
        labels: dict[str, str] = _state_label_lookup(form_data or {})
        hist_table: Table = Table(title="State History", border_style="dim")
        hist_table.add_column("When", style="dim")
        hist_table.add_column("From")
        hist_table.add_column("To")
        hist_table.add_column("Actor")
        hist_table.add_column("Note")
        for entry in history:
            from_key: str = str(entry.get("from_state") or "")
            to_key: str = str(entry.get("to_state") or "")
            hist_table.add_row(
                str(entry.get("at") or ""),
                labels.get(from_key, from_key) if from_key else "—",
                labels.get(to_key, to_key) if to_key else "—",
                str(entry.get("actor_name") or ""),
                str(entry.get("note") or ""),
            )
        console.print(hist_table)


def print_form_response_deleted(form_uuid: str, response_uuid: str) -> None:
    """Confirmation after a successful response delete."""
    print_success(f"Response {response_uuid} deleted (form {form_uuid}).")


def print_teams_table(teams: list[dict[str, Any]]) -> None:
    """Display teams visible to the caller."""
    if not teams:
        print_info("No teams visible to you. Org admins see all teams; members see only their own.")
        return

    table: Table = Table(title="Teams", border_style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Team UUID", style="dim")
    table.add_column("Members", justify="right")
    table.add_column("Active")
    for team in teams:
        active_value: Any = team.get("active")
        active_display: str = "yes" if active_value or active_value is None else "no"
        members_count: Any = team.get("members_count")
        if members_count is None:
            members_raw: Any = team.get("members") or team.get("memberships")
            members_count = len(members_raw) if isinstance(members_raw, list) else "—"
        table.add_row(
            str(team.get("name") or team.get("uuid") or ""),
            str(team.get("uuid") or ""),
            str(members_count),
            active_display,
        )
    console.print(table)


def print_team_detail(team: dict[str, Any], members: list[dict[str, Any]] | None = None) -> None:
    """Display a single team with optional member list."""
    table: Table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Name", str(team.get("name") or ""))
    table.add_row("UUID", str(team.get("uuid") or ""))
    active_value: Any = team.get("active")
    if active_value is not None:
        table.add_row("Active", "yes" if active_value else "no")
    if team.get("is_default") is not None:
        table.add_row("Default team", "yes" if team.get("is_default") else "no")
    console.print(Panel(table, title="[bold]Team[/bold]", border_style="cyan"))

    if members is not None:
        if not members:
            print_info("No members on this team.")
            return
        m_table: Table = Table(title="Members", border_style="cyan")
        m_table.add_column("Name", style="bold")
        m_table.add_column("User UUID", style="dim")
        m_table.add_column("Email", style="dim")
        for member in members:
            m_table.add_row(
                str(member.get("full_name") or member.get("name") or member.get("uuid") or ""),
                str(member.get("uuid") or ""),
                str(member.get("email") or ""),
            )
        console.print(m_table)


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


def _choice_labels(question: dict[str, Any]) -> list[str]:
    """Extract display labels from a canonical ``choices`` list.

    The contract returns ``choices`` as ``[{"label", "value"}]`` on every read
    path; a bare-string element is tolerated defensively but not expected.
    """
    raw: Any = question.get("choices") or []
    if not isinstance(raw, list):
        return []
    labels: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            label: Any = item.get("label") or item.get("value")
            if label:
                labels.append(str(label))
        elif item:
            labels.append(str(item))
    return labels


def _question_rows(questions: list[dict[str, Any]]) -> Table:
    """Build a questions table shared by the authoring renderers.

    Every authoring/read endpoint returns the canonical question shape
    (``uuid`` / ``index`` / ``question`` / ``question_type`` / ``required`` /
    ``is_blocker`` / ``choices``), so no field-name normalization is needed.
    Multiple-choice options render as a dim line under the question text.
    """
    table: Table = Table(title="Questions", border_style="cyan")
    table.add_column("#", justify="right")
    table.add_column("Question")
    table.add_column("Type")
    table.add_column("Required")
    table.add_column("Blocker")
    table.add_column("Question UUID", style="dim")
    for index, question in enumerate(questions):
        question_cell: Text = Text(str(question.get("question", "")), style="bold")
        labels: list[str] = _choice_labels(question)
        if labels:
            question_cell.append("\n" + ", ".join(labels), style="dim")
        short_q: Any = question.get("short_question")
        if short_q and str(short_q) != str(question.get("question", "")):
            question_cell.append(f"\n↳ report title: {short_q}", style="dim")
        variations: Any = question.get("variations")
        if variations:
            question_cell.append(f"\n↳ {len(variations)} variation(s)", style="dim")
        if question.get("logic"):
            question_cell.append("\n↳ conditional logic", style="dim")
        blocker_cell: Text = (
            Text("yes", style="red") if question.get("is_blocker") else Text("—", style="dim")
        )
        table.add_row(
            str(question.get("index", index)),
            question_cell,
            str(question.get("question_type", "")),
            "yes" if question.get("required", True) else "no",
            blocker_cell,
            str(question.get("uuid", "")),
        )
    return table


def print_report_channels(channels: list[dict[str, Any]]) -> None:
    """Display the reporting channels available to the caller."""
    if not channels:
        print_info("No report channels available.")
        return
    table: Table = Table(title=f"Report Channels ({len(channels)})", border_style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Platform")
    table.add_column("UUID", style="dim")
    for channel in channels:
        table.add_row(
            str(channel.get("name") or ""),
            str(channel.get("platform") or ""),
            str(channel.get("uuid") or channel.get("id") or ""),
        )
    console.print(table)


def print_form_created(form: dict[str, Any], *, updated: bool = False) -> None:
    """Display a created (or, with ``updated=True``, edited) form + question summary."""
    name: str = str(form.get("name") or "")
    form_id: str = resource_uuid(form)
    title: str = "Form Updated" if updated else "Form Created"
    lines: list[str] = [f"[bold]{name}[/bold]", f"ID: {form_id}"]
    if form.get("public_url"):
        lines.append(f"Public URL: {form.get('public_url')}")
    console.print(Panel("\n".join(lines), title=f"[bold]{title}[/bold]", border_style="green"))
    questions: list[dict[str, Any]] = form.get("questions") or []
    if questions:
        console.print(_question_rows(questions))


def print_checkin_created(checkin: dict[str, Any], *, updated: bool = False) -> None:
    """Display a created (or, with ``updated=True``, edited) check-in + summary."""
    name: str = str(checkin.get("name") or "")
    checkin_id: str = str(checkin.get("id") or checkin.get("uuid") or "")
    lines: list[str] = [f"[bold]{name}[/bold]", f"ID: {checkin_id}"]
    schedule: dict[str, Any] = checkin.get("schedule") or {}
    if schedule:
        days: Any = schedule.get("days")
        if days is not None:
            lines.append(f"Days: {days}")
        for label, key in (("Time", "time"), ("Timezone", "timezone")):
            value: Any = schedule.get(key)
            if value:
                lines.append(f"{label}: {value}")
    title: str = "Check-in Updated" if updated else "Check-in Created"
    console.print(Panel("\n".join(lines), title=f"[bold]{title}[/bold]", border_style="green"))
    questions: list[dict[str, Any]] = checkin.get("questions") or []
    if questions:
        console.print(_question_rows(questions))


def print_question(question: dict[str, Any]) -> None:
    """Display a single question after an add/update."""
    console.print(_question_rows([question]))


def print_questions_table(questions: list[dict[str, Any]]) -> None:
    """Display a form/check-in's questions."""
    if not questions:
        print_info("No questions defined.")
        return
    console.print(_question_rows(questions))


def print_archived(kind: str, uuid: str) -> None:
    """Confirm that a form or check-in was archived (soft-deleted)."""
    print_success(f"{kind.capitalize()} {uuid} archived.")


def print_reordered(kind: str, order: list[str]) -> None:
    """Confirm that questions were reordered."""
    print_success(f"{kind.capitalize()} questions reordered ({len(order)} items).")
