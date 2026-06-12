# Performance

> Operational performance posture for `dailybot-cli` — what matters, how we measure it, and the budgets we enforce. This is a **library-distributable Python CLI**, not a server, so the relevant axes are *cold-start latency*, *HTTP I/O wisdom*, and *terminal rendering*.

## Why a CLI cares about performance

The CLI runs interactively, often in an agent's harness, often inside CI. The user-visible expectation for every invocation is:

- `dailybot --help` / `dailybot --version` — feels instantaneous (≤ 100 ms wall on a warm shell, single-digit-ms on a hot Python).
- `dailybot status` / `dailybot checkin list` / `dailybot form list` — a clear spinner within ~50 ms, network result within the HTTP budget below.
- `dailybot agent update "…"` — a clear spinner within ~50 ms; submission within the **submit timeout budget** below.
- Agent hooks (`dailybot hook session-start / activity / stop / dismiss`) — **must never block the harness**. Hard ceiling: 200 ms wall, and the implementation must guarantee that exception in the hook degrades to silent no-op (per `commands/hook.py::evaluate_*` contract).

Every degradation against those expectations is a perceptible regression, not a theoretical one — an agent that waits 2 s on `session-start` slows every developer turn.

---

## Budgets

These are the budgets we enforce. They live here so a PR reviewer can cite them.

### 1. Cold-start latency — `dailybot --version`

| Stage | Budget | Why |
|---|---|---|
| Python interpreter startup | not ours to optimize | bounded by the user's interpreter (~10–30 ms typical) |
| `dailybot_cli` import graph | **≤ 100 ms** cumulative | the import graph reaches `click`, `httpx`, `rich`; defer everything else to first-use |
| Total wall (`time dailybot --version`) | **≤ 200 ms** on warm shell | what users notice |

Anti-patterns that break the budget:

- Importing `questionary` / `rich.Live` / `httpx.Client` at module top-level for a command that doesn't use them. Use **lazy imports inside the command callback**.
- Performing **any** HTTP call from `main.py` or from a `Click` group's setup. Network only happens inside an explicit `command.callback`.
- Reading `~/.config/dailybot/agents.json` from `main.py`. Auth resolution belongs inside `_resolve_agent_context`.

### 2. HTTP I/O budgets — `api_client.py`

Two-tier read/submit budget. Defined as module-level constants (per AGENTS.md Rule 12 "No Magic Numbers").

| Class of call | Endpoints | Timeout | Where defined |
|---|---|---|---|
| **Read** (idempotent GET) | `/v1/cli/checkins/`, `/v1/forms/`, `/v1/teams/`, `/v1/users/`, `/v1/agent-messages/` | **`DEFAULT_TIMEOUT_SECS = 30.0`** | `api_client.py` |
| **Submit** (non-idempotent POST/PATCH; may trigger AI-processing server-side) | `/v1/agent-reports/`, `/v1/agent-email/send/`, `/v1/send-message/`, `/v1/cli/checkins/<id>/answer/` | **`LONG_TIMEOUT_SECS = 120.0`** | `api_client.py` |

Rules of thumb:

- **Never** hand-pick a timeout inline at the call site (`httpx.post(url, timeout=120.0)`). Always use one of the two named constants.
- A new endpoint goes in the **read tier by default**; only promote to the submit tier with an explicit comment justifying it (e.g. "endpoint runs AI summarisation server-side").
- Retries are intentionally **not** layered into `api_client.py`. The Dailybot API is idempotent only for the read tier; transparent retry of submits would risk double-posting. If a future read endpoint needs jittered retry, add it as an opt-in helper, not a default.

### 3. Terminal rendering budget — `display.py` / `rich`

`rich` rendering itself is fast. The risk is **shelling spinners around fast operations** (e.g. wrapping a local file read in `console.status("…")` — flicker without value).

| Pattern | Budget / rule |
|---|---|
| `console.status("…")` for any HTTP call | **Always** — even the fastest read benefits visually |
| `console.status("…")` for local-only computation | Forbidden when the computation completes < 100 ms |
| Table rendering of large result sets (`form responses`, `checkin list`) | Acceptable up to ~500 rows; beyond that, paginate server-side, do not page in the client |

### 4. Hook budget — `commands/hook.py`

Hooks run on **every** Claude Code / Cursor lifecycle event (session-start, post-tool-use on file edits, end-of-turn stop). Latency here is *per turn × per file edit*, so it compounds fast.

| Hook | Budget (wall) | What it must NOT do |
|---|---|---|
| `hook session-start` | ≤ 100 ms | network calls, prompting, blocking I/O beyond reading the local ledger |
| `hook activity` | ≤ 50 ms | anything beyond appending a signal to the local ledger |
| `hook post-commit` | ≤ 200 ms (one `git log -1` allowed) | anything beyond reading the latest commit metadata |
| `hook stop` | ≤ 150 ms | network calls; the `decision:block` payload is just a JSON line, not an HTTP round-trip |
| `hook dismiss` | ≤ 50 ms | anything beyond writing the snooze marker to the ledger |

Every hook callback is wrapped in `try: ... except Exception: return` (degrade-to-silence) so a failing hook never breaks the developer's harness — but the wrapper is a safety net, not an excuse to do slow work.

---

## How we measure

Cold-start and command latency are measured with `hyperfine` against an installed editable build:

```bash
pip install -e . hyperfine
hyperfine --warmup 3 'dailybot --version'
hyperfine --warmup 3 'dailybot --help'
hyperfine --warmup 3 'dailybot status' # auth required; runs against staging
```

HTTP timing is read off `httpx`'s `Response.elapsed` and logged on debug runs (`DAILYBOT_DEBUG=1`).

Hook latency is asserted in tests in `tests/hook_commands_test.py` — every hook subcommand has a "fast-exit when no signal" test that uses `subprocess.run(..., timeout=0.5)` as a soft bound.

There is **no production telemetry** — the CLI does not phone home with any timing data. Performance regressions are caught locally and in code review.

---

## When to relax a budget

A budget is not an end in itself. Relax it when (and only when) one of these is true:

1. **A new feature inherently needs more time** (e.g. the AI-processing submit budget was 30 s before agent reports moved to backend AI summarisation; the 120 s ceiling is a concession to that). Document the move in the constant's docstring.
2. **The user explicitly opts into a long-running operation** (e.g. a future `dailybot agent backfill --since 2026-01-01`). Such commands SHOULD print "this may take several minutes" before they spin.
3. **A platform constraint forces it** (e.g. Windows process startup is slower than POSIX; the 200 ms wall is for warm shell on POSIX, not for cold-boot on a CI runner).

Never relax a budget silently. Add a CHANGELOG entry and an updated row in this doc.

---

## Performance bug template

When you suspect a perf regression, file (or open a draft PR with) the following:

```
## Symptom
What command? What was slow? On what hardware / Python / OS?

## Repro
hyperfine --warmup 3 'dailybot <command>'

## Suspected cause
Module-level import? Synchronous wait? Lock contention? Unbounded result set?

## Budget breached
Which budget in docs/PERFORMANCE.md? By how much?

## Proposed fix
The smallest change that restores the budget.
```

See also: [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) for the import graph and module boundaries, [`docs/DEVELOPMENT_COMMANDS.md`](DEVELOPMENT_COMMANDS.md) for the test+lint flow, and [`docs/AGENT_HOOKS.md`](AGENT_HOOKS.md) for the hook contract details.
