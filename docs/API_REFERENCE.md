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

Run with no subcommand → drops into the menu-driven interactive TUI (`commands/interactive.py`).

### `dailybot ask [MESSAGE] [--json] [--session-id ID]`

Talk to the Dailybot AI. The mode is chosen by whether a message is supplied (same pattern as `psql`/`python`/`sqlite3`):

- **`dailybot ask "question"`** — **headless one-shot**: sends the message to `POST /v1/cli/chat/completions/` and prints the assistant's answer to stdout, then exits. Ideal for agents, CI, and scripts. `--json` emits `{ message, actions, classification, session_id }`. A piped message also works: `echo "draft my standup" | dailybot ask`.
- **`dailybot ask`** (no message, interactive terminal) — opens the full-screen Textual chat session (multi-turn).

| Flag | Short | Notes |
|------|-------|-------|
| `--json` | | Machine-readable answer (headless mode). |
| `--session-id` | `-s` | Continue an existing chat session by id. |

### `dailybot interactive` (deprecated alias)

Deprecated alias for `dailybot ask` with no message (opens the chat session). Retained for backward-compatibility with CLI 1.14.0; prints a deprecation notice. New code should use `dailybot ask`.

Starts a Claude-style full-screen Textual chat session. Natural-language turns are sent to Dailybot via `POST /v1/cli/chat/completions/`; the Textual UI is lazy-loaded only when this command runs.

Slash commands are handled locally unless they need an existing CLI endpoint:

| Command | Behavior |
|---------|----------|
| `/help` | Show chat-mode help. |
| `/clear` | Clear local transcript and start a new terminal session id. |
| `/status` | Call `GET /v1/cli/auth/status/`. |
| `/checkins` | Call `GET /v1/cli/status/`. |
| `/report` | Submit a free-text update through `POST /v1/cli/updates/`. |
| `/exit` | Leave the chat session. |

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

### `dailybot checkin` (group) — user-scoped, Bearer or API key auth

#### `dailybot checkin list [--json]`

Lists today's pending check-ins. Calls `GET /v1/cli/status/`. JSON mode adds 0-based `index` to each question.

#### `dailybot checkin complete <followup_uuid> [-a index=response]... [--response-date YYYY-MM-DD] [--yes] [--json]`

Completes a pending check-in.

| Flag | Short | Notes |
|------|-------|-------|
| `--answer` | `-a` | Repeatable `index=response` (0-based). Prompts when omitted. |
| `--response-date` | | Defaults to today. |
| `--yes` | `-y` | Skip confirmation prompt. |
| `--json` | | Machine-readable JSON output. |

Interactive path: prompts each question using type-aware inputs (text, numeric, boolean, choice). Non-interactive path requires all `--answer` flags matching the question count.

---

### `dailybot form` (group) — user-scoped, Bearer or API key auth

#### `dailybot form list [--json]`

Lists forms visible to the user. Calls `GET /v1/forms/?include=questions` to include question definitions.

#### `dailybot form get <form_uuid> [--json]`

Fetches a form's full payload via `GET /v1/forms/<uuid>/` — questions, workflow states, and permissions surface (`workflow_enabled`, `workflow_config.states`, `state_change_permission`, `view_reports_permission`, `edit_permission`, `allow_reopen_from_final_state`).

#### `dailybot form submit <form_uuid> [--content JSON] [--yes] [--json]`

Submits a form response. When `--content` is omitted, calls `GET /v1/forms/<uuid>/` to load questions and prompts each one interactively with type-aware inputs.

| Flag | Short | Notes |
|------|-------|-------|
| `--content` | `-c` | JSON map `{"<question_uuid>": "<answer>"}`. |
| `--yes` | `-y` | Skip confirmation prompt. |
| `--json` | | Machine-readable JSON output. |

#### `dailybot form responses <form_uuid> [--state STATE] [--latest] [--json]`

Lists the caller's own responses (`GET /v1/forms/<uuid>/responses/`). `--state` filters by `current_state` (workflow forms only). `--latest` returns only the most recent — useful for "continue where I left off".

#### `dailybot form response get <form_uuid> <response_uuid> [--json]`

Fetches a single response (`GET /v1/forms/<uuid>/responses/<resp_uuid>/`) including `current_state`, `allowed_transitions`, `can_change_state`, and `state_history`. A 404 returns `{code: form_response_not_found}` (the API never leaks existence to callers without read permission).

#### `dailybot form update <form_uuid> <response_uuid> --content JSON [--yes] [--json]`

Merges new answers into an in-progress response via `PATCH /v1/forms/<uuid>/responses/<resp_uuid>/`. Strict own-only — admins are not elevated to other users' responses on this endpoint.

#### `dailybot form transition <form_uuid> <response_uuid> <to_state> [--note ...] [--yes] [--json]`

Advances a response to `to_state` via `POST /v1/forms/<uuid>/responses/<resp_uuid>/transition/`. The form's `state_change_permission` audience is the sole gate — there is no response-author short-circuit. `--note` is recorded on the audit trail. 403 / `final_state_locked` fires when the response is in the final state and the form's `allow_reopen_from_final_state` is `false`.

#### `dailybot form delete <form_uuid> <response_uuid> [--yes] [--json]`

Deletes a response via `DELETE /v1/forms/<uuid>/responses/<resp_uuid>/`. Allowed for the response author, the form owner, or an org admin (403 / `form_response_delete_forbidden` otherwise).

---

### `dailybot kudos` (group) — user-scoped, Bearer or API key auth

#### `dailybot kudos give [--to <user>] [--team <team>] --message <text> [--value <uuid>] [--yes] [--json]`

Gives kudos to a user, a team, or both. Users are resolved by name (exact then partial match) against `GET /v1/users/`. Teams are resolved by name against `GET /v1/teams/` (server-scoped by role). At least one of `--to` / `--team` is required.

The POST `/v1/kudos/` payload uses a single `receivers` list of UUIDs (users and teams merged — the server resolves each UUID's type); the backend manager expands team UUIDs into their active members and excludes the caller, so giving kudos to a team you belong to is valid. (The legacy `user_uuid_receivers` / `team_uuid_receivers` fields are still accepted server-side during a deprecation window, but the CLI now sends `receivers`.)

| Flag | Short | Notes |
|------|-------|-------|
| `--to` | `-t` | User full name or UUID. Optional when `--team` is provided. |
| `--team` | | Team name or UUID. Optional when `--to` is provided. |
| `--message` | `-m` | Kudos message. Required. |
| `--value` | | Optional company value UUID. |
| `--yes` | `-y` | Skip confirmation prompt. |
| `--json` | | Machine-readable JSON output. |

Self-kudos via `--to` is rejected client-side (exit code 4). Ambiguous name matches return exit code 2.

---

### `dailybot user` (group) — user-scoped, Bearer or API key auth

#### `dailybot user list [--json]`

Lists organization members. Calls `GET /v1/users/` with automatic pagination (capped at `_MAX_LIST_PAGES = 50`). Table displays Name and UUID only — emails are not shown.

---

### `dailybot team` (group) — user-scoped, Bearer or API key auth

#### `dailybot team list [--json]`

Lists teams visible to the caller via `GET /v1/teams/`. **Visibility is scoped server-side**: admins see all org teams, members see only their own (via `teammembership_set`). The CLI never client-filters — it renders the server response verbatim.

#### `dailybot team get <team_uuid_or_name> [--with-members] [--json]`

Fetches a team via `GET /v1/teams/<uuid>/`. A name argument is resolved to UUID by calling `GET /v1/teams/` first (case-insensitive; ambiguous matches exit 2). `--with-members` adds a second call to `GET /v1/teams/<uuid>/members/`.

---

### User-scoped exit codes

All user-scoped commands (`checkin`, `form`, `kudos`, `user`, `team`) share these exit codes:

| Code | Constant | Meaning |
|------|----------|---------|
| `0` | — | Success |
| `2` | `EXIT_USAGE_ERROR` | Invalid input / 400 from server |
| `3` | `EXIT_NOT_AUTHENTICATED` | Not logged in |
| `4` | `EXIT_PERMISSION_DENIED` | Forbidden, self-kudos, daily limit, `final_state_locked` |
| `5` | `EXIT_NOT_FOUND` / `EXIT_QUOTA_EXHAUSTED` | 404 from server, or form quota (402) |
| `6` | `EXIT_RATE_LIMITED` | Rate limited (429) |
| `7` | `EXIT_USER_ABORTED` | Confirmation declined |

`--json` output for any 4xx includes `error`, `status`, and (when present) `code` + `detail` — pattern-match on `code` rather than prose.

Server-side `code` values mapped to messages (see `ERROR_CODE_MESSAGES` in `commands/public_api_helpers.py`):

| Code | Surfaced as |
|------|-------------|
| `form_response_change_state_forbidden` | 403 → exit 4 |
| `final_state_locked` | 403 → exit 4 |
| `form_response_delete_forbidden` | 403 → exit 4 |
| `user_can_not_see_form_responses` | 403 → exit 4 |
| `form_response_not_found` | 404 → exit 5 |
| `form_does_not_exists` | 404 → exit 5 |
| `payload_too_large` | 400 → exit 2 |
| `no_valid_team` | 400 → exit 2 |
| `no_valid_users` | 400 → exit 2 |
| `no_users_found` | 400 → exit 2 |

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

### `dailybot chat send` / `dailybot chat update <bot_message_id>`

Sends a Dailybot **bot** message to the org's connected chat platform
(Slack/Teams/Discord/Google Chat) via `POST /v1/send-message/`. The CLI
authenticates with the login **Bearer** token automatically when no API key is
configured, so this works after `dailybot login` (sends **as you**, role-scoped
— see below); an org `X-API-KEY` also works and is org-wide. `update` is the
same call with `bot_message_id` set, which edits the existing message.

At least one target is required. Targets:

| Flag | Repeatable | Accepts |
|------|-----------|---------|
| `--user` / `-u` | yes | user UUID, email, or chat external id (delivered as DM) |
| `--channel` / `-c` | yes | channel id |
| `--team` / `-t` | yes | team UUID (expanded to members as DMs) |

Content & options: `--text/-m`, `--image-url/-i`, `--link-button "Label::url"`
(repeatable), `--button "Label::value"` (interactive, repeatable),
`--thread-message` (repeatable, max 10 — posts a reply in the parent's thread),
`--thread` (reply into an existing platform thread id),
`--channel-type` (`channel`/`private_channel`/`group_chat`/`direct_message`),
`--bot-name`, `--bot-icon-url`, `--bot-icon-emoji`, `--ephemeral`,
`--skip-time-off`, `--metadata/-d JSON`, `--profile/-p`.

- `--payload-json '<body>'` — raw request body escape hatch for full API
  control (multi-part `messages`, rich `thread_responses`, any future field);
  bypasses the building flags. Forward-compatible by design.
- `--json` — emit the raw API response to stdout for headless/agent use:
  `{ "bot_message_id": "<parent>", "thread_responses": ["<reply1>", …] }`.

**Threads.** `--thread-message` builds the request's `thread_responses` array:
a short parent message plus its replies, posted inside the parent's thread in
one call. The response returns the parent `bot_message_id` plus one
server-minted id per reply, so `chat update <id>` edits the **parent or any
reply** in place. Threads render natively on Slack (channels + DMs); on
Teams/Discord/Google Chat they thread in channels and deliver flat in DMs (the
replies always arrive, never dropped).

**Identity & ephemeral (Slack only).** `platform_settings` (`--bot-name`,
`--bot-icon-url`/`--bot-icon-emoji`, `--ephemeral`) are silently ignored on
other platforms. `--bot-icon-url` and `--bot-icon-emoji` are mutually
exclusive; `--ephemeral` needs a `--user` target. Custom name/avatar needs the
Slack `chat:write.customize` scope — without it Slack uses the default identity
(`ok: true`, no error). On **update**, the platform keeps the message's
original name/avatar, so identity flags are ignored when editing.

**Send by name.** Targeting flags only accept ids/emails, never free-form
names. To message "Sergio Florez", resolve the name first with
`dailybot user list` (gives each member's UUID), then pass it to `--user`.

**Role scope (login path).** A logged-in caller reaches only what their role
allows in their own org: admins/managers → anyone/any channel/any team;
team members → teammates, public channels, and teams they belong to; guests →
self only. Out-of-scope → `403 cli_send_message_target_not_allowed`; CLI sends
are rate-limited per token (`429`). The `X-API-KEY` path is org-wide and not
scoped/throttled this way.

---

### `dailybot hook <subcommand>` (local-only — no HTTP)

Lifecycle commands for agent harness hooks. They read/write only the local
report ledger (`<config dir>/ledger/`) and git — **never** the Dailybot API —
and always exit `0` so a failure can't break the calling agent session.
Full guide with diagrams: [AGENT_HOOKS.md](AGENT_HOOKS.md).

| Subcommand | Flags | Output |
|------------|-------|--------|
| `session-start` | `--format/-f claude\|cursor\|generic` | Login nudge + leftover-work context in the harness's hook dialect, or nothing |
| `post-commit` | — | Silent; records a strong work signal |
| `activity` | — | Silent; records a soft (non-commit) work signal |
| `stop` | `--format/-f claude\|cursor\|generic` | Report reminder when unreported work exists, or nothing |
| `dismiss` | `--minutes/-m INT` (default 60) | Confirmation line; snoozes reminders for the repo |

`dailybot agent update` resets the ledger on success (`mark_reported`), which
is what stops the reminders after the model reports.

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

### CLI-personal (X-API-KEY *or* Bearer)

These accept **either** an org API key (`X-API-KEY`) or a Bearer login token; the server resolves the acting user from the key's owner.

| Method | Path | Request | Response | Notes |
|--------|------|---------|----------|-------|
| `POST` | `/v1/cli/updates/` | `{ message?, done?, doing?, blocked? }` | `{ followups_count, attached_followups: [{followup_name, action}] }` | 120s timeout (AI parsing) |
| `GET` | `/v1/cli/status/` | — | `{ pending_checkins: [{followup_name, template_questions}] }` | Also backs `dailybot checkin list` |
| `GET` | `/v1/cli/auth/status/` | — | `{ authenticated, user: {uuid, email, full_name}, organization: {id, name, uuid} }` | Session/identity; resolves the API key's owner too |
| `POST` | `/v1/cli/chat/completions/` | `{ message?, history?, messages?, session_id?, reset_thread?, available_commands? }` | `{ status, async, correlation_id, classification, message: {role, content}, actions }` | AI chat (`dailybot ask` / `interactive`); 120s timeout |

### User-scoped (X-API-KEY *or* Bearer)

These endpoints accept **either** an org API key (`X-API-KEY`) or a Bearer login
token. The CLI prefers the login session when present and falls back to the API
key, so all of these commands work with `DAILYBOT_API_KEY` set even without
`dailybot login`.

| Method | Path | Request | Response | Notes |
|--------|------|---------|----------|-------|
| `GET` | `/v1/forms/` | `?include=questions` (optional) | `[{ id, name, questions?: [...] }]` | |
| `GET` | `/v1/forms/<uuid>/` | — | `{ id, name, slug, workflow_enabled, workflow_config, questions: [...] }` | Used by guided form submit + `form get` |
| `POST` | `/v1/forms/<uuid>/responses/` | `{ content: { "<q_uuid>": "<answer>" } }` | `{ id, current_state?, allowed_transitions?, can_change_state? }` | 402 = quota exhausted |
| `GET` | `/v1/forms/<uuid>/responses/` | `?state=<key>` (optional) | `[{ id, current_state, allowed_transitions, can_change_state, state_history, content, edited, created_at }]` | Caller's own responses |
| `GET` | `/v1/forms/<uuid>/responses/<resp_uuid>/` | — | Same shape as above | 404 = `form_response_not_found` |
| `PATCH` | `/v1/forms/<uuid>/responses/<resp_uuid>/` | `{ content: { ... } }` | Updated response | Strict own-only |
| `POST` | `/v1/forms/<uuid>/responses/<resp_uuid>/transition/` | `{ to_state, note? }` | Updated response | 403 = `form_response_change_state_forbidden` or `final_state_locked` |
| `DELETE` | `/v1/forms/<uuid>/responses/<resp_uuid>/` | — | 204 | Author / owner / admin |
| `POST` | `/v1/checkins/<followup_uuid>/responses/` | `{ responses: [{ uuid, index, response }], last_question_index?, response_date? }` | `{ uuid }` | |
| `GET` | `/v1/users/` | — | `{ results: [{ uuid, full_name }], next: url\|null }` | Paginated |
| `GET` | `/v1/teams/` | — | `{ results: [{ uuid, name, active, members_count, is_default }], next? }` | Server-scoped: admins see all, members see own |
| `GET` | `/v1/teams/<uuid>/` | — | `{ uuid, name, active, ... }` | Same scoping |
| `GET` | `/v1/teams/<uuid>/members/` | — | `[{ uuid, full_name, email }]` | Members of a team the caller can see |
| `POST` | `/v1/kudos/` | `{ content, receivers: [...uuid], company_value? }` | `{ uuid }` | `receivers` merges users+teams; legacy `user_uuid_receivers`/`team_uuid_receivers` still accepted; 406 = daily limit |

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
| `POST` | `/v1/send-message/` | `{ message?/messages?, image_url?, buttons?, thread_responses?, target_users?/target_channels?/target_teams?, platform_settings?, metadata?, skip_users_on_time_off?, bot_message_id? }` | `{ bot_message_id, thread_responses?: [ids] }` | **X-API-KEY or Bearer** (login, role-scoped); ≥1 target; `thread_responses` posts replies in the parent thread (≤10); `bot_message_id` in → edits that message (parent or reply) |
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
    if authenticated:
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"   # ← preferred for user endpoints
            self._agent_auth_mode = "bearer"
        elif self.api_key:
            h["X-API-KEY"] = self.api_key                 # ← fallback when no login session
            self._agent_auth_mode = "api_key"
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

Both helpers accept **either** credential; they differ only in preference order
(`_headers` is Bearer-first, `_agent_headers` is API-key-first). The
`_agent_auth_mode` is used by `_handle_response` to produce a "Session expired"
message on 401/403 only when the auth came from a Bearer token (not from an API
key, where the wording would be misleading).

## Error Translation

| HTTP | Default behavior | Per-command override |
|------|------------------|----------------------|
| Any | `APIError(status_code, detail)` | All commands wrap calls in `try/except APIError` |
| 401/403 (bearer) | `_handle_response` rewrites detail to "Session expired. Run 'dailybot login' to re-authenticate." | Multiple commands also catch and prefix with their own context |
| 401/403 (api_key) | passes through with backend's detail | `agent configure` treats as invalid key |
| 400 with "ai processing failed" | — | `update.py` rewrites to a support-contact message |
| 429 | passes through | `agent email send` adds "Hourly email limit exceeded"; `agent register` adds "Rate limited. Try again in a few minutes." |
| `httpx.TimeoutException` | propagates from httpx | `update.py` and `interactive.py` catch and emit a "may be processing your update" message |
