# AGENTS.md - Documentation for AI Agents

**Purpose:** Single source of truth for all AI coding assistants (Claude Code, Cursor AI, OpenAI Codex, Google Gemini, GitHub Copilot, and others) working on the Dailybot CLI. Notice we write **"Dailybot"** for user-facing content or documentation, not "DailyBot".

> **Read this first.** Skim the [Project Overview](#project-overview), [Project Structure](#project-structure), and [Mandatory Rules](#critical-mandatory-rules) before touching code. Deeper reference material lives in [`docs/`](docs/).

## Detailed Documentation

| Category | Document |
|----------|----------|
| Product Spec | [docs/PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md) |
| Architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Testing | [docs/TESTING_GUIDE.md](docs/TESTING_GUIDE.md) |
| Development Commands | [docs/DEVELOPMENT_COMMANDS.md](docs/DEVELOPMENT_COMMANDS.md) |
| API Reference | [docs/API_REFERENCE.md](docs/API_REFERENCE.md) |
| CLI Command Best Practices | [docs/CLI_COMMAND_BEST_PRACTICES.md](docs/CLI_COMMAND_BEST_PRACTICES.md) |
| Display & Output Best Practices | [docs/DISPLAY_OUTPUT_BEST_PRACTICES.md](docs/DISPLAY_OUTPUT_BEST_PRACTICES.md) |
| Security | [docs/SECURITY.md](docs/SECURITY.md) |
| Configuration & Credentials | [docs/CONFIGURATION.md](docs/CONFIGURATION.md) |
| Release & Distribution | [docs/RELEASE_AND_DISTRIBUTION.md](docs/RELEASE_AND_DISTRIBUTION.md) |
| Repository Standards | [docs/STANDARDS.md](docs/STANDARDS.md) |
| Python Guidelines | [docs/DEVELOPMENT_GUIDELINES.md](docs/DEVELOPMENT_GUIDELINES.md) |
| Documentation Guide | [docs/DOCUMENTATION_GUIDE.md](docs/DOCUMENTATION_GUIDE.md) |
| AI Agent Onboarding | [docs/AI_AGENT_ONBOARDING.md](docs/AI_AGENT_ONBOARDING.md) |
| AI Agent Collaboration | [docs/AI_AGENT_COLLAB.md](docs/AI_AGENT_COLLAB.md) |
| Ecosystem Context | [docs/ECOSYSTEM_CONTEXT.md](docs/ECOSYSTEM_CONTEXT.md) |
| PR Review Workflow | [docs/PR_REVIEW_WORKFLOW.md](docs/PR_REVIEW_WORKFLOW.md) |
| Troubleshooting | [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |
| Skills Catalog | [.agents/docs/skills_agents_catalog.md](.agents/docs/skills_agents_catalog.md) |

## Project Overview

**Dailybot CLI** is a Python command-line tool that bridges **humans** and **agents** with the [Dailybot](https://www.dailybot.com) platform. It provides:

- **For humans** — email-OTP login, viewing pending check-ins, submitting structured/free-text updates, interactive TUI mode.
- **For agents (AI assistants, CI jobs, deploy scripts, bots)** — progress reports, milestone tracking, agent health, webhook registration, agent-to-agent messaging, transactional email, and standalone agent registration (creates an org without a human Dailybot account).

It talks exclusively to the Dailybot HTTP API under `/v1/cli/*` and `/v1/agent*/*` endpoints. There is no local database; all state is either in `~/.config/dailybot/` (credentials, agent profiles, config) or fetched from the API.

**Stack:** Python 3.10+, [Click](https://click.palletsprojects.com/) 8.3+, [httpx](https://www.python-httpx.org/) 0.28+, [questionary](https://questionary.readthedocs.io/) 2.1+, [rich](https://rich.readthedocs.io/) 15+. Tested with `pytest`. Built and packaged with `setuptools`; distributed via PyPI, Homebrew tap (`dailybothq/tap`), a PyInstaller-built Linux x86_64 binary, and a PowerShell installer (`install.ps1`) that wraps `pipx`/`uv`/`pip` for native Windows users.

## Project Structure

```
dailybot_cli/                # Source package
├── __init__.py              # Package version (read from installed metadata)
├── main.py                  # Click root group + entry point (`dailybot`)
├── api_client.py            # DailyBotClient + APIError (httpx wrapper)
├── config.py                # Credentials, agent profiles, config files in ~/.config/dailybot/
├── display.py               # Rich console output helpers (panels, tables, status)
└── commands/
    ├── __init__.py
    ├── auth.py              # login / logout (email OTP, multi-org)
    ├── status.py            # pending check-ins + --auth status
    ├── update.py            # submit human check-in update
    ├── config.py            # get/set/remove stored settings (api_key)
    ├── interactive.py       # questionary-based TUI when run with no args
    ├── version.py           # `dailybot version` — install info + PyPI update check
    ├── upgrade.py           # `dailybot upgrade` — auto-detect install method + self-update
    └── agent.py             # `agent` group: configure, profiles, register,
                             #   update, health, webhook, message, email

tests/                       # pytest suite (file naming: *_test.py)
├── api_client_test.py       # HTTP client mocking
├── commands_test.py         # Click CliRunner invocations
└── config_test.py           # Config/credential file management

.github/workflows/release.yml  # Tag-triggered: PyPI + Linux binary + Homebrew
install.sh                     # Curl-piped installer (macOS brew, Linux binary, pip fallback)
pyproject.toml                 # Package metadata, deps, entry point
pytest.ini                     # `python_files = *_test.py`, testpaths = tests
```

## Runtime Environment - IMPORTANT

**This project does NOT require Docker.** It is a plain Python package. All commands run on the host.

Verify your environment before working:

```bash
python --version          # >= 3.10
pip install -e ".[dev]"   # editable install (note: [dev] extra may need to be added if missing)
pip install -e .          # plain editable install if no [dev] extra is defined yet
pytest                    # run the suite
dailybot --version        # confirm the CLI is on PATH
```

If `dailybot` is not on PATH after `pip install -e .`, your virtualenv may not be activated, or the `--user` install dir may not be in PATH. See [docs/DEVELOPMENT_COMMANDS.md](docs/DEVELOPMENT_COMMANDS.md) and [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

> **Never run `pip install` against the user's system Python without their consent.** Always use a virtualenv, `pipx`, or `uv tool` for development.

## CRITICAL: Mandatory Rules

### 1. English Only
All code, comments, docstrings, log messages, error messages, commit messages, and documentation MUST be in English. The CLI is a public open-source product distributed worldwide.

### 2. Type Hints (MANDATORY)

ALL Python code MUST use type hints. **If you generate code without type hints, you MUST add them before the code is complete.** This is enforced both by convention and by reviewer expectations.

```python
# ✅ CORRECT — all parameters, return types, and local variables annotated
from typing import Any

def submit_report(content: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"content": content}
    if metadata:
        payload["metadata"] = metadata
    return payload

# ❌ WRONG — never generate untyped code
def submit_report(content, metadata=None):
    payload = {"content": content}
    if metadata:
        payload["metadata"] = metadata
    return payload
```

Use modern syntax (`requires-python = ">=3.10"`): `list[str]` and `dict[str, Any]` (not `List`/`Dict`), `X | None` for nullable (PEP 604, not `Optional[X]`), `X | Y` for unions (not `Union[X, Y]`), `tuple[str, ...]` for click multi-options. `ruff check --fix` enforces this. See [docs/DEVELOPMENT_GUIDELINES.md](docs/DEVELOPMENT_GUIDELINES.md).

### 3. Import Order (MANDATORY)

```python
# 1. Python stdlib
import json
import os
from pathlib import Path
from typing import Any

# 2. Third-party
import click
import httpx
import questionary
from rich.console import Console

# 3. Internal project
from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.config import get_token, save_credentials
from dailybot_cli.display import print_error, print_success
```

The order is **three tiers**: `stdlib → third-party → internal`. See [docs/STANDARDS.md](docs/STANDARDS.md).

### 4. Test File Naming
**ALWAYS `*_test.py`**, NEVER `test_*.py`. This is enforced by `pytest.ini` (`python_files = *_test.py`). See [docs/TESTING_GUIDE.md](docs/TESTING_GUIDE.md).

### 5. Layered Architecture (Click → Service-Like Helpers → API Client)

Click command callbacks are thin coordinators. They:
1. Parse and validate flags/arguments.
2. Resolve auth context (`_resolve_agent_context`, `_require_auth`).
3. Call the `DailyBotClient` (HTTP) or a local helper.
4. Hand the result to a `display.py` function for rendering.

**Do not embed business logic, JSON shaping, or rich rendering directly inside command callbacks.** Helpers in `display.py` own all output; `api_client.py` owns all HTTP. See [docs/CLI_COMMAND_BEST_PRACTICES.md](docs/CLI_COMMAND_BEST_PRACTICES.md).

### 6. TDD Workflow
1. Write or update a `*_test.py` covering the new behavior first.
2. Run `pytest path/to/test.py::TestClass::test_method` → confirm it fails (Red).
3. Implement the minimal code change.
4. Re-run the targeted test → confirm it passes (Green).
5. Refactor if needed; then run the full suite (`pytest`).

### 7. Mock All HTTP in Tests

Tests MUST NEVER hit the real Dailybot API. Patch `httpx.get` / `httpx.post` / `httpx.patch` / `httpx.request` at the call site (`dailybot_cli.api_client.httpx.<method>`), or instantiate `DailyBotClient` with a `MagicMock(spec=DailyBotClient)`. See [docs/TESTING_GUIDE.md](docs/TESTING_GUIDE.md).

### 8. Click Conventions

- Prefer `click.pass_context` only when sharing state (e.g., the `--profile` flag set on the `agent` group).
- Use `--flag/-f` short options consistently (`-n` name, `-p` profile, `-d` metadata, `-j` json-data, `-m` milestone, `-c` co-authors).
- Multi-value flags use `multiple=True` and arrive as `tuple[str, ...]`.
- Always provide `\b` blocks in docstrings for example sections — Click preserves their formatting in `--help`.
- Exit on user-facing errors with `print_error(...)` then `raise SystemExit(1)`. Never `sys.exit(...)` directly inside library code.

### 9. Output Through `display.py` Only

Never use raw `print(...)` or `click.echo(...)` for user-facing output (one exception: `_print_org_list` uses `click.echo` for plain UUID/name lines that must remain unstyled and machine-pipeable). All success/error/info/warning text and all tables/panels go through helpers in `dailybot_cli/display.py`. Errors print to **stderr** (`error_console`); everything else to **stdout** (`console`). See [docs/DISPLAY_OUTPUT_BEST_PRACTICES.md](docs/DISPLAY_OUTPUT_BEST_PRACTICES.md).

### 10. HTTP Errors Through `APIError`

`api_client.py` raises `APIError(status_code, detail)` for any non-2xx response. Command callbacks **must** wrap `client.*(...)` calls in `try/except APIError` and translate them to user-friendly messages. Special-case `e.status_code in (401, 403)` to suggest `dailybot login`, and `e.status_code == 429` to suggest waiting / rate-limit messaging.

### 11. Credentials & Secrets — File Permissions

Any file in `~/.config/dailybot/` that stores secrets (`credentials.json`, `config.json`, `agents.json`) MUST be written with mode `0o600` (owner read/write only). When adding a new on-disk store, copy the existing pattern in `dailybot_cli/config.py`:

```python
PATH.write_text(json.dumps(data, indent=2))
os.chmod(PATH, 0o600)
```

Never log full API keys or Bearer tokens. Use the `_mask` helper (or equivalent: first 4 chars + `****`).

### 12. No Magic Numbers
Extract limits, timeouts, and counts into module-level constants:

```python
# ✅ CORRECT
DEFAULT_TIMEOUT_SECS: float = 30.0
LONG_TIMEOUT_SECS: float = 120.0   # for AI-processing endpoints

# ❌ WRONG
response = httpx.post(url, timeout=120.0)  # what is 120 for?
```

`api_client.py` already follows this for the read timeout vs. submit timeout split. The challenge constants in `commands/agent.py` (`_CHALLENGE_WORD_COUNT`) follow the same pattern.

### 13. Brand Name Spelling (MANDATORY)

The product name in **user-facing text** is **"Dailybot"** (lowercase 'b'). "DailyBot" (capital 'B') is the legacy spelling — never use it in new user-facing strings.

**Applies to:** CLI help text, docstrings, success/error messages, README user-facing copy, panel titles, prompts.

**Does NOT apply to:** Python identifiers (`DailyBotClient` is intentional and stable — it predates the rebrand), GitHub org/repo paths (`DailyBotHQ/cli`, `dailybothq/tap`), HTTP headers, env var names, or any internal contract.

```python
# ✅ CORRECT — user-facing string
print_success(f"Logged in as {email} ({org_name})")
help="Your Dailybot account email."

# ❌ WRONG — legacy spelling in user-facing string
help="Your DailyBot account email."

# ✅ OK — code identifier (not user-facing)
class DailyBotClient: ...
```

### 14. Auth Resolution Order (Do Not Break)

The agent commands resolve credentials in this strict order — changing it is a **breaking change** for users:

1. `--profile` flag (explicit profile from `~/.config/dailybot/agents.json`)
2. `<repo>/.dailybot/profile.json::profile` — the closest ancestor of `$PWD` containing this file pins a profile slug for everyone working in the repo
3. Default profile from `agents.json`
4. `DAILYBOT_API_KEY` environment variable
5. `dailybot config key=...` (stored in `~/.config/dailybot/config.json`)
6. Login session (Bearer token from `~/.config/dailybot/credentials.json`)

The repo file may also pin the agent display name (`name`) and a `default_metadata` object that gets shallow-merged into every report. **Credentials never live in the repo file** — a `key` field in `.dailybot/profile.json` is a hard error. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the per-field precedence and the security rule.

The implementation lives in `dailybot_cli/commands/agent.py::_resolve_agent_context` and `dailybot_cli/api_client.py::_agent_headers`. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

### 15. Packaging & Versioning

- The CLI version is read at runtime from installed package metadata (`importlib.metadata.version("dailybot-cli")`) — see `dailybot_cli/__init__.py`.
- The single source of truth is `pyproject.toml::project.version`. **Never** hardcode the version anywhere else.
- **Default release path: merge a PR to `main` — that's it.** Every PR is gated by `code_check.yml` (ruff + mypy + pytest matrix on Python 3.10 / 3.12 + a `python -m build` smoke-test). Once that passes and the PR is merged, `auto-release.yml` (powered by `python-semantic-release`) cuts a release **unconditionally**. The bump level is decided by the conventional-commit prefixes when present, but they are **not required** — devs who forget the prefix still ship a PATCH automatically:
  - `feat:` → MINOR (e.g. `1.0.1 → 1.1.0`)
  - `fix:` / `perf:` → PATCH (e.g. `1.0.1 → 1.0.2`)
  - `feat!:` or `BREAKING CHANGE:` in the body → MAJOR (e.g. `1.0.1 → 2.0.0`)
  - any other prefix or no prefix at all → PATCH (because `default_bump_level = 2` in `pyproject.toml` — PSR 10's LevelBump value for PATCH)

  PSR then updates `pyproject.toml::version` + `CHANGELOG.md`, commits as `DailyBot Automations`, tags `vX.Y.Z`, and pushes. The tag push triggers `release.yml`, which fans out to PyPI, the Linux binary, the GitHub Release, and the Homebrew tap.
- Do **NOT** hand-edit `pyproject.toml::version` or `CHANGELOG.md` for normal work — let the automation own them. The two fallback flows (manual `git tag`, local `twine`) are documented for emergencies. See [docs/RELEASE_AND_DISTRIBUTION.md](docs/RELEASE_AND_DISTRIBUTION.md).

### 16. Backward Compatibility for Stored Files

The schemas of `credentials.json`, `config.json`, `agents.json`, and `org_cache.json` are persisted on user machines across CLI upgrades. **Adding** keys is safe; **renaming or removing** keys requires a migration path or a new file name. When introducing a new key, treat its absence as the legacy default in `load_*` functions (see how `api_url` defaults to `DEFAULT_API_URL`).

### 17. Temporary Files Live in `tmp/`

The repo has a top-level `tmp/` directory reserved for any throwaway artifact: scratch notes, draft PR bodies, intermediate command output, downloaded sample payloads, debugging dumps, generated diffs to inspect, etc.

**Rules for AI agents:**

- **Always** drop temporary files inside `tmp/`. Never write scratch files to the repo root, to `docs/`, to `dailybot_cli/`, or anywhere else.
- The folder is gitignored except for `tmp/.gitkeep` (which preserves the empty directory in git). Anything else you put inside is invisible to `git status` and will not be committed by accident.
- Don't promote a file out of `tmp/` unless you've decided it's a real, permanent artifact (and then move it deliberately to its proper home).
- Don't delete `tmp/.gitkeep`.
- If you need a subdirectory for organization (`tmp/pr-bodies/`, `tmp/api-dumps/`), create it freely — everything under `tmp/` is ignored.

This keeps the working tree clean across long agent sessions and avoids accidental commits of generated/scratch content.

## Quick Commands

```bash
# Development
pip install -e .                   # editable install (run inside a venv/pipx/uv env)
pytest                             # full test suite
pytest -k <keyword>                # filter by name
pytest tests/api_client_test.py    # one file
pytest -x                          # stop on first failure

# Linting & type-checking (if/when wired into the project)
ruff check dailybot_cli tests      # if ruff is configured
mypy dailybot_cli                  # if mypy is configured
black dailybot_cli tests           # if black is configured

# Try the CLI locally
dailybot --version
dailybot --help
dailybot --api-url https://staging.dailybot.com login --email me@example.com

# Build artifacts (release path — usually CI handles these)
python -m build                            # sdist + wheel
pyinstaller --onefile --name dailybot \
  --clean dailybot_cli/main.py             # Linux binary
```

See [docs/DEVELOPMENT_COMMANDS.md](docs/DEVELOPMENT_COMMANDS.md) for full reference.

## Common Mistakes

### DON'T

1. Write code/docs/comments in Spanish
2. Write Python without type hints
3. Use `test_*.py` naming (use `*_test.py`)
4. Hit the real Dailybot API in tests — always mock `httpx`
5. Embed business logic or rendering inside Click callbacks (push to `display.py` / `api_client.py`)
6. Use raw `print(...)` for user-facing output — go through `display.py`
7. Print errors to stdout — `print_error` writes to **stderr** for a reason
8. Bypass `APIError` handling in command callbacks (no naked `httpx` exceptions surfacing to users)
9. Hardcode the version anywhere except `pyproject.toml`
10. Hardcode timeouts, limits, or magic strings inline — extract to constants
11. Log or print full API keys / Bearer tokens — always mask
12. Write secret files without `os.chmod(path, 0o600)`
13. Break the auth resolution order in `_resolve_agent_context`
14. Use "DailyBot" (capital 'B') in new user-facing text — use "Dailybot"
15. Add a new dependency without checking the Homebrew tap formula in `.github/workflows/release.yml` (every Python dep there is a `resource` block — adding one means updating the formula)
16. Run `pip install` against the system interpreter — always venv / pipx / uv
17. Re-prompt (`request_code`) before verifying an OTP — it invalidates the previously-sent code (see the cached-org-list pattern in `auth.py`)
18. Call `sys.exit(...)` from library code — `raise SystemExit(N)` from command callbacks only
19. Add a Click flag without a short alias if the existing command in the same group already uses one (consistency)
20. Forget the `\b` marker in Click docstrings — without it, Click reflows your example block
21. Drop scratch files anywhere outside `tmp/` (draft PR bodies, debug dumps, sample payloads, etc.) — see Rule 17
22. **Push directly to `main`** — even a one-line workflow fix or a `pyproject.toml` toggle MUST go through a feature branch + PR + the `code_check.yml` gate. The only exception is the `chore(release): X.Y.Z [skip ci]` commit that `auto-release.yml` itself makes automatically. Force-pushes to `main` are forbidden without explicit, scoped permission for that exact operation.

### DO

1. ALWAYS use type hints (modern syntax: `list[str]`, `X | None`)
2. Name tests `*_test.py`
3. Follow import order: stdlib → third-party → internal
4. Mock `httpx` at the call site in tests
5. Keep Click callbacks thin: parse → resolve → call client → render
6. Funnel all user-facing output through `display.py`
7. Send errors to stderr (`print_error` does this for you)
8. Catch `APIError` in every command callback and translate it
9. Read the version via `importlib.metadata.version("dailybot-cli")`
10. Extract magic numbers/strings into module-level constants
11. Mask secrets in any output (`key[:4] + "****"`)
12. Set `0o600` on every credential/config file you create
13. Preserve the documented auth resolution order; if you must extend it, add at the end and document it
14. Use "Dailybot" (lowercase 'b') in all new user-facing strings
15. Update the Homebrew formula in `release.yml` when adding a new Python dependency
16. Run `pytest -x` before committing
17. When non-interactive flags are required (e.g., `--email --code`), provide a useful error if cached state is missing — see `_verify_non_interactive`
18. Use `print_pending_agent_messages(result.get("pending_messages", []))` after any agent action that returns the pending list — preserves the message inbox UX
19. Use `console.status("...")` around any HTTP call so the user sees a spinner

## Pre-Commit Checklist

- [ ] All code in English with type hints
- [ ] Tests use `*_test.py` naming and pass (`pytest`)
- [ ] External services mocked in tests (no real network calls)
- [ ] Import order follows convention (stdlib → third-party → internal)
- [ ] No raw `print(...)` for user-facing output (use `display.py`)
- [ ] Errors go to stderr, success/info goes to stdout
- [ ] All `client.*` calls wrapped in `try/except APIError`
- [ ] No hardcoded magic numbers or timeouts — use named constants
- [ ] Any new file in `~/.config/dailybot/` has `os.chmod(path, 0o600)`
- [ ] Secrets are masked in all logs and console output
- [ ] User-facing strings use "Dailybot" (not "DailyBot")
- [ ] If a new dependency was added, the Homebrew formula in `.github/workflows/release.yml` is updated
- [ ] If `pyproject.toml::project.version` was bumped, the bump is in its **own commit** named `Version bump`
- [ ] Click `--help` output for any touched command still renders cleanly (run `dailybot <cmd> --help`)
- [ ] Commit message in English (conventional format)

## Commit Message Format

**Format**: `<type>(<scope>): <short description>`

**Types**: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `build`, `ci`

**Scopes**: `auth`, `agent`, `update`, `status`, `config`, `interactive`, `display`, `client`, `cli`, `release`, `tests`, `docs`

```
feat(agent): add --co-authors flag to agent update

## Summary
Allow agents to credit collaborators on a single report.

## Change Log
- Added repeatable --co-authors option (also accepts comma-separated)
- Forwarded co_authors list to /v1/agent-reports/
- Updated print_success to render co-author names
- Added 4 test cases (single, multiple, comma-separated, empty)

## Risks
- None for backwards compat — flag is optional and skipped if empty
```

A simpler short form is acceptable for tiny commits (`fix(release): bump version to 0.4.13`), but the body is preferred for any user-visible behavior change.

## Agent Progress Reporting (Mandatory)

> **ALL AI agents MUST report progress to Dailybot after significant work.** This applies whether the work was on this CLI repo or anywhere else.

The CLI itself **is** the reporting tool — that's the recursion. To report on changes you made to this repository, run the locally-built CLI (or your installed one):

```bash
# After implementing a feature in this repo:
dailybot agent update --name "Claude Code" \
  "Added --co-authors support to dailybot agent update — agents can now credit collaborators on a single report." \
  --metadata '{"model":"claude-opus-4-7","repo":"cli"}'

# After completing a multi-task plan (use --milestone + --json-data):
dailybot agent update --name "Claude Code" --milestone \
  "Built the agent profiles system — named profiles persist auth and default to a slugified agent name across all commands." \
  --json-data '{"completed":["agents.json schema","configure subcommand","profile resolution order","18 test cases"],"in_progress":[],"blockers":[]}' \
  --metadata '{"model":"claude-opus-4-7","plan":"PLAN_agent_profiles","repo":"cli"}'
```

Full philosophy, what to report, and what to skip: [.agents/skills/dailybot-progress-report/SKILL.md](.agents/skills/dailybot-progress-report/SKILL.md). Key rules:

- 1–3 sentences, **always in English**
- Focus on WHAT + WHY, never "Agent completed…"
- Never include file paths, git stats, branch names, raw commit messages
- ~10 meaningful reports/day, not 100
- Send **after committing, before finishing your response** — it's part of completing the work
- Always include `--metadata '{"model":"<your-model>"}'`
- If the local CLI is not authenticated, surface that to the user once and continue working without reporting; never block work on reporting

## Ecosystem Context

The CLI is one of several frontends to the Dailybot platform. It does **not** talk to Slack / Microsoft Teams / Discord / Google Chat directly — it only talks to the Dailybot API, which fans out to chat platforms internally.

```
                  ┌──────────────────────────────┐
   dailybot CLI ──┤        Dailybot API          │── Slack / Teams / Discord / Google Chat / Web
   (this repo)    │  /v1/cli/* and /v1/agent*/*  │
                  └──────────────────────────────┘
```

See [docs/ECOSYSTEM_CONTEXT.md](docs/ECOSYSTEM_CONTEXT.md) for the agent-vs-human endpoint split and how the CLI fits into the platform.

## Reading PR Review Comments (Mandatory)

When applying bot feedback on a PR, agents **must** skip `isMinimized == true` comments and anchor on the most recent `<!-- claude-review-marker -->` comment to identify the authoritative review SHA. Previous reviews are auto-collapsed as `OUTDATED` on every new push, so reading all comments blindly will mix live and stale feedback. Full specification: [docs/PR_REVIEW_WORKFLOW.md](docs/PR_REVIEW_WORKFLOW.md).

## Skills & Agents System

Reusable **Skills** (slash commands) and **Agents** (specialized personas) live under [`.agents/`](.agents/) — the vendor-neutral standard adopted by most coding agents (Claude Code, Cursor, Codex, Gemini, Copilot, …):

- [`.agents/skills/`](.agents/skills/) — slash commands (e.g., `/quick-fix`, `/release-prep`, `/cli-command-add`, `/dailybot-progress-report`)
- [`.agents/agents/`](.agents/agents/) — agent personas (e.g., `cli-developer`, `release-manager`, `docs-writer`, `test-engineer`)
- [`.agents/docs/skills_agents_catalog.md`](.agents/docs/skills_agents_catalog.md) — full index

> `.claude/` at the repo root is a git-tracked **symlink to `.agents/`**, kept so tools that still default to the legacy Claude-specific path keep working unchanged. Edit content under `.agents/` only — never under `.claude/`. **This includes Claude-specific assets** (e.g. `settings.json`, `commands/`, hook scripts): put them in `.agents/` and the symlink will route Claude Code to them. Windows users without `core.symlinks = true` should reference `.agents/` directly.

### Slash Commands Across Agents

| Agent | Prefix | Example |
|-------|--------|---------|
| Claude Code | `/` (native) | `/quick-fix` |
| Codex / Cursor / Gemini | `#` | `#quick-fix` |

When invoked: look up in `.agents/docs/skills_agents_catalog.md`, READ the procedure file, FOLLOW it exactly. Do not improvise.

## Documentation Maintenance

### Single Source of Truth

| Scope | Source |
|-------|--------|
| AI agent rules & navigation for THIS repo | This file (`AGENTS.md`) |
| Detailed reference docs | [`docs/`](docs/) |
| Skills & agent personas | [`.agents/`](.agents/) |
| Release pipeline | [`.github/workflows/release.yml`](.github/workflows/release.yml) |
| Public user-facing docs | [`README.md`](README.md) |
| Package metadata & deps | [`pyproject.toml`](pyproject.toml) |

### Update Responsibilities

- **Code change** — update `AGENTS.md` if a *rule* changes; update `docs/` if a *concept* changes; update `README.md` if user-visible behavior changes.
- **New command** — update `README.md` Commands table, add to `docs/API_REFERENCE.md` (or `docs/CLI_COMMAND_BEST_PRACTICES.md`), and add a test in `tests/commands_test.py`.
- **New dependency** — update `pyproject.toml`, the Homebrew resource list in `.github/workflows/release.yml`, and `docs/RELEASE_AND_DISTRIBUTION.md` if the bundling changes.
- **Schema change to a `~/.config/dailybot/*.json` file** — document the migration path in `docs/CONFIGURATION.md`.
