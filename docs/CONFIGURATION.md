# Configuration & Credentials

The Dailybot CLI persists state in `~/.config/dailybot/` by default. The path can be overridden by setting `DAILYBOT_CONFIG_DIR` (see Environment Variables below). All files that contain secrets are written with mode `0o600`.

## Files

| File | Owner | Contents | Permissions |
|------|-------|----------|-------------|
| `credentials.json` | `dailybot login` | `{ token, email, organization, organization_uuid, api_url }` | `0o600` |
| `config.json` | `dailybot config` | `{ api_key }` (and any future settings) | `0o600` |
| `agents.json` | `dailybot agent configure` / `register` | `{ default, profiles: { <slug>: { agent_name, api_key?, agent_email? } } }` | `0o600` |
| `org_cache.json` | `dailybot login --email` (step 1) | `{ email, organizations: [...] }` | (no chmod — non-secret) |
| `ledger/<repo-slug>.json` | `dailybot hook ...` / `dailybot agent update` | Per-repo report ledger: `{ repo, first_seen_at, last_report_at, last_reported_commit, last_nudge_at, last_activity_at, work_pending, snoozed_until, turns_since_report, reported_by }` | `0o600` (dir `0o700`) |
| `ledger/_global.json` | `dailybot hook session-start` | Cross-repo hook state: `{ last_login_nudge_at }` | `0o600` |
| `<repo>/.dailybot/profile.json` | hand-authored, committed to git | `{ name?, profile?, default_metadata?, vars?, report? }` | (no chmod — must be readable by team) |

### Schema notes

**`credentials.json`** — created by `save_credentials(...)`. Backwards-compatible additions are safe; `load_credentials()` treats missing keys as absent. The `api_url` field captures which API the user authenticated against, so re-running commands from a different default URL doesn't accidentally use the wrong one.

**`config.json`** — extended via `save_config({...})`. Setting a key to `None` removes it. Accessed only through `load_config()` / `save_config()` — never read directly elsewhere.

**`agents.json`** — `default` points to a profile slug under `profiles`. Slugs are derived from the agent name via `_slugify` (lowercase, alphanumeric + hyphens). When `save_agent_profile` is called and `default` is unset, the new profile becomes the default automatically.

**`org_cache.json`** — written during step 1 of non-interactive multi-org login (`--email` only). Read during step 2 (`--code --org=<uuid>`) to resolve a UUID → integer ID **without** re-issuing `request_code`, which would invalidate the OTP. Cleared after a successful verification.

**`ledger/`** — the local report ledger backing the `dailybot hook` lifecycle commands (added in the same release as the `hook` group; older CLIs simply never create the directory). One JSON file per repository, keyed by a slug derived from the `origin` remote, plus `_global.json` for cross-repo state. It stores bookkeeping only (timestamps, one commit SHA, a counter) — never report content or secrets. The ledger is a recoverable cache: deleting any file is safe and merely re-anchors the repo's baseline. Written atomically (temp file + rename). Full semantics: [AGENT_HOOKS.md](AGENT_HOOKS.md).

**`<repo>/.dailybot/profile.json`** — repo-level agent profile, intended to be committed so every contributor signs reports under the same identity. Discovery walks up from `$PWD` to `/`; the first ancestor that contains the file wins. All keys are optional:

| Key | Type | Purpose |
|-----|------|---------|
| `name` | string | Overrides the agent display name (`--name` equivalent) |
| `profile` | string slug | Selects an entry in the global `agents.json` for credentials |
| `default_metadata` | object | Shallow-merged into every report's `--metadata` (inline keys win per-key) |
| `vars` | object | Free-form repo variables for scripts, skills, and automation. The CLI carries this key but never sends it in reports or warnings. |
| `report` | object | Per-repo policy for the `dailybot hook` reminders: `{ "min_interval_minutes": 30, "nudge": true }`. `nudge: false` silences end-of-turn report reminders for the repo. See [AGENT_HOOKS.md](AGENT_HOOKS.md). |

**Security rule:** a `key` field is rejected with a hard error — credentials must never be committed. The file is plain text and lives in the repo, so it must remain free of secrets. Unknown future keys log a one-line warning and are ignored (forward compatibility). Malformed JSON falls back to the global config with a warning.

## Environment Variables

| Variable | Read by | Effect |
|----------|---------|--------|
| `DAILYBOT_CONFIG_DIR` | `get_config_dir()` | Redirects all config/credential file I/O to this directory instead of `~/.config/dailybot/`. Useful for dev sandboxes (`clitest`) and CI environments. |
| `DAILYBOT_API_URL` | `get_api_url()` | Overrides the API base URL (after `--api-url` flag) |
| `DAILYBOT_API_KEY` | `get_api_key()` | Provides an org API key without storing it on disk |
| `DAILYBOT_CLI_TOKEN` | `get_token()` | Provides a login Bearer token without `dailybot login` |

`--api-url` (root flag) takes precedence over `DAILYBOT_API_URL`.

## Auth Resolution Order

### For `dailybot login` / `logout` / `status` / `update` / `checkin` / `form` / `kudos` / `user`

These commands only accept the **login session Bearer token**. The user-scoped commands (`checkin`, `form`, `kudos`, `user`) use `require_bearer_auth()` from `public_api_helpers.py`, which exits with code 3 if no token is found. Resolution:

1. `DAILYBOT_CLI_TOKEN` env var
2. `credentials.json::token`

If neither is present, the command exits with `Not logged in. Run: dailybot login`.

### For `dailybot status --auth`

Tries OTP login first (Bearer), then API key. Reports which one succeeded.

### For `dailybot agent` commands

The full resolution (see `_resolve_agent_context` in `commands/agent.py`):

**Profile slug** (which entry of `agents.json` to load credentials from):

1. `--profile <name>` flag
2. `.dailybot/profile.json::profile` (closest ancestor along `$PWD` → `/`)
3. Default profile from `agents.json`

**Credentials** (resolved against the selected profile, then via legacy fallback):

1. `<profile>::api_key` from `agents.json`
2. `DAILYBOT_API_KEY` env var
3. `config.json::api_key` (set via `dailybot config key=...`)
4. Login session Bearer token (`credentials.json::token`)

A profile that has no `api_key` but a login session is allowed — it just uses the Bearer token. A profile that has neither is an error. If `.dailybot/profile.json::profile` points at a slug that does not exist in `agents.json`, the CLI warns once and falls through to session credentials (this is **not** a hard error so the repo file can roll out safely before every developer has configured the matching local profile).

**Agent display name** (per-field precedence — highest layer wins):

1. `--name` flag
2. `.dailybot/profile.json::name`
3. Selected profile's `agent_name`
4. Fallback: `"CLI Agent"`

**`default_metadata`** is merged shallow per-key into every outgoing `--metadata`: inline `--metadata` keys win, missing keys fall through from the repo file. This is applied by `dailybot agent update` and `dailybot agent email send`.

To inspect what the CLI will use in the current directory:

```bash
dailybot agent profiles --resolve
```

The output shows each resolved field plus which layer it came from.

> **Do not change this order without bumping the minor version and writing a migration note.** It is observable behavior for users with multiple credentials configured.

## Common Configuration Tasks

### Switching between staging and production

```bash
# One-off
dailybot --api-url https://staging.dailybot.com login --email me@example.com

# Persistent (all subsequent commands until unset)
export DAILYBOT_API_URL=https://staging.dailybot.com
```

The login session is scoped to the API URL it was authenticated against (the URL is stored in `credentials.json`), so logging into staging won't accidentally let you act on production.

### Wiping all local state

```bash
rm -rf ~/.config/dailybot/
```

Forces re-login on next run. Safe to run any time.

### Inspecting current state

```bash
ls -la ~/.config/dailybot/
cat ~/.config/dailybot/agents.json | jq .
cat ~/.config/dailybot/credentials.json | jq '{email, organization, api_url}'  # masks the token
```

### Configuring a CI environment

```bash
# Preferred: env var, not on-disk
export DAILYBOT_API_KEY=dbk_xxxxxxxxxxxx
dailybot agent update "Build #${BUILD_ID} passed" --name "CI Bot"
```

Avoid `dailybot config key=...` in CI — it writes to disk and is awkward to clean up between jobs.

## Adding a New Configuration Key

1. Add a constant in `config.py` for the file path if you're introducing a new file.
2. Add `load_X()` / `save_X(...)` / `clear_X()` helpers.
3. **chmod 0600** if the file contains anything sensitive.
4. If reading from an env var, follow the existing pattern (`os.environ.get(...)` first, on-disk second).
5. Document it here, in `AGENTS.md`, and in `SECURITY.md` if applicable.
6. Add a test in `tests/config_test.py`.
