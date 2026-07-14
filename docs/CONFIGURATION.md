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
| `<repo>/.dailybot/env.json` | `dailybot env` / hand-authored, **gitignored** | `{ disabled?, active?, profiles: [{ name, api_key, api_url?, app_url? }, ...] }` | `0o600` |

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
| `report` | object | Per-repo policy for the `dailybot hook` reminders: `{ "min_interval_minutes": 30, "nudge": true, "mode": "balanced", "soft_turn_threshold": 8 }`. `nudge: false` silences end-of-turn report reminders for the repo; `mode: "continuous"` lowers the soft-nudge thresholds (interval `20`, turns `5` when those keys are omitted) so research/docs-heavy repos are reminded about non-commit work sooner; `soft_turn_threshold` overrides the agent-turns-without-a-report count before a soft nudge. Invalid `mode`/`soft_turn_threshold` values fall back to the defaults. Requires CLI `>= 1.19.0` (older CLIs ignore `mode`/`soft_turn_threshold`). See [AGENT_HOOKS.md](AGENT_HOOKS.md). |

**Security rule:** a `key` field is rejected with a hard error — credentials must never be committed. The file is plain text and lives in the repo, so it must remain free of secrets. Unknown future keys log a one-line warning and are ignored (forward compatibility). Malformed JSON falls back to the global config with a warning.

## Repo-level env override (`.dailybot/env.json`)

`.dailybot/env.json` is an **opt-in, gitignored** file that carries API keys and optional URL overrides for one or more environments (production, local dev orgs, staging). It sits **beside** `profile.json` in `.dailybot/` and serves a different purpose: `profile.json` pins the *identity* of an agent (committed, shared), `env.json` pins the *auth context* (per-machine, per-developer, never committed).

Introduced in CLI `>= 3.7.0`.

### Why it exists

Before `env.json`, switching between local dev orgs / staging / production required exporting `DAILYBOT_API_URL` / `DAILYBOT_APP_URL` / `DAILYBOT_API_KEY` for every shell, or reconfiguring the global `agents.json`. This got painful when a developer wanted:

- Repo A "logged into" org X
- Repo B "logged into" org Y

Both simultaneously, from any shell, with zero env-var management. `env.json` gives each repo its own credential context that follows the working directory.

### Schema

```json
{
  "disabled": false,
  "active": "local org 1",
  "profiles": [
    {
      "name": "live",
      "api_key": "sk_live_xxxxxxxxxxxx"
    },
    {
      "name": "local org 1",
      "api_key": "sk_local_xxxxxxxxxxxx",
      "api_url": "http://localhost:8000",
      "app_url": "http://localhost:8090"
    },
    {
      "name": "staging",
      "api_key": "sk_staging_xxxxxxxxxxxx",
      "api_url": "https://staging-api.example.com",
      "app_url": "https://staging-app.example.com"
    }
  ]
}
```

| Field | Type | Required | Purpose |
|---|---|---|---|
| `disabled` | boolean | optional (default `false`) | **Kill-switch.** When `true`, the entire file is ignored even if `active` points to a valid profile. Use to temporarily disable the override while preserving the selection (`dailybot env off` / `dailybot env on`). |
| `active` | string \| null | optional | Name of the profile to use. `null`, empty string, missing, or pointing at an unknown name all render the file *inert* (resolution continues to lower layers). Only one active at a time — impossible to be ambiguous. |
| `profiles` | list of objects | **required** | Every configured environment. Each entry needs `name` and `api_key`; `api_url` and `app_url` are optional. |
| `profiles[].name` | string | **required** | Unique per file. Human-friendly (spaces allowed). |
| `profiles[].api_key` | string | **required** | The API key for this environment. Stored in plain text — gitignore is mandatory. |
| `profiles[].api_url` | string | optional | Overrides `DAILYBOT_API_URL` / `credentials.json` when this profile is active. Trailing slashes normalized. Falls through to `DEFAULT_API_URL` when absent. |
| `profiles[].app_url` | string | optional | Overrides `DAILYBOT_APP_URL` when this profile is active. Falls through to `DEFAULT_APP_URL` when absent. |

### CLI commands

```bash
dailybot env add \
  --name "local org 1" \
  --key sk_xxx \
  --api-url http://localhost:8000 \
  --app-url http://localhost:8090       # Creates env.json + auto-active if first
dailybot env add --name live --key sk_live_yyy   # Appends without changing active
dailybot env use "local org 1"          # Switch active
dailybot env use ""                     # Clear active (fall through to global)
dailybot env show                       # Show resolved profile (key masked)
dailybot env list                       # All profiles in the file
dailybot env remove "local org 1"       # Remove a profile (confirms first, --yes to skip)
dailybot env off                        # Disable the file (preserves active)
dailybot env on                         # Re-enable
```

### Security guarantees

1. **Gitignored by convention.** The repo's root `.gitignore` should carry `.dailybot/*` with an explicit exception only for `!.dailybot/profile.json`. `env.json` is NEVER excepted. See the [example .gitignore for this repo](../.gitignore).
2. **`0o600` permissions.** Every write via `dailybot env` — and every load — enforces owner-only permissions defensively (in case an editor created the file with a lax umask).
3. **Fatal refuse-if-tracked guard.** On every load, the CLI runs `git ls-files --error-unmatch .dailybot/env.json` and raises `RepoEnvError` if the file is tracked. Any `dailybot env` subcommand (and any subsequent command that would consume env.json auth) exits non-zero with an actionable message:
   ```
   .dailybot/env.json is tracked by git. This file contains API keys and
   must never be committed. Fix with:
     git rm --cached .dailybot/env.json
     # ensure your .gitignore ignores .dailybot/env.json
     git commit -m 'chore: untrack .dailybot/env.json'
   The CLI refuses to load env.json while it is tracked.
   ```
4. **Masked in all output.** `dailybot env show` and `dailybot env list` mask API keys as `abcd****` (first 4 chars + `****`), matching the pattern used by `dailybot config key`.

### Auth-resolution precedence (updated)

The full order for **`api_key`**:

1. `.dailybot/env.json` active profile's `api_key` (walk-up from cwd) — new in 3.7.0
2. `DAILYBOT_API_KEY` env var
3. `config.json::api_key` (from `dailybot config key=...`)

The full order for **`api_url`**:

1. `--api-url` CLI flag
2. `.dailybot/env.json` active profile's `api_url` — new in 3.7.0
3. `DAILYBOT_API_URL` env var
4. `credentials.json::api_url` (from the login session)
5. `DEFAULT_API_URL` (`https://api.dailybot.com`)

The full order for **`app_url`**:

1. `--app-url` CLI flag
2. `.dailybot/env.json` active profile's `app_url` — new in 3.7.0
3. `DAILYBOT_APP_URL` env var
4. `DEFAULT_APP_URL` (`https://app.dailybot.com`)

When `env.json::disabled` is `true` or `active` is empty/null/unknown, the file is transparently skipped and every resolver behaves as if the file didn't exist.

### Interaction with `profile.json`

The two files are **orthogonal** and both can be present:

| File | Committed | Contains | Rules |
|---|---|---|---|
| `.dailybot/profile.json` | Yes (tracked) | `name`, `default_metadata`, `report`, `vars` — **identity** | `key` field fatally rejected. |
| `.dailybot/env.json` | **No** (gitignored) | `api_key`, `api_url`, `app_url` per profile — **auth context** | `agent_name` / `default_metadata` NOT allowed (belongs in `profile.json`). Fatally rejected when tracked. |

`profile.json` still governs how reports are *signed* even when `env.json` provides the credentials to send them.

### Interaction with the login Bearer token

When an `env.json` active profile provides an `api_key`, the CLI's `DailyBotClient` receives that key and — because Bearer is preferred over API key in `_headers()` — the presence of the login Bearer token would normally still win. To make "logged into different orgs in different repos" work correctly, the client should be constructed such that the API key takes precedence for env.json-authored contexts.

Two ways this is achieved in practice:

- **Different API URLs.** When the env.json profile carries `api_url` pointing at, say, `http://localhost:8000` while the stored Bearer session was issued against `https://api.dailybot.com`, the URL alone routes correctly and the server-side auth is the only thing that matters (each env has its own key/token).
- **Auto-fallback on 401.** As of CLI `>= 3.5.1`, if Bearer fails with 401, the client automatically retries with the alternative credential (API key). So even if the Bearer wins the initial dispatch and the token isn't valid on the env.json's API, the API key retry succeeds.

For a bulletproof "different org per repo" story, prefer profiles with distinct `api_url`s or use `dailybot logout` on machines where the mix would be ambiguous.

### When NOT to use `env.json`

- **CI environments** — prefer `DAILYBOT_API_KEY` as an env var; leaves no on-disk secret to clean up between jobs.
- **Single-org development** — `dailybot login` + a global `agents.json` profile is simpler.
- **Team-shared identity** — that's `profile.json`'s job. `env.json` is per-developer, per-machine.

## Environment Variables

| Variable | Read by | Effect |
|----------|---------|--------|
| `DAILYBOT_CONFIG_DIR` | `get_config_dir()` | Redirects all config/credential file I/O to this directory instead of `~/.config/dailybot/`. Useful for dev sandboxes (`clitest`) and CI environments. |
| `DAILYBOT_API_URL` | `get_api_url()` | Overrides the API base URL (after `--api-url` flag) |
| `DAILYBOT_APP_URL` | `get_app_url()` | Overrides the webapp/dashboard base URL (after `--app-url` flag). Default: `https://app.dailybot.com`. For local development: `http://localhost:8090`. |
| `DAILYBOT_API_KEY` | `get_api_key()` | Provides an org API key without storing it on disk |
| `DAILYBOT_CLI_TOKEN` | `get_token()` | Provides a login Bearer token without `dailybot login` |

`--api-url` (root flag) takes precedence over `DAILYBOT_API_URL`.
`--app-url` (root flag) takes precedence over `DAILYBOT_APP_URL`.

## Auth Resolution Order

### For `dailybot login` / `logout`

The OTP login flow issues the Bearer token; `logout` clears it. These are inherently tied to the login session.

### For user / CLI commands (`status` / `update` / `checkin` / `form` / `kudos` / `team` / `user` / `chat`)

These accept **either** a login session Bearer token **or** an org API key. The `status` / `update` commands gate via their own `get_agent_auth()` check; the user-scoped commands use `require_auth()` from `public_api_helpers.py`. Either way, resolution is:

1. Login session Bearer token (`credentials.json::token`), preferred when present
2. Org API key (`DAILYBOT_API_KEY` env var, then `config.json::api_key`)

The command exits non-zero (`Not authenticated. Run: dailybot login or set DAILYBOT_API_KEY`) only when **neither** credential is present. The `DailyBotClient._headers()` helper prefers the Bearer token and falls back to `X-API-KEY`; the server resolves the acting user from the API key's owner, so both paths behave identically.

### For `dailybot status --auth`

Tries OTP login first (Bearer), then API key. Reports which one succeeded.

### For `dailybot agent` commands

The full resolution (see `_resolve_agent_context` in `commands/agent.py`):

**Profile slug** (which entry of `agents.json` to load credentials from):

1. `--profile <name>` flag
2. `.dailybot/profile.json::profile` (closest ancestor along `$PWD` → `/`)
3. Default profile from `agents.json`

**Credentials** (highest layer wins; env.json is the newest layer, sits above everything except a `--profile` flag):

1. `.dailybot/env.json` active profile's `api_key` (walk-up from cwd) — new in 3.7.0
2. `<profile>::api_key` from `agents.json` (when profile slug is set)
3. `DAILYBOT_API_KEY` env var
4. `config.json::api_key` (set via `dailybot config key=...`)
5. Login session Bearer token (`credentials.json::token`)

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

### Local development URLs

When testing against the local server:

| Service | URL |
|---------|-----|
| API | `http://djangovscode:8000` |
| Webapp / Dashboard | `http://localhost:8090` |

```bash
export DAILYBOT_API_URL=http://djangovscode:8000
export DAILYBOT_APP_URL=http://localhost:8090
```

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
