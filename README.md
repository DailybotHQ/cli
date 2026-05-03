# Dailybot CLI

The command-line bridge between **humans** and **agents**. [Dailybot](https://www.dailybot.com) connects your team — whether they work in Slack, Google Chat, Discord, Microsoft Teams, or the web — with AI agents and automated workflows. The CLI brings that power to your terminal: progress reports, observability, health checks, messaging, and workflow automation for modern teams.

## Installation.

```bash
pip install dailybot-cli
```

Requires Python 3.10+.

### Alternative installation methods

**macOS (Homebrew)**

```bash
brew install dailybothq/tap/dailybot
```

**Linux, WSL2, or Git Bash on Windows (binary or pip fallback)**

```bash
curl -sSL https://cli.dailybot.com/install.sh | bash
```

**Native Windows PowerShell** (only if you don't have WSL2 or Git Bash)

```powershell
irm https://cli.dailybot.com/install.ps1 | iex
```

Requires Python 3.10+ on PATH. Wraps `pipx` / `uv tool` / `pip --user`.

Or download directly from [GitHub Releases](https://github.com/DailyBotHQ/cli/releases).

## Checking your installed version

The CLI exposes two ways to inspect what's installed — a quick one-liner for scripts and a richer panel for humans:

```bash
# Single-line, scriptable
dailybot --version
# → dailybot 1.0.0 (Python 3.12.4)

# Multi-line panel: version, Python runtime, install path, release notes link
dailybot version

# Same panel, but also queries PyPI to tell you whether a newer version exists
dailybot version --check
```

`dailybot version --check` is the recommended way to find out whether you should upgrade. If a newer release is available, the output lists the upgrade command for each install method (Homebrew, Linux binary, pipx, pip), so you don't need to remember which channel you used to install in the first place.

To upgrade, just run:

```bash
dailybot upgrade
```

The CLI auto-detects how it was installed and either runs the right upgrade command for you (pipx / uv tool / pip) or prints the exact command you should run yourself (Homebrew, Linux binary, editable dev install). Use `dailybot upgrade --dry-run` to preview without executing.

> **Bug reports?** Always include the full output of `dailybot version` — the install path and Python runtime are usually enough to tell us whether the issue is in the CLI itself, in a transitive dep, or in the host environment.

## For humans

Authenticate once with your Dailybot email, then submit updates and check pending check-ins right from your terminal.

```bash
# Log in (interactive, email OTP)
dailybot login

# See what check-ins are waiting for you
dailybot status

# Submit a free-text update
dailybot update "Finished the auth module, starting on tests."

# Or use structured fields
dailybot update --done "Auth module" --doing "Tests" --blocked "None"
```

Run `dailybot` with no arguments to enter **interactive mode** — if you're not logged in yet, it will walk you through authentication first, then let you submit updates step by step.

## For agents

Any software agent — AI coding assistants, CI jobs, deploy scripts, bots — can report activity through the CLI. This lets teams get visibility into what automated processes are doing, alongside human updates. Dailybot interconnects agents and humans with work analysis, progress reports, observability, and automations.

### Authentication

Authenticate with any of these methods (checked in this order):

```bash
# Option 1: Environment variable (CI pipelines, one-off scripts)
export DAILYBOT_API_KEY=your-key

# Option 2: Store the key on disk (recommended for dev machines)
dailybot config key=your-key

# Option 3: Use your login session (no API key needed)
dailybot login
```

### Non-interactive login

AI agents (e.g. Claude Code) and scripts can log in without interactive prompts using a two-step flow:

```bash
# Step 1: request a verification code — ask the user to check their email
dailybot login --email=user@example.com

# Step 2: verify the code the user received by email
dailybot login --email=user@example.com --code=123456

# Multi-org accounts: step 2 prints available organizations with UUIDs.
# Re-run with --org to select one:
dailybot login --email=user@example.com --code=123456 --org=abc-123

# Verify credentials are valid (checks login session, then API key)
dailybot status --auth
```

### Agent profiles

Configure a named agent identity so all agent commands use your preferred name and credentials automatically. Profiles are stored in `~/.config/dailybot/agents.json`.

```bash
# Configure a profile using your login session (no API key needed)
dailybot agent configure --name "Claude Code"

# Configure with an API key (for CI pipelines or dedicated agents)
dailybot agent configure --name "CI Bot" --key your-api-key

# Configure with a custom profile name
dailybot agent configure --name "Claude Code" --profile claude

# List all configured profiles
dailybot agent profiles
```

Once configured, all agent commands use the default profile automatically — no need to pass `--name` every time:

```bash
# Uses the default profile's agent name
dailybot agent update "Deployed v2.1 to staging"

# Override with a specific profile
dailybot agent --profile ci-bot update "Build #42 passed"
```

Auth resolution order:
1. `--profile` flag (explicit profile from `agents.json`)
2. `.dailybot/profile.json::profile` in the current repo (see below)
3. Default profile from `agents.json`
4. `DAILYBOT_API_KEY` environment variable
5. `dailybot config key=...` (stored API key)
6. Login session (Bearer token from `dailybot login`)

### Repo-level profile (`.dailybot/profile.json`)

Commit a tiny config file at the root of your repo so every contributor — and every AI agent running in the repo — signs reports under the same identity, with no per-developer setup. The CLI walks up from `$PWD` looking for `.dailybot/profile.json`; the closest ancestor wins.

```json
{
  "name": "Core Hub Bot",
  "profile": "core-hub-bot",
  "default_metadata": {
    "team": "platform",
    "service": "core-hub"
  }
}
```

All keys are optional:

- **`name`** — overrides the worker display name (same effect as `--name`). Anyone running `dailybot agent update "..."` from the repo signs as `"Core Hub Bot"`.
- **`profile`** — selects which entry of the **global** `agents.json` provides credentials. The repo file's `name` still wins over the global profile's display name. If the slug isn't found locally, the CLI warns once and falls back to your login session — handy for repos that ship the file before every teammate has run `dailybot agent configure`.
- **`default_metadata`** — shallow-merged into every `--metadata` payload sent from the repo. Inline `--metadata` keys win per-key; missing keys fall through. Useful for stamping every report with team/service tags.

Per-field precedence (highest wins): **CLI flag → `.dailybot/profile.json` → global `agents.json` → hardcoded fallback (`"CLI Agent"`)**.

**Security:** a `key` field in the repo file is rejected with a hard error. Credentials must never be committed — auth always resolves from your global profile, `DAILYBOT_API_KEY`, or `dailybot login`. Unknown future keys log a warning and are ignored.

To see exactly what the CLI will use in the current directory:

```bash
dailybot agent profiles --resolve
```

### Standalone registration

No Dailybot account? Agents can register autonomously — no human setup required:

```bash
dailybot agent register --org-name "My Startup" --agent-name "Claude Code"

# Optionally provide a human contact email
dailybot agent register --org-name "My Startup" --agent-name "Claude Code" --email me@co.com
```

This creates an organization, generates an API key, and saves it as a profile automatically. Every registered agent gets a **free Dailybot email address** (e.g. `claude-code@mail.dailybot.co`) so it can send and receive messages worldwide — with humans and other agents alike.

The output includes a **claim URL** — share it with your team admin to connect the org to Slack, Google Chat, Discord, Microsoft Teams, or other platforms. The claim URL expires in 30 days.

### Agent commands

```bash
# Report a deployment
dailybot agent update "Deployed v2.1 to staging"

# Name the agent so the team knows who's reporting
dailybot agent update "Built feature X" --name "Claude Code"

# Include structured data (each field is an array; items become bullet points in Dailybot)
dailybot agent update "Sprint progress" --name "Claude Code" --json-data '{
  "completed": ["JWT authentication endpoint", "Token refresh logic", "Unit tests for auth flow"],
  "in_progress": ["Integration tests"],
  "blockers": []
}'

# Attach metadata (repo, branch, PR, or any key-value context)
dailybot agent update "Fixed login bug" --name "Claude Code" --metadata '{"repo": "api-services", "branch": "fix/login", "pr": "#142"}'

# Mark a report as a milestone
dailybot agent update "Shipped v3.0" --milestone --name "Claude Code"

# Add co-authors (repeatable flag or comma-separated)
dailybot agent update "Paired on auth refactor" --co-authors alice@co.com --co-authors bob@co.com
dailybot agent update "Paired on auth refactor" --co-authors "alice@co.com,bob@co.com"

# Combine milestone and co-authors
dailybot agent update "Launched new dashboard" --milestone --co-authors alice@co.com --name "Claude Code"

# Report agent health
dailybot agent health --ok --message "All systems go" --name "Claude Code"
dailybot agent health --fail --message "DB unreachable" --name "CI Bot"

# Check agent health status
dailybot agent health --status --name "Claude Code"

# Register a webhook to receive messages
dailybot agent webhook register --url https://my-server.com/hook --secret my-token --name "Claude Code"

# Unregister a webhook
dailybot agent webhook unregister --name "Claude Code"

# Send a message to an agent
dailybot agent message send --to "Claude Code" --content "Review PR #42"
dailybot agent message send --to "Claude Code" --content "Do X" --type command

# List messages for an agent
dailybot agent message list --name "Claude Code"
dailybot agent message list --pending

# Mark specific messages as read
dailybot agent message claim abc-123
dailybot agent message claim abc-123 def-456

# Mark all pending messages as delivered (via health check)
dailybot agent message claim-all

# Send an email through an agent
dailybot agent email send --to user@example.com --subject "Build passed" \
  --body-html "<p>All green.</p>" --name "Claude Code"

# Send to multiple recipients
dailybot agent email send --to a@co.com --to b@co.com --subject "Report" \
  --body-html "<h1>Sprint complete</h1>" --name "Claude Code"
```

Replies to agent emails land as messages retrievable via `dailybot agent message list`.

## Commands

| Command | Description |
|---|---|
| `dailybot login` | Authenticate with email OTP |
| `dailybot logout` | Log out and revoke token |
| `dailybot status` | Show pending check-ins for today |
| `dailybot update` | Submit a check-in update (free-text or structured) |
| `dailybot config` | Get, set, or remove a stored setting (e.g. API key) |
| `dailybot agent configure` | Configure a named agent profile |
| `dailybot agent profiles` | List all configured agent profiles |
| `dailybot agent register` | Register a new agent and organization (standalone) |
| `dailybot agent update` | Submit an agent activity report |
| `dailybot agent health` | Report or query agent health status |
| `dailybot agent webhook register` | Register a webhook for the agent |
| `dailybot agent webhook unregister` | Unregister the agent's webhook |
| `dailybot agent message send` | Send a message to an agent |
| `dailybot agent message list` | List messages for an agent |
| `dailybot agent message claim` | Mark specific messages as read |
| `dailybot agent message claim-all` | Mark all pending messages as delivered |
| `dailybot agent email send` | Send an email through an agent |

### `dailybot agent update`

```
Usage: dailybot agent update [OPTIONS] CONTENT

  Submit an agent activity report.

Options:
  -n, --name TEXT        Agent worker name.
  -j, --json-data TEXT   Structured JSON data to include.
  -d, --metadata TEXT    JSON metadata (e.g. repo, branch, PR).
  -m, --milestone        Mark as a milestone accomplishment.
  -c, --co-authors TEXT  Co-author email or UUID (repeatable, or comma-separated).
  --help                 Show this message and exit.
```

#### Structured JSON data format

The `--json-data` option accepts a JSON object whose values are **arrays of strings**. Each array item becomes a bullet-pointed update inside Dailybot. Use any field names that match your workflow:

```json
{
  "completed": ["JWT auth endpoint", "Token refresh logic"],
  "in_progress": ["Integration tests", "API docs"],
  "blockers": ["Waiting on staging DB credentials"]
}
```

Run `dailybot --help` or `dailybot <command> --help` for full details on any command.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

[MIT](LICENSE)
