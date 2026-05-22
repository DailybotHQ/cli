# Display & Output Best Practices

All user-facing output flows through `dailybot_cli/display.py`. This document explains why and how.

## Two Consoles, Two Streams

```python
console: Console = Console()                  # stdout
error_console: Console = Console(stderr=True) # stderr
```

| Helper | Goes to | Style |
|--------|---------|-------|
| `print_success` | stdout | `[bold green]OK[/bold green] {message}` |
| `print_info` | stdout | `[dim]{message}[/dim]` |
| `print_warning` | stdout | `[bold yellow]Warning:[/bold yellow] {message}` |
| `print_error` | **stderr** | `[bold red]Error:[/bold red] {message}` |

**Why stderr matters.** Users pipe Dailybot CLI output into other tools:

```bash
dailybot agent message list --pending | jq '.[] | .id'
```

If errors went to stdout, an auth failure would corrupt the JSON pipe. Sending errors to stderr means failures stay visible without polluting the data stream.

## Always Use Helpers

```python
# ✅ CORRECT
print_success(f"Logged in as {email} ({org_name})")
print_info("Check your inbox.")
print_error("Not logged in. Run: dailybot login")

# ❌ WRONG
print(f"Logged in as {email}")           # raw print → no color, no stderr split
click.echo(f"Logged in as {email}")      # bypasses Rich
console.print("[red]Error[/red]: ...")   # wrong stream + duplicates `print_error` logic
```

**Documented exception**: `auth.py::_print_org_list` uses `click.echo(...)` for the org list lines because they need to remain unstyled and pipeable (so users can copy/paste UUIDs out). If you find yourself wanting the same, document the why with a short comment.

## Specialized Renderers

Don't reinvent panels and tables in command code. The existing helpers cover most needs:

| Helper | Renders |
|--------|---------|
| `print_auth_status(data)` | Auth panel with email + org + uuid |
| `print_pending_checkins(checkins)` | One panel per pending follow-up with numbered questions |
| `print_agent_health(data)` | Health panel + history table + pending messages |
| `print_pending_agent_messages(messages)` | Inbox list with `[id:...]` prefixes |
| `print_webhook_result(data)` | Webhook registration panel |
| `print_agent_messages(messages)` | Inbox table |
| `print_agent_message_sent(data)` | Sent-message panel |
| `print_agent_email_sent(data)` | Sent-count panel |
| `print_agent_profiles(profiles)` | Profile table with masked keys |
| `print_registration_result(data)` | Registration panel + claim URL |
| `print_update_result(data)` | Update receipt with attached follow-ups |
| `print_users_table(users)` | Team members table (Name + UUID, no email) |
| `print_forms_table(forms)` | Forms table (Name + UUID + Questions count) |
| `print_checkin_list(checkins)` | Pending check-ins table with question count |
| `print_kudos_result(name, data)` | Kudos sent confirmation panel |
| `print_form_submit_result(data)` | Form submission confirmation panel |
| `print_checkin_complete_result(data)` | Check-in completion confirmation panel |

If you need a new shape, add a helper here rather than building it inline.

## Markup Escaping

Rich treats `[...]` as markup. User-supplied content (message IDs, agent names) MUST be escaped:

```python
def _format_sender(msg: dict[str, Any]) -> str:
    sender_type: str = msg.get("sender_type", "")
    sender_name: str = msg.get("sender_name") or ""
    if sender_name:
        return f"\\[{sender_type}] {sender_name}:"   # escaped [
    if sender_type:
        return f"\\[{sender_type}]:"
    return ""
```

The `\\[` renders as a literal `[` without Rich trying to interpret it. Apply the same pattern any time you embed external strings inside text that Rich will parse.

## Status Spinners

Wrap every HTTP call:

```python
with console.status("Submitting update..."):
    result: dict[str, Any] = client.submit_update(...)
```

Status text is short, imperative, present-continuous. Examples used in the codebase:

- `"Sending verification code..."`
- `"Verifying code..."`
- `"Logging out..."`
- `"Submitting update..."`
- `"Fetching..."`
- `"Submitting agent report..."`
- `"Fetching agent health..."`
- `"Registering webhook..."`
- `"Sending message..."`
- `"Marking messages as read..."`
- `"Fetching pending check-ins..."`
- `"Submitting check-in..."`
- `"Fetching forms..."`
- `"Submitting form response..."`
- `"Resolving receiver..."`
- `"Sending kudos..."`
- `"Fetching team members..."`

If a call is fast (<100ms typical), a spinner is still preferred — it provides feedback that the CLI is actually doing something even on slow networks.

## Masking Secrets

Always mask any secret before displaying or returning it:

```python
def _mask(value: str) -> str:
    if len(value) <= 4:
        return value[0] + "****" if value else "****"
    return value[:4] + "****"
```

Used by `dailybot config key` and `dailybot agent profiles`. Never display a full API key, Bearer token, or webhook secret.

## Tables

```python
table: Table = Table(show_header=False, box=None, padding=(0, 2))
table.add_column(style="bold")
table.add_column()
table.add_row("Email", email)
table.add_row("Organization", org_name)
console.print(Panel(table, title="[bold]Auth Status[/bold]", border_style="green"))
```

Conventions:
- `box=None` for "table-as-layout" inside a panel; default boxing for true data tables.
- `padding=(0, 2)` for label/value layouts.
- `border_style="green"` for success panels, `"red"` for errors, `"yellow"` for warnings, `"cyan"` for neutral lists.

## Panels

```python
console.print(Panel(content, title="[bold]Title[/bold]", border_style="green"))
```

Use panels for "results of an action" (registration result, message sent, auth status). Use tables alone for "lists of things" (messages, profiles).

## When NOT to Render

Don't print success messages for trivial operations (a no-op `--auth` check passes silently). Print success when:

- A side effect occurred (login, logout, register, configure, update sent, message sent, webhook registered).
- The user asked for status (status, health, profiles, messages list).
- An error was caught and the user needs to know to retry.

Avoid:
- Echoing back the user's input ("You said: ...")
- Confirming intermediate steps ("Step 1 complete")
- Verbose progress dumps unless behind a `--verbose` flag (we don't have one yet)

## Adding a New Display Helper

1. Pick a name: `print_<thing>` or `print_<thing>_<verb>` (e.g., `print_agent_message_sent`).
2. Place it in `dailybot_cli/display.py` next to similar helpers.
3. Take the API response dict as the only argument; do not import API types — use `dict[str, Any]`.
4. Default to a `Panel` for "results of an action", a `Table` for "list of things".
5. Document the helper in [API_REFERENCE.md](API_REFERENCE.md) if it's the canonical renderer for an endpoint.
