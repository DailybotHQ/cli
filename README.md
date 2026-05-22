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

To uninstall:

```bash
dailybot uninstall              # confirm, then remove (keeps your config)
dailybot uninstall --yes        # skip the confirmation (for scripts / CI)
dailybot uninstall --purge      # also delete ~/.config/dailybot/
dailybot uninstall --dry-run    # show the plan, do nothing
```

Same auto-detection as `upgrade`: the matching uninstall is run for you on `pipx` / `uv tool` / `pip` installs; for Homebrew and the Linux/Windows binary the exact command is printed instead. Your credentials and agent profiles in `~/.config/dailybot/` are **kept by default** so reinstalling later doesn't force you to redo `dailybot login` or `dailybot agent configure` — pass `--purge` to wipe them too.

> **Bug reports?** Always include the full output of `dailybot version` — the install path and Python runtime are usually enough to tell us whether the issue is in the CLI itself, in a transitive dep, or in the host environment.

## For humans

Authenticate once with your Dailybot email, then submit updates, complete check-ins, fill out forms, give kudos, and browse your team — all from your terminal.

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

Run `dailybot` with no arguments to enter **interactive mode** — a grouped menu covering check-ins, forms, kudos, and team browsing. If you're not logged in yet, it walks you through authentication first.

---

## Check-ins

```bash
# List today's pending check-ins
dailybot checkin list

# Complete a check-in interactively (prompts each question)
dailybot checkin complete <followup_uuid>

# Complete non-interactively with answer flags (0-based index)
dailybot checkin complete <followup_uuid> \
  -a 0="Shipped the auth refactor" \
  -a 1="Reviewing the migration plan" \
  --yes

# Target a specific response date
dailybot checkin complete <followup_uuid> -a 0="Done" --response-date 2026-05-20 --yes

# Machine-readable JSON output
dailybot checkin list --json
dailybot checkin complete <followup_uuid> -a 0="Done" --yes --json
```

### `dailybot checkin complete` options

| Flag | Short | Description |
|------|-------|-------------|
| `--answer` | `-a` | Answer as `index=response` (0-based). Repeatable. Prompts when omitted. |
| `--response-date` | | Target date `YYYY-MM-DD`. Defaults to today. |
| `--yes` | `-y` | Skip the confirmation prompt. |
| `--json` | | Emit machine-readable JSON to stdout. |

---

## Forms

```bash
# List all forms visible to you (includes question count)
dailybot form list

# Submit a form — guided mode (prompts each question by label and type)
dailybot form submit <form_uuid>

# Submit non-interactively with a JSON content map
dailybot form submit <form_uuid> \
  --content '{"<question-uuid>":"Great week!", "<question-uuid-2>":"No blockers"}' \
  --yes

# Machine-readable JSON output
dailybot form list --json
dailybot form submit <form_uuid> --content '{"<q-uuid>":"Yes"}' --yes --json
```

Guided mode (`form submit` without `--content`) fetches the form's question list from the API and prompts each question one by one, with type-aware inputs:

| Question type | Prompt |
|--------------|--------|
| `text_field` | Free-text input |
| `numeric` | Number input, validated |
| `boolean` | Yes / No selector |
| `choice` | Pick from a list of options |

### `dailybot form submit` options

| Flag | Short | Description |
|------|-------|-------------|
| `--content` | `-c` | JSON map of `{"<question_uuid>": "<answer>"}`. Prompts when omitted. |
| `--yes` | `-y` | Skip the confirmation prompt. |
| `--json` | | Emit machine-readable JSON to stdout. |

---

## Kudos

```bash
# Give kudos — receiver resolved by full name against your org directory
dailybot kudos give --to "Jane Doe" --message "Shipped the auth refactor cleanly, great work!"

# Resolve by UUID instead
dailybot kudos give --to <user-uuid> --message "Thanks for the PR review." --yes

# Attach a company value
dailybot kudos give --to "Jane Doe" --message "Great!" --value <company-value-uuid> --yes

# Machine-readable
dailybot kudos give --to "Jane Doe" --message "Great!" --yes --json
```

If `--to` matches more than one name partially, the CLI lists the ambiguous matches and exits — it never guesses. Pass the full name or a UUID to be precise.

### `dailybot kudos give` options

| Flag | Short | Description |
|------|-------|-------------|
| `--to` | `-t` | Receiver full name or UUID. Required. |
| `--message` | `-m` | Kudos message (team-visible). Required. |
| `--value` | | Optional company value UUID. |
| `--yes` | `-y` | Skip the confirmation prompt. |
| `--json` | | Emit machine-readable JSON to stdout. |

---

## Team

```bash
# List all members in your organization
dailybot user list

# Machine-readable
dailybot user list --json
```

The table shows **Name** and **User UUID**. You can copy a UUID directly into `dailybot kudos give --to <uuid>` for precise targeting.

---

## User-scoped exit codes

All user-scoped commands (`checkin`, `form`, `kudos`, `user`) use structured exit codes for scripting:

| Code | Meaning |
|------|---------|
| `0` | Success |
| `2` | Invalid input (bad format, ambiguous receiver) |
| `3` | Not logged in — run `dailybot login` |
| `4` | Permission denied (403), self-kudos, or daily kudos limit reached |
| `5` | Form response quota exhausted |
| `6` | Rate limited — wait and retry |
| `7` | User declined the confirmation prompt |

## For agents

Any software agent — AI coding assistants, CI jobs, deploy scripts, bots — can report activity through the CLI. This lets teams get visibility into what automated processes are doing, alongside human updates. Dailybot interconnects agents and humans with work analysis, progress reports, observability, and automations.

### Quick start (interactive)

If you only do one thing on a fresh install, run:

```bash
dailybot agent init
```

It's a 30-second wizard that walks you through both kinds of profile — your **personal** identity (saved to `~/.config/dailybot/agents.json`) and an optional **repo-shared** identity (`<repo>/.dailybot/profile.json`, committed to git so every contributor signs reports the same way) — and asks the bare minimum: a display name and how to authenticate.

For non-interactive setup (CI, scripts, automation) every step the wizard does is also available as a flag — see the sections below.

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

The fastest way to create or update it is via the CLI:

```bash
# Create or merge the repo profile (anchors at the git root automatically)
dailybot agent configure --repo --name "Core Hub Bot"

# Add default metadata that gets stamped on every report from this repo
dailybot agent configure --repo --metadata team=platform --metadata service=core-hub

# Re-running is idempotent — fields are merged, metadata keys are added
```

Or hand-author the file if you prefer:

```json
{
  "name": "Core Hub Bot",
  "profile": "core-hub-bot",
  "default_metadata": {
    "team": "platform",
    "service": "core-hub"
  },
  "vars": {
    "release_form_id": "671b6410-83dc-4353-be08-dbea480274bc"
  }
}
```

All keys are optional:

- **`name`** — overrides the worker display name (same effect as `--name`). Anyone running `dailybot agent update "..."` from the repo signs as `"Core Hub Bot"`.
- **`profile`** — selects which entry of the **global** `agents.json` provides credentials. The repo file's `name` still wins over the global profile's display name. If the slug isn't found locally, the CLI warns once and falls back to your login session — handy for repos that ship the file before every teammate has run `dailybot agent configure`.
- **`default_metadata`** — shallow-merged into every `--metadata` payload sent from the repo. Inline `--metadata` keys win per-key; missing keys fall through. Useful for stamping every report with team/service tags.
- **`vars`** — a free-form object for repo-specific variables that the CLI carries but does not act on. Use it to store IDs, config values, or any context that scripts, skills, or automation can read from the profile. The CLI will never send `vars` in reports or warnings.

```json
{
  "name": "Core Hub Bot",
  "default_metadata": { "team": "platform" },
  "vars": {
    "release_form_id": "671b6410-83dc-4353-be08-dbea480274bc",
    "deploy_checkin_id": "abc-123"
  }
}
```

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

### Session

| Command | Description |
|---------|-------------|
| `dailybot login` | Authenticate with email OTP |
| `dailybot logout` | Log out and revoke token |
| `dailybot status` | Show pending check-ins and auth status |
| `dailybot update` | Submit a free-text or structured check-in update |
| `dailybot config` | Get, set, or remove a stored setting (e.g. API key) |
| `dailybot version` | Show version info and optionally check for updates |
| `dailybot upgrade` | Upgrade the CLI (auto-detects install method) |
| `dailybot uninstall` | Remove the CLI |

### Check-ins

| Command | Description |
|---------|-------------|
| `dailybot checkin list` | List today's pending check-ins |
| `dailybot checkin complete <uuid>` | Complete a pending check-in (interactive or `-a` flags) |

### Forms

| Command | Description |
|---------|-------------|
| `dailybot form list` | List forms visible to you (includes question count) |
| `dailybot form submit <uuid>` | Submit a form (guided prompts or `--content` JSON) |

### Kudos

| Command | Description |
|---------|-------------|
| `dailybot kudos give` | Give kudos to a teammate by name or UUID |

### Team

| Command | Description |
|---------|-------------|
| `dailybot user list` | List all members in your organization |

### Agent commands

| Command | Description |
|---------|-------------|
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
