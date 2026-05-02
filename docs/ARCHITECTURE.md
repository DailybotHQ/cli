# Architecture

## High-Level View

The Dailybot CLI is a **thin Click-based wrapper** around the Dailybot HTTP API. There is no local database, no background worker, no plugin system. The runtime path of every command is short and predictable:

```
┌──────────────────────────────────────────────────────────────────────┐
│ dailybot_cli/main.py                                                 │
│   click.Group("cli") + invoke_without_command → run_interactive()    │
└─────────┬─────────────────────────────────────────────────────┬──────┘
          │                                                     │
          ▼                                                     ▼
┌──────────────────────────────────────────────┐   ┌────────────────────────┐
│ dailybot_cli/commands/*.py                   │   │ commands/interactive.py│
│   (auth, status, update, agent, config)      │   │   questionary-driven   │
│   • Parse args, validate flags               │   │   TUI; calls the same  │
│   • Resolve auth context (profile / token)   │   │   client + display     │
│   • Wrap APIError → user-friendly message    │   │   helpers              │
└────────┬───────────────────────────┬─────────┘   └────────────────────────┘
         │                           │
         ▼                           ▼
┌──────────────────────┐   ┌────────────────────────┐
│ api_client.py        │   │ display.py             │
│   DailyBotClient     │   │   Rich console panels, │
│   • httpx requests   │   │   tables, status       │
│   • _headers /       │   │   spinner, masking,    │
│     _agent_headers   │   │   stderr/stdout split  │
│   • _handle_response │   └────────────────────────┘
│   • Raises APIError  │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│ Dailybot API                                 │
│   /v1/cli/auth/{request-code,verify-code,…}  │
│   /v1/cli/{updates,status}                   │
│   /v1/agent-{reports,health,messages,email,  │
│              webhook}                        │
│   /v1/agent/register/{challenge,}            │
└──────────────────────────────────────────────┘
```

## Module Responsibilities

### `dailybot_cli/main.py`
The entry point. Defines the root `cli` Click group, the `--api-url` override, and `--version`. Registers the top-level commands (`login`, `logout`, `update`, `status`, `agent`, `config`). When invoked with no subcommand, drops into `commands/interactive.py::run_interactive`.

**Key contract:** `--api-url` calls `set_api_url_override(...)` *before* any subcommand runs, so every subsequent `DailyBotClient()` picks up the overridden URL. The override is also exposed via `DAILYBOT_API_URL` env var.

### `dailybot_cli/api_client.py`
The single HTTP boundary. Owns:

- **`DailyBotClient`** — a thin httpx wrapper. Constructor accepts `api_url`, `token`, `api_key`, `timeout` and falls back to `config` lookups when omitted.
- **`APIError(status_code, detail)`** — every non-2xx response becomes one of these. Command callbacks translate them; raw `httpx` exceptions never reach the user.
- **Header helpers**:
  - `_headers(authenticated=True)` — used by **human** endpoints; sends `Authorization: Bearer <token>`.
  - `_agent_headers()` — used by **agent** endpoints; sends `X-API-KEY` if available, falls back to `Authorization: Bearer <token>`. Tracks the chosen mode in `_agent_auth_mode` so `_handle_response` can produce the right error message on 401/403.

**Two different auth schemes.** Human endpoints (`/v1/cli/*`) only accept Bearer tokens. Agent endpoints (`/v1/agent*/*`) accept either. The split is intentional and reflects the platform's security model.

**Two different timeouts.** Most calls use `self.timeout` (default 30s). The `submit_update` call uses 120s because the AI parsing on the backend can take a while. Add new long-running calls to a named constant rather than inlining a number.

### `dailybot_cli/config.py`
The on-disk credential and configuration store. Owns:

- `~/.config/dailybot/credentials.json` — login session (token, email, organization, organization_uuid, api_url)
- `~/.config/dailybot/config.json` — stored settings (currently just `api_key`)
- `~/.config/dailybot/agents.json` — named agent profiles + default-profile pointer
- `~/.config/dailybot/org_cache.json` — temporary cache of the org list during multi-org non-interactive login

Every secret-bearing file is written with `os.chmod(path, 0o600)`.

**Resolution helpers** that the rest of the codebase relies on:

- `get_api_url()` — `--api-url` flag > `DAILYBOT_API_URL` env > credentials > default
- `get_token()` — `DAILYBOT_CLI_TOKEN` env > credentials
- `get_api_key()` — `DAILYBOT_API_KEY` env > stored config
- `get_agent_auth()` — returns `"api_key"`, `"bearer"`, or `None` (purely for early "not authenticated" errors)
- `get_default_profile()` / `get_profile(name)` / `list_profiles()` — agent profile lookups

### `dailybot_cli/display.py`
The user-facing rendering layer. Two distinct `rich.Console` instances:

- `console` — stdout, used for success / info / panels / tables
- `error_console` — **stderr**, used by `print_error(...)`

Every command callback rendering output should go through one of:

- `print_success`, `print_error`, `print_warning`, `print_info`
- Specialized helpers: `print_auth_status`, `print_pending_checkins`, `print_agent_health`, `print_agent_messages`, `print_agent_message_sent`, `print_agent_email_sent`, `print_agent_profiles`, `print_registration_result`, `print_update_result`, `print_pending_agent_messages`, `print_webhook_result`

**Why stderr matters.** Users pipe CLI output into other tools (`dailybot agent message list | jq …`). Errors going to stderr mean failures are visible without polluting the data stream.

**Markup escaping.** Square brackets in user content are escaped with `\\[` so Rich doesn't interpret them as markup. See `_format_sender` for the canonical pattern.

### `dailybot_cli/commands/`

Each module owns one command (or one command group). The shape is consistent:

```python
@click.command()  # or @<group>.command()
@click.option(...)
@click.argument(...)
def <name>(...) -> None:
    """User-facing docstring (Click renders this in --help)."""
    # 1. Validate flag combinations (e.g., exactly one of --ok/--fail/--status)
    # 2. Resolve auth context (profile + client)
    # 3. Parse JSON / shape inputs
    # 4. Wrap client.<method>() in try/except APIError
    # 5. Hand result to display.print_<thing>(...)
```

Specific notes per file:

- **`auth.py`** — login is a 4-step flow (request code → optional org list → enter code → verify-and-save). Three call paths share `_verify_and_save`: interactive, non-interactive step 2 (`_verify_non_interactive`), and the auto-recurse on `requires_organization_selection`. The cached org list (`org_cache.json`) is critical for non-interactive multi-org login — re-calling `request_code` would invalidate the OTP.
- **`status.py`** — two modes: list pending check-ins (default) or verify auth (`--auth`). The `--auth` path tries OTP first, then API key, with carefully tuned error messages.
- **`update.py`** — supports free-text + structured fields. When invoked with no args, falls back to a stdin loop (Enter twice to submit). 401/403 → `dailybot login`; 400 with "ai processing failed" → contact support.
- **`agent.py`** — the largest module. Sub-groups: `webhook`, `message`, `email`. The `_resolve_agent_context` helper centralizes the 5-step auth resolution and is the only function that should be touched if the resolution order needs to change. The `register` command implements a math-challenge handshake (no auth needed).
- **`config.py`** — minimal get/set/remove for stored settings. Only `key` (→ `api_key`) is currently a known setting; adding new ones is a 1-line `KNOWN_SETTINGS` change.
- **`interactive.py`** — questionary-based TUI. Calls into `auth._do_login` if not already authenticated; otherwise loops a four-choice menu.

## Data Flow Examples

### `dailybot login` (interactive, multi-org)

```
user runs `dailybot login`
  │
  ├─ click prompts for --email
  │
  ├─ commands/auth.py::login → _do_login(email)
  │    ├─ DailyBotClient().request_code(email)
  │    │    POST /v1/cli/auth/request-code/  →  { is_multi_org, organizations: [...] }
  │    │
  │    ├─ display._print_org_list(orgs)
  │    ├─ click.prompt for the 6-digit code
  │    ├─ questionary.select an org
  │    └─ _verify_and_save(client, email, code, org_id)
  │         ├─ client.verify_code(...) → { token, organization, organization_uuid }
  │         ├─ config.save_credentials(...)  (chmod 0600)
  │         └─ print_success(f"Logged in as {email} ({org_name})")
```

### `dailybot agent update "..." --milestone --json-data ...`

```
user runs `dailybot agent update "Built X" --milestone -j '{...}'`
  │
  ├─ commands/agent.py::agent_update
  │    ├─ _resolve_agent_context(profile_flag, name_flag)
  │    │    → (agent_name, DailyBotClient(api_key=...))   # or with Bearer fallback
  │    │
  │    ├─ json_mod.loads(json_data)
  │    └─ client.submit_agent_report(agent_name, content, structured, …)
  │         POST /v1/agent-reports/  with X-API-KEY  →  { id, is_milestone, pending_messages: [...] }
  │
  └─ display.print_success("Report submitted (id: …) [Milestone]")
     display.print_pending_agent_messages(pending_messages)   # if any
```

## Cross-Cutting Concerns

### Error Handling
- `APIError` is the **only** exception that command callbacks should expect from `DailyBotClient`. Anything else (OS errors, JSON decode, etc.) is a real bug and should propagate.
- `httpx.TimeoutException` is **separately** caught in `update.py` and `interactive.py` because the AI parsing endpoint has its own user-facing message ("the request timed out, may already be processing").
- Every `print_error(...)` is followed by `raise SystemExit(1)` (for non-interactive cleanliness) — except in interactive mode where we just print and return to the menu.

### Spinners
Every HTTP call should be wrapped in `with console.status("..."):` so the user gets feedback. This is a UX rule, not a hard constraint, but it's followed everywhere in the codebase and the absence of a spinner reads as a regression.

### Type Hints
The codebase uses modern Python typing throughout: `dict[str, Any]`, `list[dict[str, Any]]`, `X | None` (PEP 604, not `Optional[X]`), `tuple[str, ...]`. Annotate all parameters, return types, and meaningful local variables (this is a project convention even where mypy doesn't strictly require it).

## Where to Add Things

| You're adding… | Put it in… |
|----------------|-----------|
| A new command | `dailybot_cli/commands/<name>.py` + register in `main.py` |
| A subcommand of `agent` | `dailybot_cli/commands/agent.py` (add to one of the sub-groups or as a top-level `@agent.command`) |
| A new HTTP endpoint call | `dailybot_cli/api_client.py` (one method per endpoint) |
| A new rendered output | `dailybot_cli/display.py` (one helper per output shape) |
| A new on-disk file | `dailybot_cli/config.py` (matching read/write/clear helpers; chmod 0600) |
| A new env var read | `dailybot_cli/config.py` resolution helper, never inlined elsewhere |
| A test | `tests/<matching>_test.py` (file name mirrors the module under test) |
