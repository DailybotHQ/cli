# Product Spec — Dailybot CLI

## What is the Dailybot CLI?

The **Dailybot CLI** is a Python command-line tool that bridges **humans** and **agents** with the [Dailybot](https://www.dailybot.com) platform — Dailybot's value proposition outside of chat platforms (Slack, Microsoft Teams, Google Chat, Discord, web).

It is a **public, open-source product** distributed through PyPI, Homebrew, and a self-contained Linux binary. It is the only direct, scriptable surface AI agents and CI pipelines have onto Dailybot.

## Target Users

### Humans
- Developers who run daily standups in Dailybot
- Engineers who want to submit check-ins from the terminal without context-switching
- Users on platforms where the Dailybot chat integration is unavailable or impractical

### Agents
- **AI coding assistants** (Claude Code, Cursor AI, OpenAI Codex, Google Gemini, GitHub Copilot, Antigravity, etc.) — submit progress reports as they complete work
- **CI/CD pipelines** (GitHub Actions, GitLab CI, Jenkins) — report deployment milestones, build status, smoke-test results
- **Deploy scripts and bots** — emit health checks, register webhooks for inbound events, send agent-to-agent messages
- **Standalone agents** — register an autonomous Dailybot organization without a human account, get a free `@mail.dailybot.co` email, and operate independently

## Feature Set

### Human-Facing

| Feature | Command | Notes |
|---------|---------|-------|
| Email-OTP login | `dailybot login` | Interactive (prompted) or non-interactive (`--email --code`) |
| Multi-org account support | `dailybot login --org=<uuid>` | Org list cached locally between step 1 and step 2 |
| Logout (revoke token) | `dailybot logout` | Best-effort revocation; clears local credentials |
| View pending check-ins | `dailybot status` | Lists today's pending follow-ups with their questions |
| Verify auth | `dailybot status --auth` | Tries OTP login first, then API key |
| Submit a free-text update | `dailybot update "<message>"` | Dailybot AI parses and routes to the matching follow-ups |
| Submit a structured update | `dailybot update --done X --doing Y --blocked Z` | Bypasses AI parsing |
| List pending check-ins | `dailybot checkin list` | Pending follow-ups for today with question details |
| Complete a check-in | `dailybot checkin complete <uuid>` | Interactive or `--answer` flags; type-aware prompts |
| List forms | `dailybot form list` | All visible forms with question count |
| Submit a form | `dailybot form submit <uuid>` | Guided per-question prompts or `--content` JSON |
| Give kudos | `dailybot kudos give --to "Name"` | Resolves receiver by name or UUID; team-visible |
| List team members | `dailybot user list` | Name + UUID; emails not exposed |
| Interactive TUI | `dailybot` (no args) | Grouped menu: Check-ins, Forms, Team, Session |

### Agent-Facing

| Feature | Command | Notes |
|---------|---------|-------|
| Configure named profile | `dailybot agent configure --name "..." [--key ...]` | Stored in `~/.config/dailybot/agents.json` |
| List profiles | `dailybot agent profiles` | Shows masked keys and which is default |
| Standalone registration | `dailybot agent register --org-name "..." --agent-name "..."` | No human account needed; gets a free agent email + claim URL |
| Submit activity report | `dailybot agent update "<content>"` | Optional `--milestone`, `--json-data`, `--metadata`, `--co-authors` |
| Report health | `dailybot agent health --ok|--fail|--status [--message ...]` | Used as health check + delivery ack for pending messages |
| Register webhook | `dailybot agent webhook register --url ... [--secret ...]` | Receives messages via POST + `X-Webhook-Secret` |
| Unregister webhook | `dailybot agent webhook unregister` | |
| Send message to agent | `dailybot agent message send --to "..." --content "..." [--type ...]` | Types: `text` (default), `command`, `system` |
| List messages | `dailybot agent message list [--pending]` | `--pending` filters to undelivered |
| Mark messages read | `dailybot agent message claim <id>...` | |
| Mark all delivered | `dailybot agent message claim-all` | Implemented as a health check that drains pending |
| Send transactional email | `dailybot agent email send --to ... --subject ... --body-html ...` | Replies arrive as `agent message`s |

### Configuration & Plumbing

| Feature | Command | Notes |
|---------|---------|-------|
| Store API key | `dailybot config key=<KEY>` | Saved to `~/.config/dailybot/config.json` (`0o600`) |
| Show stored API key (masked) | `dailybot config key` | |
| Remove stored API key | `dailybot config key=` (empty) | |
| Override API URL | `--api-url <URL>` (root flag) | Or `DAILYBOT_API_URL` env var; useful for staging |
| Show CLI version | `dailybot --version` | |

## Authentication Methods

The CLI supports four credential sources, resolved in this order for **agent commands**:

1. `--profile <name>` (explicit profile from `agents.json`)
2. Default profile (from `agents.json`)
3. `DAILYBOT_API_KEY` environment variable
4. Stored API key (`dailybot config key=...`)
5. Login session Bearer token (`dailybot login`)

For **human commands** (`status`, `update`, `logout`) and **user-scoped commands** (`checkin`, `form`, `kudos`, `user`), only the login session Bearer token is supported. These commands call `require_bearer_auth()` which checks `get_token()` and exits with code 3 if not logged in.

For **standalone agent registration**, no authentication is required — agents complete a math challenge to prove they're not bots.

## Distribution Channels

| Channel | Audience | Triggered by |
|---------|----------|--------------|
| **PyPI** (`pip install dailybot-cli`) | Python users, CI | Push `v*` git tag |
| **Homebrew tap** (`brew install dailybothq/tap/dailybot`) | macOS users | Push `v*` git tag (after PyPI propagation) |
| **Linux x86_64 binary** (GitHub Releases) | Linux users without Python | Push `v*` git tag (built with PyInstaller in a glibc 2.31 container for broad compat) |
| **Curl installer** (`curl -sSL https://cli.dailybot.com/install.sh | bash`) | First-time installs | Always serves latest; routes to `brew` (macOS), binary (Linux x86_64), or `pipx`/`uv`/`pip` fallback |

## Non-Goals

The following are **not** in scope for this repo:

- **Direct Slack / Microsoft Teams / Discord / Google Chat integration.** All chat platform routing is handled server-side by the Dailybot API. The CLI only talks to the Dailybot API.
- **Local persistence beyond credentials/profiles/config.** No local DB, no caching of follow-ups, no offline mode.
- **Real-time streaming.** No WebSockets, no SSE, no long-poll. Inbound messages arrive via the registered webhook (out-of-process) or are pulled via `dailybot agent message list`.
- **Plugin system.** All commands are first-party. Adding a command means a PR to this repo.

## Versioning Policy

This project follows **semver-ish** but lives in `0.x.y` — every release is permitted to introduce minor breaking changes if necessary. We aim to:

- Bump **patch** (`0.4.X`) for bug fixes, doc-only changes, internal refactors with no user-visible behavior change.
- Bump **minor** (`0.X.0`) for new commands, new flags, or non-breaking schema additions.
- Avoid **major** (`X.0.0`) until the API surface is considered stable; breaking changes get a clear deprecation note in the GitHub Release.

The version source-of-truth is `pyproject.toml::project.version`. The runtime reads it via `importlib.metadata.version("dailybot-cli")` — see `dailybot_cli/__init__.py`.
