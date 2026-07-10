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

The chat endpoint is throttled to **30 requests/minute per API key**. On a `429`, `dailybot ask` exits with code `6` and a "Rate limit exceeded. Try again in Ns." message; in `--json` mode the payload carries `retry_after_seconds` (from the `Retry-After` header).

### `dailybot interactive` (deprecated alias)

Deprecated alias for `dailybot ask` with no message (opens the chat session). Retained for backward-compatibility with CLI 1.14.0; prints a deprecation notice. New code should use `dailybot ask`.

Starts a Claude-style full-screen Textual chat session. Natural-language turns are sent to Dailybot via `POST /v1/cli/chat/completions/`; the Textual UI is lazy-loaded only when this command runs.

Slash commands run **terminal-native flows** locally (interactive numbered prompts / autocomplete) instead of going to the AI; anything else is natural language sent to Dailybot. The chat also recognizes some plain-language intents (e.g. "give kudos to Jane for the release", "show my check-ins") and routes them to the matching native flow — see `dailybot_cli/tui/intents.py`.

| Command | Behavior |
|---------|----------|
| `/help` | Show the command catalog. |
| `/clear` | Clear local transcript and start a new terminal session id. |
| `/status` | Login status + pending check-ins (`GET /v1/cli/auth/status/`, `GET /v1/cli/status/`). |
| `/dashboard` | Show the Dailybot dashboard URL. |
| `/checkins` | Complete pending check-ins with numbered prompts. |
| `/checkin edit` / `/checkin reset` | Edit or delete today's submitted response (`PUT` / `DELETE /v1/checkins/<uuid>/responses/`). |
| `/kudos` | Send kudos to users or teams (`POST /v1/kudos/`). |
| `/forms`, `/form submit\|responses\|update\|transition\|delete` | Full forms lifecycle (`/v1/forms/*`). |
| `/users`, `/teams`, `/team <name>` | Browse the org directory and teams (`/v1/users/`, `/v1/teams/*`). |
| `/mood` | Track today's mood (`GET` / `POST /v1/mood/track/`). |
| `/report` | Submit a free-text update (`POST /v1/cli/updates/`). |
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

### `dailybot me [--include-email] [--json]` — user-scoped, Bearer or API key auth

Shows the authenticated user and the org context of the active credential. Calls `GET /v1/me/`. `--include-email` adds the email to the rendered output; `--json` emits the raw payload.

### `dailybot org [--json]` — user-scoped, Bearer or API key auth

Shows the organization the credential is scoped to. Calls `GET /v1/organization/`.

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

#### `dailybot checkin status [--date YYYY-MM-DD] [--json]`

Shows each check-in with its pending/completed state for a date (default today). Calls `GET /v1/checkins/?date=...&include_summary=true`.

#### `dailybot checkin show <followup_uuid> [--json]`

Introspects a check-in's configuration and question definitions. Calls `GET /v1/checkins/<uuid>/` + `GET /v1/templates/<template_uuid>/?render_special_vars=true&followup_id=<uuid>`.

#### `dailybot checkin history <followup_uuid> [--days N | --from YYYY-MM-DD --to YYYY-MM-DD] [--user <uuid>] [--page N] [--page-size N] [--limit N] [--json]`

Lists response history for a check-in over a date range. Calls `GET /v1/checkins/<uuid>/responses/?date_start=...&date_end=...`. Check-ins are team-wide, so the endpoint returns **all participants'** responses by default (unlike forms, which default to the caller's own). `--user <uuid>` narrows to one participant for admin/manager callers; a member always sees only their own responses (server-side guard, no 403). `?all=true` is a no-op — the default already returns everyone. `--search` / `--grep` (from the [shared list query flags](#shared-list-query-flags)) filters by term. `--page` / `--page-size` / `--limit` return a single slice; with none of them the command walks every page, as it always has. `--user` accepts **only a UUID** — an email or a name is rejected client-side (the API answers `400 invalid_user_identifier`).

#### `dailybot checkin edit <followup_uuid> [-a index=response]... [--date YYYY-MM-DD] [--yes] [--json]`

Edits an existing response: fetches it (`GET .../responses/?user=<caller>`, scoped to the caller's own response since the endpoint otherwise returns all participants), applies `-a` overrides (or prompts each question with the current answer as default when a terminal is attached), then `PUT /v1/checkins/<uuid>/responses/`.

#### `dailybot checkin reset <followup_uuid> [--date YYYY-MM-DD] [--yes] [--json]`

Deletes (resets) your own response for a day via `DELETE /v1/checkins/<uuid>/responses/`. Confirms first unless `--yes` (or `--json`).

> **Backfill / future-dating:** `complete` (`--response-date`), `edit`/`reset`/`history` (`--date` / range) target other days. The server may reject with `previous_responses_are_not_allowed` / `future_responses_are_not_allowed` / `followup_not_allow_responses_before_trigger_time` if the check-in disallows it — the CLI maps these `code`s to friendly messages.

---

### Shared list query flags

`form list`, `kudos list`, and `workflow list` share a common pagination/search
surface; `form responses` and `checkin history` accept the `--search` subset.
Every list endpoint returns a `{ count, next, previous, results }` envelope
(handled by a shared paginated-GET helper in `api_client.py`), and list commands
print a `Showing X of N` count footer.

| Flag | Query param | Notes |
|------|-------------|-------|
| `--page N` | `page` | 1-based page number. |
| `--page-size N` | `page_size` | Results per page (max 100). |
| `--all` | — | Follows `next` until every page is fetched. |
| `--limit N` | — | Stops after N results (client-side). |
| `--search TEXT` / `--grep TEXT` | `search` | Max 256 chars; truncated client-side. |
| `--since YYYY-MM-DD` | `since` | On or after this date. |
| `--until YYYY-MM-DD` | `until` | On or before this date. |
| `--date YYYY-MM-DD` | `date` | Exact date. |
| `--last-week` | — | Shortcut for the previous seven days. |
| `--today` | — | Shortcut for today. |

Every `/v1` list endpoint returns the envelope unconditionally; no opt-in parameter is needed.

---

### `dailybot form` (group) — user-scoped, Bearer or API key auth

#### `dailybot form list [--json]`

Lists forms visible to the user. Calls `GET /v1/forms/?include=questions` to include question definitions. Accepts the [shared list query flags](#shared-list-query-flags).

#### `dailybot form get <form_uuid> [--json]`

Fetches a form's full payload via `GET /v1/forms/<uuid>/` — questions, workflow states, and permissions surface (`workflow_enabled`, `workflow_config.states`, `state_change_permission`, `view_reports_permission`, `edit_permission`, `allow_reopen_from_final_state`).

#### `dailybot form submit <form_uuid> [--content JSON] [--yes] [--json]`

Submits a form response. When `--content` is omitted, calls `GET /v1/forms/<uuid>/` to load questions and prompts each one interactively with type-aware inputs.

| Flag | Short | Notes |
|------|-------|-------|
| `--content` | `-c` | JSON map `{"<question_uuid>": "<answer>"}`. |
| `--yes` | `-y` | Skip confirmation prompt. |
| `--json` | | Machine-readable JSON output. |

#### `dailybot form responses <form_uuid> [--state STATE] [--latest] [--page N] [--page-size N] [--limit N] [--json]`

Lists responses (`GET /v1/forms/<uuid>/responses/`). Defaults to the caller's own. `--state` filters by workflow **state key** (`draft`, not the `Draft` label) — server-side, workflow forms only. On a form without a workflow the API returns `400 invalid_workflow_state` and the CLI explains that the flag doesn't apply. `--latest` returns only the most recent. `--all` / `--user <uuid>` surface everyone's / a specific user's responses and are admin/owner-only server-side (a member gets 403 / `form_response_view_all_forbidden`). `--from` / `--to` (`date_from`/`date_to`) narrow the window. `--search` / `--grep` (from the [shared list query flags](#shared-list-query-flags)) filters by term. `--page` / `--page-size` / `--limit` return a single slice; with none of them the command walks every page. Note `--all` here means *every author*, not every page. `--user` accepts **only a UUID**.

#### `dailybot form response get <form_uuid> <response_uuid> [--json]`

Fetches a single response (`GET /v1/forms/<uuid>/responses/<resp_uuid>/`) including `current_state`, `allowed_transitions`, `can_change_state`, and `state_history`. A 404 returns `{code: form_response_not_found}` (the API never leaks existence to callers without read permission).

#### `dailybot form update <form_uuid> <response_uuid> --content JSON [--yes] [--json]`

Merges new answers into a response via `PATCH /v1/forms/<uuid>/responses/<resp_uuid>/`. The server authorizes by role: the response author may always edit; a form owner / org admin may edit anyone's (audited as `metadata.last_edited_by`). A non-privileged edit of another user's response returns 403 / `form_response_edit_forbidden`.

#### `dailybot form transition <form_uuid> <response_uuid> <to_state> [--note ...] [--yes] [--json]`

Advances a response to `to_state` via `POST /v1/forms/<uuid>/responses/<resp_uuid>/transition/`. The form's `state_change_permission` audience is the sole gate — there is no response-author short-circuit. `--note` is recorded on the audit trail. 403 / `final_state_locked` fires when the response is in the final state and the form's `allow_reopen_from_final_state` is `false`.

#### `dailybot form delete <form_uuid> <response_uuid> [--yes] [--json]`

Deletes a response via `DELETE /v1/forms/<uuid>/responses/<resp_uuid>/`. Allowed for the response author, the form owner, or an org admin (403 / `form_response_delete_forbidden` otherwise).

---

### `dailybot channels list` — user-scoped, Bearer or API key auth

Lists report channels available to the caller via `GET /v1/report-channels/`. Channel UUIDs feed `--report-channel` on form/check-in create and edit.

---

### Forms & check-ins authoring — user-scoped, Bearer or API key auth

Creating and configuring forms/check-ins (as opposed to filling them in). All authoring is **role-gated server-side** (admins/managers/owners as applicable); the CLI performs only shape validation and surfaces the server's `403`. Both credentials work; an API key resolves to its admin owner.

| Command | HTTP | Notes |
|---|---|---|
| `form list [--include-archived]` | `GET /v1/forms/` (`?include_archived=true`) | Archived forms hidden by default; flagged in a Status column when shown. |
| `form create -n NAME [--questions-file F] [--interactive] [--report-channel UUID] [config flags]` | `POST /v1/forms/create/` (`name`, `questions?`, `report_channels?`, config all inline) | Question types: `text`, `multiple_choice`, `boolean`, `numeric`; ≤ 50. Config flags below. |
| `form edit <uuid> [--name] [--report-channel]` | `PATCH /v1/forms/<uuid>/config/` | Thin subset of `form config`. |
| `form config <uuid> [--name] [--report-channel] [config flags]` | `PATCH /v1/forms/<uuid>/config/` | Full form config (partial). Flags below. |

**Form config flags** (on `create` + `config`; only the ones you pass change): `--active/--inactive`, `--anonymous/--no-anonymous`, `--public/--no-public`, `--brand/--no-brand`, `--require-identity/--no-require-identity`, `--reopen-from-final/--no-reopen-from-final`, `--state "Label:#color"` (repeatable, ordered — enables the workflow) / `--no-workflow`, `--can-edit`/`--can-see`/`--can-change-states` (`everyone`/`owner_and_admins`, or `restricted` via `--{scope}-user`/`--{scope}-team`), `--approval/--no-approval` + `--approver-user`/`--approver-team`, `--command NAME`/`--no-command`. Sent inline; the server rejects unknown fields with `400 unknown_field` and validates each (`workflow_requires_states`, `invalid_workflow_state`, `invalid_permission_audience`, `invalid_approvers`, `invalid_command`, `command_already_exists`). Detail echoes them back. A form must have **at least one question** at create time (`questions_required`) — seed with `--questions-file`/`--interactive`. Unlike check-ins, form `is_anonymous` is freely toggleable (no `anonymous_irreversible`).
| `form archive <uuid>` | `DELETE /v1/forms/<uuid>/archive/` | Soft-delete (204). Confirms unless `--yes`. |
| `form questions list <uuid>` | `GET /v1/forms/<uuid>/` | Canonical question shape (see below). |
| `form questions add <uuid> --type --question [--options] [--required/--optional] [--blocker] [extras]` | `POST /v1/forms/<uuid>/questions/` | `multiple_choice` requires `--options`; `boolean` takes none. `--blocker` tags the blocker question. Extras below. |
| `form questions edit <uuid> <q_uuid> [... --blocker/--no-blocker] [extras]` | `PATCH /v1/forms/<uuid>/questions/<q_uuid>/` | Partial update (non-destructive). |

**Report title is required by the CLI.** When authoring a question (`questions add`, or seeding via `create --questions-file`/`--interactive`), a `--short-question` / `"short_question"` is **mandatory** — pass `--ai-short-question` to opt into Dailybot's AI generating it instead (AI titling only runs on intelligence-enabled check-ins). Server-side AI titling is a frontend-oriented convenience; agents/scripts should author explicit report titles. (`questions edit` doesn't require it — partial update.)

**Per-question extras** (on `questions add` + `edit`, both forms and check-ins): `--short-question` (title shown in web & chat reports, ≤512 chars), `--variation` (alternate phrasing rotated per run; repeatable, ≤10), and question logic via `--logic-file <path>` (a JSON `{"rules": {"rules_if": [...], "rules_else": {...}}}` object) or the inline single-jump shortcut `--jump-if-equals VALUE --jump-to N [--else-jump-to M]` (`N`/`M` = target question index, `-1` = end). A **`rules_else` fallback is required** and jump targets are **forward-only** (must be greater than the question's own index, or `-1`); the server owns the question index and rejects backward/out-of-range jumps. Navigation keys (`question_key`/`next_key`/`prev_key`) are computed server-side — never send them. Logic operators (server enforces per type): text — `is_equal_to`, `is_not_equal_to`, `contains`, `not_contains`, `begins_with`, `not_begins_with`, `ends_with`, `not_ends_with`; numeric — `is_equal_to`, `is_not_equal_to`, `lower_than`, `lower_or_equal_than`, `greater_than`, `greater_or_equal_than`; `multiple_choice`/`boolean` — `is_equal_to`, `is_not_equal_to`. Boolean comparison values are JSON `true`/`false` (the CLI coerces `--jump-if-equals true/false`). Actions: `jump_to` (int target), `trigger_checkin` / `trigger_form` (UUID target); connectors: `and`, `or` (`multiple_choice`: `or` only). Empty question text is rejected server-side (`question_label_required`); both check-ins and forms **require at least one question at create time** (`questions_required`) — the CLI fails fast if you create without `--questions-file`/`--interactive`. Question types remain `text`, `multiple_choice`, `boolean`, `numeric` (the complete catalog).
| `form questions delete <uuid> <q_uuid>` | `DELETE /v1/forms/<uuid>/questions/<q_uuid>/delete/` | Confirms unless `--yes`. |
| `form questions reorder <uuid> <q_uuid>...` | `PUT /v1/forms/<uuid>/questions/reorder/` | Unknown UUID → 400. |
| `checkin create -n NAME [--time --days --timezone \| --schedule-file] [--user --team] [--questions-file \| --interactive] [--report-channel]` | `POST /v1/checkins/create/` | `days` = ISO weekday ints (0=Sun…6=Sat). **Requires ≥1 participant** — with no `--user`/`--team` an interactive run prompts (default team suggested); non-interactive errors. |
| `checkin show <uuid>` | `GET /v1/checkins/<uuid>/detail/` | Canonical detail: schedule, resolved `participants`, attached `report_channels`, canonical questions. |
| `checkin config <uuid> [--name] [--time --days --timezone] [--report-channel] [--user --team] [--active/--inactive] [config flags]` | `PATCH /v1/checkins/<uuid>/config/` (accepts `participants` + full config) | `--user`/`--team` replace participants. Config flags below. |

**Check-in config flags** (on `create` + `config`; only the ones you pass change): `--start-on` / `--end-on` (`YYYY-MM-DD`), `--frequency weekly` (monthly/custom cadences → `--frequency-advanced`), `--every N`, `--trigger-based/--fixed-time`, `--participant-timezone/--custom-timezone`, `--reminders 0-5`, `--reminder-interval 0-60`, `--reminder-condition smart_frequency|fixed_frequency`, `--work-days/--no-work-days`, `--allow-early/--no-early`, `--allow-past/--no-past`, `--allow-future/--no-future`, `--anonymous/--no-anonymous`, `--privacy <level>`, `--one-by-one/--aggregated`, `--intro`/`--outro`, `--report-time HH:MM`, `--reminder-tone standard|persuasive`, `--smart/--no-smart`, `--intelligence/--no-intelligence` (requires `--smart`), `--max-clarifying 0-5` (requires `--intelligence`), `--frequency-advanced disabled|monthly|custom`, `--cron "<5-field>"`. Sent inline in the create/config body; the server rejects unknown fields with `400 unknown_field` and validates each (`invalid_frequency_type`, `invalid_reminder_count`, `invalid_reminder_tone`, `invalid_frequency_cron`, `intelligence_requires_smart_checkin`, …). Detail echoes them back. This surface is at 100% parity with the web UI; only the computed `summary` stays read-only.
| `checkin archive <uuid>` | `DELETE /v1/checkins/<uuid>/archive/` | Soft-delete (204). Confirms unless `--yes`. |
| `checkin questions add/edit/delete/reorder` | `.../v1/checkins/<uuid>/questions/...` | Same shapes as form questions (incl. `--blocker`). |

**Canonical question shape** (every read path — form detail, `form questions list`, `checkin show` detail): `{ uuid, index, question, question_type, required, is_blocker, choices }`. For `multiple_choice`, `choices` is a list of `{ label, value }` objects; for `text`/`boolean`/`numeric` it is `[]`.

> **Date-param asymmetry:** form response filters use `date_from`/`date_to`; check-in response filters use `date_start`/`date_end`. The CLI presents one `--from`/`--to` UX and maps per resource.

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

#### `dailybot kudos list [--filter received|given] [--json]`

Lists kudos the caller received or gave via `GET /v1/kudos/`. `--filter` selects the direction (received vs. given). Accepts the [shared list query flags](#shared-list-query-flags) (pagination, `--search`/`--grep`, and the date filters).

#### `dailybot kudos org [--json]`

Browse every kudos in the organization via `GET /v1/kudos/organization/` — the org-wide counterpart of `kudos list`, which is scoped to the caller. Admin-only (a non-admin receives `403`). Accepts the [shared list query flags](#shared-list-query-flags).

#### `dailybot kudos wall-of-fame [--limit N] [--json]`

Leaderboard of top kudos recipients via `GET /v1/kudos/wall-of-fame/`. `--limit` caps the number of entries returned.

---

### `dailybot user` (group) — user-scoped, Bearer or API key auth

#### `dailybot user list [--json]`

Lists organization members. Calls `GET /v1/users/` with automatic pagination (capped at `_MAX_LIST_PAGES = 50`). Table displays Name and UUID only — emails are not shown.

#### `dailybot user get <user_uuid> [--include-email] [--json]`

Fetches a single member via `GET /v1/users/<uuid>/`. `--include-email` adds the email to the rendered output (omitted by default, matching `user list`).

---

### `dailybot team` (group) — user-scoped, Bearer or API key auth

#### `dailybot team list [--json]`

Lists teams visible to the caller via `GET /v1/teams/`. **Visibility is scoped server-side**: admins see all org teams, members see only their own (via `teammembership_set`). The CLI never client-filters — it renders the server response verbatim.

#### `dailybot team get <team_uuid_or_name> [--with-members] [--json]`

Fetches a team via `GET /v1/teams/<uuid>/`. A name argument is resolved to UUID by calling `GET /v1/teams/` first (case-insensitive; ambiguous matches exit 2). `--with-members` adds a second call to `GET /v1/teams/<uuid>/members/`.

---

### `dailybot workflow` (group) — user-scoped, Bearer or API key auth

Read-only browsing of the org's workflows. Workflow writes are done in the web
app; this group only lists and retrieves. The feature is **plan-gated** — an org
on a plan without workflows gets `403 plan_upgrade_required` (with `upgrade_url`).

#### `dailybot workflow list [--json]`

Lists workflows visible to the caller via `GET /v1/workflows/`. Accepts the [shared list query flags](#shared-list-query-flags) (pagination + `--search`/`--grep`).

#### `dailybot workflow get <workflow_uuid> [--json]`

Fetches a single workflow via `GET /v1/workflows/<uuid>/`.

---

### User-scoped exit codes

All user-scoped commands (`checkin`, `form`, `kudos`, `user`, `team`, `workflow`, `me`, `org`) share these exit codes:

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
| `plan_upgrade_required` | 403 → exit 4 (payload carries `upgrade_url`) |
| `plan_free_api_keys_forbidden` | 403 → exit 4 |
| `plan_missing_core_api_integrations` | 403 → exit 4 |
| `api_key_owner_inactive` | 403 → exit 4 |
| `insufficient_role` | 403 → exit 4 |
| `member_in_scope_required` | 403 → exit 4 |
| `org_admin_required` | 403 → exit 4 |
| `target_user_inactive` | 400 → exit 2 |
| `search_query_too_long` | 400 → exit 2 |
| `invalid_date_range` | 400 → exit 2 |
| `free_plan_daily_limit_exceeded` | 403 → exit 4 |
| `send_as_user_conflict` | 400 → exit 2 |
| `send_as_user_invalid_uuid` | 400 → exit 2 |
| `send_as_user_not_found` | 404 → exit 5 |

The CLI dispatches on the machine-readable `code` field (never the `detail` prose). `plan_upgrade_required` additionally surfaces the `upgrade_url` from the payload.

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
`--send-as-user <UUID>`, `--send-as-me`,
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

**Send as a user (Slack only, admin-only).** `--send-as-user <UUID>` sets the
request's `send_as_user` field so the message is posted with that user's name
and profile picture; `--send-as-me` is the shortcut for the authenticated user.
Both require org-admin rights and are mutually exclusive with `--bot-name` /
`--bot-icon-url` / `--bot-icon-emoji`. Server-side codes: `send_as_user_conflict`
(combined with a bot-identity flag), `send_as_user_invalid_uuid`, and
`send_as_user_not_found`.

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
| `POST` | `/v1/cli/chat/completions/` | `{ message?, history?, messages?, session_id?, reset_thread?, available_commands? }` | `{ status, async, correlation_id, classification, message: {role, content}, actions }` | AI chat (`dailybot ask` / `interactive`); 120s timeout; **30 req/min per API key** (429 carries `Retry-After`) |

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
| `GET` | `/v1/forms/<uuid>/responses/` | `?state`, `?all=true`, `?user`, `?date_from`, `?date_to` (all optional) | `[{ id, current_state, allowed_transitions, can_change_state, state_history, content, edited, created_at }]` | Own by default; `all`/`user` admin/owner-only (403 `form_response_view_all_forbidden`) |
| `GET` | `/v1/forms/<uuid>/responses/<resp_uuid>/` | — | Same shape as above | 404 = `form_response_not_found` |
| `PATCH` | `/v1/forms/<uuid>/responses/<resp_uuid>/` | `{ content: { ... } }` | Updated response | Own always; owner/admin may edit anyone (audited) |
| `POST` | `/v1/forms/<uuid>/responses/<resp_uuid>/transition/` | `{ to_state, note? }` | Updated response | 403 = `form_response_change_state_forbidden` or `final_state_locked` |
| `DELETE` | `/v1/forms/<uuid>/responses/<resp_uuid>/` | — | 204 | Author / owner / admin |
| `GET` | `/v1/report-channels/` | `?name` (prefix filter), `?limit` (both optional) | `{ channels: [{ id, name, platform, type }], total }` (also accepts `{results}` / bare list) | `channels list`; `id` feeds `--report-channel` |
| `GET` | `/v1/forms/` | `?include=questions`, `?include_archived=true` | `[{ id, name, is_active, is_archived, questions? }]` | `form list`; archived hidden unless opted in |
| `POST` | `/v1/forms/create/` | `{ name, questions?: [...], report_channels?: [...] }` | `{ id, name, is_active, is_archived, questions, report_channels }` | Role-gated; `form create` |
| `PATCH` | `/v1/forms/<uuid>/config/` | `{ name?, report_channels?, is_active?, is_anonymous?, allow_public_responses?, require_email_and_name?, brand_with_logo?, allow_reopen_from_final_state?, workflow?, who_can_edit?, who_can_see_responses?, who_can_change_states?, use_for_approval?, approvers?, command_enabled?, command? }` | Form | `form edit` / `form config` |
| `DELETE` | `/v1/forms/<uuid>/archive/` | — | 204 (sets `is_active=false` + `is_archived=true`) | `form archive` (soft-delete) |
| `POST` | `/v1/forms/<uuid>/questions/` | `{ question_type, question, options?, required?, is_blocker? }` | Question | `form questions add` |
| `PATCH` | `/v1/forms/<uuid>/questions/<q_uuid>/` | partial | Question | `form questions edit` |
| `DELETE` | `/v1/forms/<uuid>/questions/<q_uuid>/delete/` | — | 204 | `form questions delete` |
| `PUT` | `/v1/forms/<uuid>/questions/reorder/` | `{ order: [q_uuid...] }` | `{ reordered: true }` | `form questions reorder` |
| `POST` | `/v1/checkins/<followup_uuid>/responses/` | `{ responses: [{ uuid, index, response }], last_question_index?, response_date? }` | `{ uuid }` | |
| `GET` | `/v1/checkins/` | — | `{ results: [{ id, name, ... }], next? }` (or bare list) | Paginated; terminal check-in flows |
| `GET` | `/v1/checkins/<followup_uuid>/` | — | `{ ... }` | v2 retrieve serializer (different shape) |
| `GET` | `/v1/checkins/<followup_uuid>/detail/` | — | `{ id, name, is_archived, schedule, questions, participants: {users,teams}, report_channels: [{id,name,platform,type,reporting_enabled}] }` | **Canonical** authoring read; `checkin show` |
| `GET` | `/v1/templates/<template_uuid>/` | `?render_special_vars=true&followup_id=<uuid>` | `{ questions: [...] }` | Question definitions for a check-in |
| `GET` | `/v1/checkins/<followup_uuid>/responses/` | `?date_start&date_end`, `?user` (`?all=true` = no-op) | `[{ ... }]` | History; default = **all participants**. `user` narrows (admin/manager); members guarded to own |
| `PUT` | `/v1/checkins/<followup_uuid>/responses/` | `{ responses: [...], last_question_index? }` | Updated response | `/checkin edit` |
| `DELETE` | `/v1/checkins/<followup_uuid>/responses/` | `?date_start&date_end` | 204 | `/checkin reset` |
| `POST` | `/v1/checkins/create/` | `{ name, schedule?, participants?, questions?, report_channels? }` | Check-in | Role-gated; `checkin create` |
| `PATCH` | `/v1/checkins/<followup_uuid>/config/` | `{ name?, schedule?, report_channels?, is_active? }` | Check-in | `checkin config` |
| `DELETE` | `/v1/checkins/<followup_uuid>/archive/` | — | 204 (sets `active=false` + `archived=true`) | `checkin archive` (soft-delete) |
| `POST` | `/v1/checkins/<followup_uuid>/questions/` | `{ question_type, question, options?, required?, is_blocker? }` | Question | `checkin questions add` |
| `PATCH` | `/v1/checkins/<followup_uuid>/questions/<q_uuid>/` | partial | Question | `checkin questions edit` |
| `DELETE` | `/v1/checkins/<followup_uuid>/questions/<q_uuid>/delete/` | — | 204 | `checkin questions delete` |
| `PUT` | `/v1/checkins/<followup_uuid>/questions/reorder/` | `{ order: [q_uuid...] }` | `{ reordered: true }` | `checkin questions reorder` |
| `GET` | `/v1/mood/track/` | `?date` | `{ ... }` | Read today's mood |
| `POST` | `/v1/mood/track/` | `{ score, date? }` | `{ ... }` | `/mood` |
| `GET` | `/v1/me/` | — | `{ user: { uuid, full_name, email }, organization: { uuid, name } }` | `dailybot me` |
| `GET` | `/v1/organization/` | — | `{ uuid, name, ... }` | `dailybot org` |
| `GET` | `/v1/users/` | — | `{ results: [{ uuid, full_name }], next: url\|null }` | Paginated |
| `GET` | `/v1/users/<uuid>/` | — | `{ uuid, full_name, email? }` | `dailybot user get` |
| `GET` | `/v1/teams/` | — | `{ results: [{ uuid, name, active, members_count, is_default }], next? }` | Server-scoped: admins see all, members see own |
| `GET` | `/v1/teams/<uuid>/` | — | `{ uuid, name, active, ... }` | Same scoping |
| `GET` | `/v1/teams/<uuid>/members/` | — | `[{ uuid, full_name, email }]` | Members of a team the caller can see |
| `POST` | `/v1/kudos/` | `{ content, receivers: [...uuid], users_receivers?: [...], teams_receivers?: [...], company_value? }` | `{ uuid }` | `receivers` = users+teams merged (validation); `users_receivers`/`teams_receivers` drive team expansion. Payload contract is being reconciled server-side — see the integration prompt. 406 = daily limit |
| `GET` | `/v1/kudos/` | `?filter=kudos_received\|kudos_given` (the CLI accepts `received`/`given` and the `KUDOS_*` forms and normalizes them), shared list params (all optional) | `{ count, next, previous, results }` | `kudos list` |
| `GET` | `/v1/kudos/organization/` | list flags | `{count, next, previous, results}` | `kudos org`; admin-only (Bearer or X-API-KEY) |
| `GET` | `/v1/kudos/wall-of-fame/` | `?limit` (optional) | `{ count, next, previous, results }` | `kudos wall-of-fame` |
| `GET` | `/v1/workflows/` | shared list params (all optional) | `{ count, next, previous, results }` | `workflow list`; plan-gated (403 `plan_upgrade_required`) |
| `GET` | `/v1/workflows/<uuid>/` | — | `{ uuid, name, ... }` | `workflow get`; plan-gated |

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
| `POST` | `/v1/send-message/` | `{ message?/messages?, image_url?, buttons?, thread_responses?, target_users?/target_channels?/target_teams?, platform_settings?, metadata?, skip_users_on_time_off?, send_as_user?, bot_message_id? }` | `{ bot_message_id, thread_responses?: [ids] }` | **X-API-KEY or Bearer** (login, role-scoped); ≥1 target; `thread_responses` posts replies in the parent thread (≤10); `send_as_user` (Slack, admin-only) posts with that user's identity; `bot_message_id` in → edits that message (parent or reply) |
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
