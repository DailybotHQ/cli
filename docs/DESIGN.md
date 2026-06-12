# DESIGN.md — Dailybot CLI design system

> Interface-design context for AI coding agents. When generating or editing any user-facing output in this repo — every panel, table, status spinner, success/error line, or interactive prompt — follow this file. Prefer the named tokens and helpers below over ad-hoc values.
>
> **Profile present:** `cli-output` (the styled terminal interface). The product's outbound chat/email messaging is documented separately in the [Dailybot agent skill pack](../.agents/skills/dailybot/) (`report/`, `chat/`, `email/`); a `conversational` profile is not adopted here today.

## Overview

The Dailybot CLI is a **terse, calm, single-purpose terminal interface** that bridges humans and AI agents with the Dailybot platform. The product personality in the terminal is **operator-friendly, never chatty** — every line earns its place. Output is rendered via [`rich`](https://rich.readthedocs.io/) through a central display module ([`dailybot_cli/display.py`](../dailybot_cli/display.py)) that owns every semantic color, panel, table, and spinner the CLI emits. **All user-facing output goes through that module** — no raw `print()`, no inline `click.echo()` for styled text, no per-command rendering. This file documents the conventions that module enforces, so any new command's output stays aligned with what users already recognize.

## Output voice & intent

- **Terse and imperative.** Status messages are short, present-continuous: `"Fetching..."`, `"Submitting check-in..."`, `"Sending verification code..."`. Never `"Now I will fetch the data for you"`.
- **English only**, no emoji in output. The brand name in user-facing strings is exactly **"Dailybot"** (lowercase `b`) — `DailyBot` is a legacy spelling and is never used in new output. See `AGENTS.md` Rule 13.
- **Action-oriented prefixes**, never editorial. Success starts with `OK`. Errors start with `Error:`. Warnings start with `Warning:`. Info has no prefix; it is rendered `dim`.
- **No echo-back, no narration.** Don't print "You said: X" or "Step 1 complete." Print success when a side effect happened, when the user explicitly asked for status, or when an error needs user action — and stay silent otherwise.
- **One-line success, multi-line details only when needed.** Confirmation of a side effect is one line via `print_success`; richer artifacts (a panel showing what was created, an ID, a URL) are added below only when the user genuinely needs them to continue.

## Semantic colors & styles

Every color in the CLI maps to a **semantic role**, never a raw aesthetic choice. The roles below are the real styles defined in [`dailybot_cli/display.py`](../dailybot_cli/display.py); do not introduce new color tokens outside this table.

| Role | Style (real `rich` markup) | Used for |
|------|----------------------------|----------|
| `success` | `[bold green]OK[/bold green] {message}` | Side effect completed (`print_success`) |
| `error` | `[bold red]Error:[/bold red] {message}` | Failure, recoverable or not — **always to stderr** (`print_error`) |
| `warning` | `[bold yellow]Warning:[/bold yellow] {message}` | Recoverable issue, soft notice (`print_warning`) |
| `info` | `[dim]{message}[/dim]` | Neutral secondary detail, no prefix (`print_info`) |
| `highlight` | `[bold]{value}[/bold]` | Emphasize a name, count, ID, email inside a table or panel |
| `accent` | `[cyan]{value}[/cyan]` | Links and copy-paste commands; `[bold cyan]` for claim URLs |
| `dim` | `[dim]{value}[/dim]` | Secondary table columns (UUIDs, timestamps, labels) |
| `state.ok` | `[green]yes[/green]` / `[green]up-to-date[/green]` / `[green]enabled[/green]` | Positive state cells inside tables |
| `state.warn` | `[yellow]no[/yellow]` / `[yellow]update available[/yellow]` | Negative-but-recoverable state cells |
| `state.bad` | `[bold red]…[/bold red]` | Hard failure state inside a table (rare; mostly inside `print_agent_health`) |

**Panel border styles** follow the same semantic rule:

| `border_style` | When |
|----------------|------|
| `green` | Successful side effect — auth status, message sent, email sent, kudos confirmation, registration, webhook registered, chat message sent/updated |
| `cyan` | Neutral information surface — version panel, pending check-ins, forms / form details, profiles, response history |
| `yellow` | Soft warning state (used inside `print_agent_health` when health is `unknown`) |
| `red` | Hard failure surface — currently only `print_agent_health` when `status == "unhealthy"` |
| `dim` | Secondary history table inside a richer panel composition |

The `Dailybot Automations` brand panel header is **always** `border_style="cyan"` with the title `[bold]…[/bold]` — see `print_version_info` for the canonical example.

## Output components

Real component inventory, named after the actual helpers in [`dailybot_cli/display.py`](../dailybot_cli/display.py). Reuse these by name; do not build new shapes inline in command callbacks.

**Semantic one-liners** (the four primitives — every other helper composes from these or from `rich` directly):

- **`print_success(message)`** — confirmation of a side effect (one line, stdout).
- **`print_error(message)`** — failure (one line, **stderr** so it does not corrupt piped output).
- **`print_warning(message)`** — recoverable issue (one line, stdout).
- **`print_info(message)`** — secondary detail (one dimmed line, stdout).

**Action-result panels** (one rectangular surface confirming "this happened, here's what was created"):

- **`print_registration_result(data)`** — panel after `dailybot agent register`, includes the **claim URL** as the bold-cyan accent line.
- **`print_webhook_result(data)`** — panel after `dailybot agent webhook`.
- **`print_agent_message_sent(data)`** / **`print_agent_email_sent(data)`** / **`print_chat_message_result(data)`** — panels after outbound send / update operations; the chat helper also lists `Thread reply N` rows when threading is used.
- **`print_auth_status(data)`** — auth panel after `dailybot status --auth`.
- **`print_checkin_complete_result(name, data)`** / **`print_form_submit_result(name, data)`** / **`print_kudos_result(name, data)`** — `print_success` plus a `print_info` line with the response ID. (These are the canonical "minimalist" confirmation pattern — prefer this over a full panel when the only payload of interest is an ID.)

**List surfaces** (tables alone, no surrounding panel):

- **`print_pending_agent_messages(messages)`** — inbox with `\[id:…]` prefixes; trailing `dim` hint about `dailybot agent message claim <id>`.
- **`print_agent_messages(messages)`** — full inbox table.
- **`print_agent_profiles(profiles)`** — profile table with **masked API keys** (`_mask` helper).
- **`print_checkin_list_overview(count, checkins)`** / **`print_forms_table(forms)`** / **`print_users_table(users)`** / **`print_teams_table(teams)`** / **`print_form_responses_table(...)`** — entity lists with name + UUID + relevant counts.

**Composite surfaces** (panels containing tables, or sequences of related panels — for richer payloads):

- **`print_version_info(...)`** — the `Dailybot CLI` version panel with optional update-check + upgrade-command list.
- **`print_pending_checkins(checkins)`** — one panel per check-in, with numbered questions and an inline `[blocker]` red tag for blocker questions.
- **`print_agent_health(data)`** — health panel + recent-history table + delegates to `print_pending_agent_messages` for the inbox tail.
- **`print_form_detail(form_data)`** — form panel + workflow-states table + questions table.
- **`print_form_response_state(data, form_data)`** — workflow-state panel printed after `form submit` / `update` / `transition`.
- **`print_form_response_detail(data, form_data)`** — single-response view (workflow surface + answers table + state-history table).
- **`print_resolved_profile(resolved)`** — table showing each resolved field plus its source provenance (CLI flag vs repo profile vs global vs env).

**Status spinner** (`console.status("…")`) — wraps **every** HTTP call. Spinner text is short, imperative, present-continuous, ending in `...`. The full canonical list is in [`docs/DISPLAY_OUTPUT_BEST_PRACTICES.md`](DISPLAY_OUTPUT_BEST_PRACTICES.md); when adding a new HTTP call, pick a verb from that catalogue (`"Fetching..."`, `"Submitting..."`, `"Sending..."`, `"Verifying..."`, `"Resolving..."`, `"Registering..."`, `"Logging out..."`, `"Marking messages as read..."`).

**Interactive prompts / pickers** — handled by [`questionary`](https://questionary.readthedocs.io/) inside `commands/interactive.py` and `commands/user_scoped_actions.py`. The CLI does not embed pickers inline in command callbacks; the interactive TUI is its own surface.

**Secret rendering** — secrets (API keys, Bearer tokens) MUST go through the `_mask` helper before any output: `value[:4] + "****"` (or `value[0] + "****"` for ≤ 4-char values). Never print a full credential. See `dailybot config key` and `dailybot agent profiles` for canonical usage.

## Layout conventions

- **Two consoles, two streams.** `console = Console()` writes to **stdout**; `error_console = Console(stderr=True)` writes to **stderr**. Errors always flow through `print_error` so they hit stderr and do not corrupt piped JSON or copy-pasteable lists.
- **`Panel` vs `Table` decision rule.** Use a `Panel` for "result of an action" (a side effect completed — registration, send, update). Use a bare `Table` for "list of things" (inbox, profiles, forms, teams). When a panel needs structured key/value content inside, use `Table(show_header=False, box=None, padding=(0, 2))` as the layout primitive — that is the canonical pattern (see `print_auth_status` for the canonical example).
- **Border style picks the panel's voice.** Choose from the table in [Semantic colors & styles](#semantic-colors--styles); never set a border color inline that isn't in that table.
- **Title formatting in panels.** Wrap the title in `[bold]…[/bold]` markup explicitly; rely on the panel itself for the surrounding chrome.
- **Blank lines** before secondary information inside composite output. `print_version_info` adds a `console.print()` before the upgrade-command list when an update is available; follow the same one-blank-line rhythm when separating "result" from "next steps."
- **Width handling.** Do not set explicit widths on tables or panels (`expand=False` is used for the version panel specifically because it should hug its content; tables otherwise expand to terminal width). `rich` adapts automatically.
- **No `print()` ladders.** If you find yourself emitting three or more `console.print(...)` calls in sequence inside a command callback, that is the signal to add (or call) a helper in `display.py` instead.

## Degradation & environment

- **stdout / stderr discipline.** All success/info/warning/panel/table output goes to **stdout**. All errors go to **stderr**. This split is load-bearing: it lets users pipe `dailybot agent message list --pending | jq '.[] | .id'` and still see auth failures on the terminal without corrupting the JSON stream.
- **`NO_COLOR` env var.** Honored natively by `rich` — colors are stripped when `NO_COLOR` is set (any value). No special handling needed in display.py; the markup tokens degrade automatically to plain text.
- **TTY detection.** `rich` auto-detects whether stdout is a TTY and strips ANSI escapes when piped to a file or another process. Spinners (`console.status`) similarly downgrade to silent rendering when not on a TTY. There is no manual `sys.stdout.isatty()` check in display.py today — `rich` owns that decision.
- **Documented exception: `_print_org_list`.** Inside `commands/auth.py`, the multi-org selection helper uses `click.echo(...)` instead of `console.print(...)` to emit `uuid    name` lines as **plain unstyled output**, so users can copy-paste UUIDs cleanly. This is the only sanctioned exception to the "always go through `display.py`" rule, and the rationale is documented inline. If you find yourself needing the same plain-pipeable shape for a new helper, document the why with a short comment and prefer adding a helper to `display.py` if possible.
- **Exit codes.** Commands exit `1` on user-facing errors (after `print_error(...); raise SystemExit(1)`). Never `sys.exit(...)` from library code. The `hook` command group is a special case — it always exits `0` per the agent-harness contract, never blocks the calling agent (see [`docs/AGENT_HOOKS.md`](AGENT_HOOKS.md)).
- **No `--quiet` / `--json` modes today.** The CLI does not currently offer a structured output mode for machine consumption (an `--auth` flag on `status` returns 0/1 silently as the only proxy). If you introduce one, document the new mode here and ensure it bypasses `console.status` spinners and panels in favor of pure JSON to stdout.
- **Pending message rendering.** `print_pending_agent_messages` uses `\[id:…]` brackets deliberately — the leading backslash escapes `rich`'s markup parser so the literal `[` survives. The same pattern applies anywhere external content gets composed into a string that `rich` will parse (see `_format_sender` for the canonical helper).

## Do's and Don'ts

- **DO** route every user-facing line through a helper in [`dailybot_cli/display.py`](../dailybot_cli/display.py). The only sanctioned exception is `_print_org_list` (see [Degradation & environment](#degradation--environment)).
- **DO** pick a semantic style by its **role** (`success`, `error`, `warning`, `info`, `highlight`, `accent`, `dim`) — never by eyeballing a `rich` color name.
- **DO** wrap every HTTP call in `console.status("…")` with imperative present-continuous text. Even fast calls benefit from the spinner — it tells the user the CLI is doing something.
- **DO** send errors to **stderr** via `print_error`, and use `raise SystemExit(1)` to exit. Never `sys.exit(...)` and never `console.print("[red]Error[/red]:…")` (it bypasses `print_error` and lands on stdout).
- **DO** escape user-supplied content with `\\[` when embedding it in a string `rich` will parse. See `_format_sender` for the canonical helper.
- **DO** mask every credential with `_mask(value)` before printing or returning it. First 4 characters + `****`; for ≤ 4-char values, first character + `****`.
- **DO** spell the product name **"Dailybot"** (lowercase `b`) in every user-facing string. `DailyBot` is the legacy spelling and is forbidden in new output. (Python identifiers like `DailyBotClient` are intentional and stable — they predate the rebrand. The rule is user-facing strings only. See `AGENTS.md` Rule 13.)

- **DON'T** use raw `print(...)` for user-facing output. Raw `print` bypasses `rich`, has no `NO_COLOR` handling, and lands on the wrong stream for errors.
- **DON'T** use `click.echo(...)` for styled output. Except for the documented `_print_org_list` case, `click.echo` bypasses the semantic-color layer and creates drift.
- **DON'T** invent a new panel border color outside the [border-style table](#semantic-colors--styles). Stick to `green` / `cyan` / `yellow` / `red` / `dim`.
- **DON'T** add a `console.status(...)` spinner around a local computation that completes in < 100ms. Spinners are for HTTP and other genuinely-slow work; flickering them around fast local work is noise.
- **DON'T** print a success confirmation for trivial no-op operations (e.g., `status --auth` exits 0 silently when auth is fine). Only print success when a side effect happened, when the user explicitly asked for status, or when an error was caught and the user needs to know.
- **DON'T** echo back what the user just typed ("You said: X") or narrate intermediate steps ("Step 1 complete"). Be terse.
- **DON'T** print a full API key, Bearer token, or webhook secret. Always mask. See `dailybot config key` and `dailybot agent profiles` for canonical masked rendering.
- **DON'T** assume color is the only carrier of meaning. Every semantic role above pairs color with a **textual prefix** (`OK`, `Error:`, `Warning:`) or a **structural cue** (table column, panel title) so the output stays unambiguous when piped to a file, when `NO_COLOR` is set, or for a colorblind reader.
- **DON'T** rely on the legacy `dailybot-progress-report` skill name — that path was renamed during the v1.7.x sync. The canonical path is [`.agents/skills/dailybot/report/SKILL.md`](../.agents/skills/dailybot/report/SKILL.md), and the reporting voice rules live there (1–3 sentences, focus on WHAT + WHY, never "Agent completed…", no file paths or git stats).

## Agent prompt guide

**For coding agents working in this repo:** this `DESIGN.md` is the source of truth for every user-facing line the Dailybot CLI emits in the terminal. Before generating or editing any output:

1. **Use the named tokens and helpers in this file.** Pick a semantic role (`success` → `print_success`; `error` → `print_error`; `warning` → `print_warning`; `info` → `print_info`); pick a border style by role (success → `green`; neutral list → `cyan`; warning → `yellow`; failure → `red`). Do not introduce ad-hoc colors or panel borders.
2. **Respect the layered architecture.** All output goes through [`dailybot_cli/display.py`](../dailybot_cli/display.py) — never raw `print(...)`, never `click.echo` for styled text. If the shape you need doesn't exist as a helper, add one to `display.py` next to similar helpers, then call it from your command.
3. **Keep integrity intact.** Errors must go to **stderr** (`print_error` handles this — don't bypass it). Secrets must be masked (`_mask` helper — never print raw credentials). User-supplied content embedded in `rich` markup must be escaped (`\\[` — see `_format_sender`). Color is never the only carrier of meaning; pair it with a textual prefix or a structural cue so piped output and `NO_COLOR` output stay legible.
4. **Match the documented patterns.** Wrap every HTTP call in `console.status("…")` with imperative present-continuous text. Use `Panel` for "result of an action," bare `Table` for "list of things," `Table(show_header=False, box=None, padding=(0, 2))` for label/value layouts inside a panel. Confirm side effects with one line via `print_success` plus an optional `print_info` line for an ID — prefer this minimalist pattern over a full panel for trivial confirmations.
5. **When something isn't covered**, choose the option most consistent with the conventions here and note the gap in your PR description rather than inventing an unrelated style. Then update this `DESIGN.md` and [`docs/DISPLAY_OUTPUT_BEST_PRACTICES.md`](DISPLAY_OUTPUT_BEST_PRACTICES.md) together so the next agent finds the convention codified.

Suggested instruction to paste into an agent prompt for any task that produces user-facing output:

> Follow `docs/DESIGN.md` strictly. Build the output using its semantic roles (`print_success` / `print_error` / `print_warning` / `print_info` / `console.status` / `Panel` with the documented border styles), keep the integrity rules intact (errors to stderr, secrets masked, markup escaped, color never the only signal), and reuse the named helpers in `dailybot_cli/display.py` instead of inventing new ones.

---

**Related references.** Background on why every helper is shaped the way it is lives in [`docs/DISPLAY_OUTPUT_BEST_PRACTICES.md`](DISPLAY_OUTPUT_BEST_PRACTICES.md) (the operational rules). Performance budgets that constrain rendering decisions (when to spinner, when not to) live in [`docs/PERFORMANCE.md`](PERFORMANCE.md). The vendored design-system addon that generated the shape of this file is [`.agents/skills/deepworkplan/addons/design-system/`](../.agents/skills/deepworkplan/addons/design-system/) — re-run it (`/deepworkplan-addon-design-system`) after substantial changes to `display.py` to refresh this document.
