# CLI Command Best Practices

The "shape" every command in this repo should have. Read alongside [DEVELOPMENT_GUIDELINES.md](DEVELOPMENT_GUIDELINES.md) (Python idioms) and [DISPLAY_OUTPUT_BEST_PRACTICES.md](DISPLAY_OUTPUT_BEST_PRACTICES.md) (rendering rules).

## The Five-Step Command Pattern

Every Click callback should be structured as five clear phases:

```python
@click.command()
@click.argument("content")
@click.option("--name", "-n", default=None)
@click.option("--profile", "-p", default=None)
@click.pass_context
def agent_update(ctx: click.Context, content: str, name: Optional[str], profile: Optional[str]) -> None:
    """User-facing docstring."""
    # 1. Validate flag combinations
    #    (e.g., exactly one of --ok/--fail/--status)

    # 2. Resolve auth context
    profile_flag: Optional[str] = profile or ctx.obj.get("profile")
    agent_name, client = _resolve_agent_context(profile_flag, name)

    # 3. Parse JSON / shape inputs
    #    (e.g., loads(--json-data), flatten comma-separated --co-authors)

    # 4. Call the API client inside try/except APIError
    try:
        with console.status("Submitting agent report..."):
            result: dict[str, Any] = client.submit_agent_report(...)
    except APIError as e:
        print_error(e.detail)
        raise SystemExit(1)

    # 5. Render the result through display.py
    print_success(f"Report submitted (id: {result.get('id', 'N/A')})")
```

Anything that doesn't fit this shape is either:
- Pure parsing/validation (keep in step 1 or 3)
- Business logic (push into a helper or `api_client.py`)
- Output rendering (push into `display.py`)

## Click Conventions

### Short Flags Must Be Consistent

| Flag | Short | Used For |
|------|-------|----------|
| `--name` | `-n` | Agent worker name |
| `--profile` | `-p` | Profile slug |
| `--metadata` | `-d` | JSON metadata |
| `--json-data` | `-j` | Structured data |
| `--milestone` | `-m` | Milestone marker |
| `--co-authors` | `-c` | Repeatable co-authors |

Pick the same short alias every time you re-use the same long name. If you need a new short alias, check the list above first to avoid collisions inside the same command.

### Help Text Style

- One-line summary: imperative, capitalized, no trailing period.
- Click flag `help="..."` text: short sentence, no period if one-line.

```python
@click.option("--name", "-n", default=None, help="Agent worker name.")
@click.option("--milestone", "-m", is_flag=True, default=False, help="Mark as a milestone accomplishment.")
```

### `\b` Blocks in Docstrings

Click reflows docstrings unless you mark a block as no-fill with `\b`. Always wrap example sections:

```python
def agent_update(...) -> None:
    """Submit an agent activity report.

    \b
      dailybot agent update "Deployed v2.1 to staging"
      dailybot agent update "Built feature X" --name "Claude Code"
      dailybot agent update "Deployed" --profile ci-bot
    """
```

Without the `\b`, Click joins the lines into a paragraph and your examples become unreadable.

### Group-Level State via `ctx.obj`

```python
@click.group()
@click.option("--profile", "-p", default=None)
@click.pass_context
def agent(ctx: click.Context, profile: Optional[str]) -> None:
    ctx.ensure_object(dict)
    ctx.obj["profile"] = profile
```

Subcommands accept their own `--profile` and combine with `ctx.obj`:

```python
profile_flag: Optional[str] = profile or ctx.obj.get("profile")
```

This way `dailybot agent --profile ci-bot update "..."` and `dailybot agent update "..." --profile ci-bot` both work, with the inner flag taking precedence (which mirrors Click's natural argument resolution).

### Mutually-Exclusive Flags

For `agent health --ok / --fail / --status`:

```python
flags: int = sum([report_ok, report_fail, query_status])
if flags != 1:
    print_error("Specify exactly one of --ok, --fail, or --status.")
    raise SystemExit(1)
```

There's no native Click XOR helper — explicit count is the simplest pattern and the existing convention.

## Auth Resolution

Every command that talks to an authenticated endpoint must resolve credentials through one of:

| Endpoint type | Resolution helper | Returns |
|---------------|-------------------|---------|
| Human (Bearer-only) | `_require_auth()` from the command file | `DailyBotClient` |
| Agent (key or Bearer) | `_resolve_agent_context(profile_flag, name_flag)` from `commands/agent.py` | `(agent_name, DailyBotClient)` |

**Do not duplicate the resolution logic.** If a new command needs auth, route through one of these helpers.

For the resolution order specifics, see [CONFIGURATION.md](CONFIGURATION.md).

## Spinner Usage

Wrap every `client.*` call in a `console.status(...)`:

```python
with console.status("Submitting update..."):
    result: dict[str, Any] = client.submit_update(message=message)
```

Status messages are imperative present-continuous: "Submitting…", "Fetching…", "Marking messages as read…". Keep them short — they appear next to a spinner.

## Exiting

```python
# Successful path: just return (Click exits 0 by default)
print_success(f"Logged in as {email}")
return  # implicit

# Error path: SystemExit(1) after printing
print_error("Not logged in. Run: dailybot login")
raise SystemExit(1)
```

Avoid `sys.exit(...)` and never call `os._exit(...)`.

## When to Add a Helper Module

The five command files in `dailybot_cli/commands/` average ~150–650 lines. When a single command is approaching ~250 lines or has multiple distinct responsibilities, consider extracting:

- A pure-function helper into the same file (lowercase `_helper_name`).
- A reusable client method into `api_client.py`.
- A reusable display helper into `display.py`.

Avoid creating a `services/` or `domain/` layer prematurely — the architecture is intentionally flat. The biggest module today, `agent.py`, lives within that flat structure cleanly because each subcommand is independent.

## When to Add a New Command Group

Add a `@click.group` when:

- You have ≥ 3 subcommands sharing a noun (e.g., `agent webhook`, `agent message`, `agent email`).
- The group needs shared state (e.g., a `--profile` flag applied across all subcommands).

If you only have 1–2 related commands, keep them as top-level commands and re-evaluate later.

## When to Use `questionary` vs `click.prompt`

| Use `click.prompt` | Use `questionary` |
|--------------------|-------------------|
| Single-line text input | Selection from a list (radio) |
| Confirm yes/no | Multi-select |
| Password / secret entry | Free-form with custom validators |

`questionary` provides arrow-key navigation; `click.prompt` is fine for everything else. If you find yourself reaching for both in the same flow, prefer `questionary` for consistency (e.g., `commands/interactive.py` uses `questionary` end-to-end).

## Anti-patterns

| Anti-pattern | Fix |
|--------------|-----|
| Embedding `print(...)` or `click.echo(...)` for styled output | Use `display.py` helpers |
| Building Rich tables/panels inside command callbacks | Move to `display.py` |
| Calling `httpx` directly inside a command | Add a method to `DailyBotClient` |
| Reading `~/.config/dailybot/...` files inside a command | Add a helper to `config.py` |
| Reading env vars inside a command | Add a helper to `config.py` (the resolution chain belongs there) |
| Catching `httpx.HTTPError` instead of `APIError` | Let `_handle_response` translate it |
| Returning early without rendering anything on success | Always emit at least a `print_success(...)` confirmation |
| Hardcoding endpoint URLs in commands | URLs belong in `api_client.py` only |
