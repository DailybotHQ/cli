# API Reference

This document is the contract between command callbacks and the rest of the world. It lists:

1. Every CLI command and its flags.
2. Every Dailybot HTTP endpoint the CLI consumes (request shape, expected response shape, auth scheme).
3. The mapping between them.

> When in doubt, the source of truth is `dailybot_cli/api_client.py` (HTTP layer) and `dailybot_cli/commands/*.py` (CLI layer). This doc must be kept in sync with both.

## CLI Commands

### Root

```
dailybot [--api-url URL] [--version] [<command> …]
```

| Flag | Env var | Default | Notes |
|------|---------|---------|-------|
| `--api-url` | `DAILYBOT_API_URL` | `https://api.dailybot.com` | Set before any subcommand runs |
| `--version` | — | — | Reads `importlib.metadata.version("dailybot-cli")` |

Run with no subcommand → drops into the interactive TUI (`commands/interactive.py`).

---

### `dailybot login`

Authenticate via email-OTP. Three modes:

| Mode | Invocation | Behavior |
|------|------------|----------|
| Fully interactive | `dailybot login` | Prompts for email, requests code, prompts for code, prompts for org if multi-org |
| Non-interactive step 1 | `dailybot login --email=<email>` | Sends OTP, prints next-step instructions, exits |
| Non-interactive step 2 | `dailybot login --email=<email> --code=<code> [--org=<uuid>]` | Verifies and saves credentials |

| Flag | Notes |
|------|-------|
| `--email` | If flag is present (vs. prompted), CLI runs in non-interactive mode |
| `--code` | Required for step 2; without it, runs step 1 |
| `--org` | Org UUID (not integer ID) — resolved against `org_cache.json` saved during step 1 |

Persists: `~/.config/dailybot/credentials.json` (`0o600`).

### `dailybot logout`

Best-effort token revocation + clears local credentials. Always succeeds locally even if the API call fails.

### `dailybot status [--auth]`

Without `--auth`: lists today's pending check-ins.

With `--auth`: verifies credentials. Tries OTP login first, then API key. Exits 1 if neither works.

### `dailybot update [MESSAGE] [--done X] [--doing Y] [--blocked Z]`

Submit a check-in update. If no flags and no message, prompts on stdin (Enter twice to submit).

| Flag | Short | Notes |
|------|-------|-------|
| `--done` | `-d` | What you completed |
| `--doing` | `-w` | What you're working on |
| `--blocked` | `-b` | Blockers |

### `dailybot config <setting>[=<value>]`

| Setting | Mapped key | Behavior |
|---------|-----------|----------|
| `key` | `api_key` | `key=...` saves; `key=` removes; `key` (no `=`) shows masked |

Persists to `~/.config/dailybot/config.json` (`0o600`).

---

### `dailybot agent` (group)

Group-level flag: `--profile / -p <name>` (passed via `ctx.obj`).

#### `dailybot agent configure --name "..." [--key ...] [--profile <slug>]`

Creates or updates an entry in `~/.config/dailybot/agents.json`. If `--key` is provided, the key is validated by calling `GET /v1/agent-health/?agent_name=<name>` and treating non-401/403 errors as success (the key itself is valid even if the agent doesn't exist yet).

If no key is provided, the profile uses your login session's Bearer token.

#### `dailybot agent profiles`

Lists all configured profiles with masked keys.

#### `dailybot agent register --org-name "..." --agent-name "..." [--email ...] [--timezone UTC] [--profile <slug>]`

Standalone registration. No auth required.

Flow:
1. `GET /v1/agent/register/challenge/` → returns `{ challenge_id, instruction }`. Instruction is a wordy paragraph containing `"session is <random_number>."`.
2. Solve: `random_number * 52`. (52 is `_CHALLENGE_WORD_COUNT`, defined in `commands/agent.py`.)
3. `POST /v1/agent/register/` with `challenge_id`, `answer`, `reason`, `org_name`, `agent_name`, `timezone`, optional `contact_email`.
4. Saves the returned API key as a profile, prints the claim URL.

Auto-retries once if the challenge has expired.

#### `dailybot agent update <content> [--name ...] [--profile ...] [--json-data JSON] [--metadata JSON] [--milestone] [--co-authors EMAIL]...`

Submits an `/v1/agent-reports/` POST.

| Flag | Short | Notes |
|------|-------|-------|
| `--name` | `-n` | Agent worker name (overrides profile's `agent_name`) |
| `--profile` | `-p` | Profile to use |
| `--json-data` | `-j` | Structured progress data (JSON object with array values) |
| `--metadata` | `-d` | Arbitrary JSON metadata (e.g., `{"repo": "cli", "branch": "main"}`) |
| `--milestone` | `-m` | Marks the report as a milestone |
| `--co-authors` | `-c` | Repeatable; comma-separated values are split |

#### `dailybot agent health (--ok | --fail | --status) [--message ...] [--name ...] [--profile ...]`

Exactly one of `--ok / --fail / --status` is required.

`--status` issues `GET /v1/agent-health/?agent_name=...`. `--ok / --fail` issues `POST /v1/agent-health/` with `ok=<true|false>`.

A health POST also drains pending messages — that's why `claim-all` is implemented as a `health --ok` call.

#### `dailybot agent webhook register --url ... [--secret ...] [--name ...] [--profile ...]`
#### `dailybot agent webhook unregister [--name ...] [--profile ...]`

Webhook URL receives `POST` with body containing the inbound message; if `--secret` was set, requests include `X-Webhook-Secret: <secret>`.

#### `dailybot agent message send --to ... --content ... [--type text|command|system] [--name ...] [--profile ...] [--json-data JSON] [--expires-at ISO8601]`
#### `dailybot agent message list [--name ...] [--profile ...] [--pending]`
#### `dailybot agent message claim <id> [<id> ...]`
#### `dailybot agent message claim-all [--name ...] [--profile ...]`

Inter-agent messaging. `--pending` filters to undelivered. `claim` marks specific IDs read; `claim-all` drains via the health endpoint.

#### `dailybot agent email send --to ... --subject ... --body-html ... [--name ...] [--profile ...] [--metadata JSON]`

Sends transactional email through the agent's `@mail.dailybot.co` inbox. `--to` is repeatable. Replies arrive as `agent message`s and can be retrieved via `agent message list`.

`429 Too Many Requests` → "Hourly email limit exceeded" (the API enforces hourly throttling).

---

## HTTP Endpoints

All endpoints are POSTed to `{api_url}/v1/...`. The default `api_url` is `https://api.dailybot.com`.

### Auth (Bearer)

| Method | Path | Request | Response (200/201) | Notes |
|--------|------|---------|--------------------|-------|
| `POST` | `/v1/cli/auth/request-code/` | `{ email }` | `{ is_multi_org, organizations: [{id, uuid, name}] }` | No auth |
| `POST` | `/v1/cli/auth/verify-code/` | `{ email, code, organization_id? }` | `{ token, organization: {name, uuid} }` or `{ requires_organization_selection: true, organizations: [...] }` | No auth |
| `GET` | `/v1/cli/auth/status/` | — | `{ user: {email}, organization: {name, uuid} }` | Bearer |
| `POST` | `/v1/cli/auth/logout/` | — | `{ detail }` | Bearer |

### Human (Bearer)

| Method | Path | Request | Response | Notes |
|--------|------|---------|----------|-------|
| `POST` | `/v1/cli/updates/` | `{ message?, done?, doing?, blocked? }` | `{ followups_count, attached_followups: [{followup_name, action}] }` | 120s timeout (AI parsing) |
| `GET` | `/v1/cli/status/` | — | `{ pending_checkins: [{followup_name, template_questions}] }` | |

### Agent (X-API-KEY *or* Bearer)

| Method | Path | Request | Response | Notes |
|--------|------|---------|----------|-------|
| `POST` | `/v1/agent-reports/` | `{ agent_name, content, structured?, metadata?, is_milestone?, co_authors? }` | `{ id, is_milestone, co_authors?, pending_messages? }` | |
| `POST` | `/v1/agent-health/` | `{ agent_name, ok, message? }` | `{ agent_name, status, last_check, history?, pending_messages? }` | |
| `GET` | `/v1/agent-health/?agent_name=...` | — | (same shape) | |
| `POST` | `/v1/agent-webhook/` | `{ agent_name, webhook_url, webhook_secret? }` | `{ agent_name, webhook_url }` | |
| `DELETE` | `/v1/agent-webhook/` | `{ agent_name }` | `{ detail }` | |
| `POST` | `/v1/agent-email/send/` | `{ agent_name, to, subject, body_html, metadata? }` | `{ sent_count, total_recipients, reply_to? }` | 429 = hourly limit |
| `POST` | `/v1/agent-messages/` | `{ agent_name, content, message_type?, metadata?, expires_at?, sender_type?, sender_name? }` | `{ id, agent_name, sender_name, sender_type, message_type, content }` | |
| `GET` | `/v1/agent-messages/?agent_name=...&delivered=true|false` | — | `[{ id, message_type, sender_type, sender_name, content, delivered, created_at }]` | Returns a bare array, not a wrapped object |
| `PATCH` | `/v1/agent-messages/read/` | `{ message_ids: [...] }` | `{ updated }` | |

### Standalone Agent Registration (no auth)

| Method | Path | Request | Response | Notes |
|--------|------|---------|----------|-------|
| `GET` | `/v1/agent/register/challenge/` | — | `{ challenge_id, instruction }` | |
| `POST` | `/v1/agent/register/` | `{ challenge_id, answer, reason, org_name, agent_name, timezone, contact_email? }` | `{ agent_name, agent_email, org_name, api_key, claim_url }` | 429 = rate-limited |

## Auth Header Selection

```
def _headers(authenticated=True):
    h = {Content-Type, Accept}
    if authenticated and self.token:
        h["Authorization"] = f"Bearer {self.token}"
    return h

def _agent_headers():
    h = {Content-Type, Accept}
    if self.api_key:
        h["X-API-KEY"] = self.api_key       # ← preferred for agent endpoints
        self._agent_auth_mode = "api_key"
    elif self.token:
        h["Authorization"] = f"Bearer {self.token}"
        self._agent_auth_mode = "bearer"
    else:
        self._agent_auth_mode = None
    return h
```

The `_agent_auth_mode` is used by `_handle_response` to produce a "Session expired" message on 401/403 only when the auth came from a Bearer token (not from an API key, where the wording would be misleading).

## Error Translation

| HTTP | Default behavior | Per-command override |
|------|------------------|----------------------|
| Any | `APIError(status_code, detail)` | All commands wrap calls in `try/except APIError` |
| 401/403 (bearer) | `_handle_response` rewrites detail to "Session expired. Run 'dailybot login' to re-authenticate." | Multiple commands also catch and prefix with their own context |
| 401/403 (api_key) | passes through with backend's detail | `agent configure` treats as invalid key |
| 400 with "ai processing failed" | — | `update.py` rewrites to a support-contact message |
| 429 | passes through | `agent email send` adds "Hourly email limit exceeded"; `agent register` adds "Rate limited. Try again in a few minutes." |
| `httpx.TimeoutException` | propagates from httpx | `update.py` and `interactive.py` catch and emit a "may be processing your update" message |
