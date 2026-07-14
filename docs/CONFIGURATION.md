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

> ## STOP — Read this before you author `env.json`
>
> **`.dailybot/env.json` MUST NEVER be committed to git. Ever. Under any circumstance.**
>
> The file stores API keys in plain text. Once committed to a repo — public or private — the keys are considered leaked and MUST be rotated. Git history is forever; a `git revert` does not undo the exposure.
>
> The CLI enforces this rule with **four independent protections (three enforced + one advisory)** — all of them must be in place, and any of them tripping is treated as a security incident, not a warning:
>
> 1. **Gitignore rule (mandatory).** The repo's `.gitignore` MUST contain `.dailybot/*` **without** ever un-ignoring `env.json`. Only `profile.json` may be excepted. This repo's [`.gitignore`](../.gitignore) is the reference implementation.
> 2. **`0o600` file permissions.** Every write via `dailybot env` creates the file with mode `0o600` from the first byte (`os.open(..., 0o600)` — no umask window), and every load re-chmods it defensively. Even shared workstations cannot leak the file laterally.
> 3. **Fatal refuse-if-tracked guard.** The root `cli()` callback calls `load_repo_env()` on every invocation. If `.dailybot/env.json` exists AND `git ls-files --error-unmatch .dailybot/env.json` returns 0 (i.e. the file is tracked — staged counts too, a commit is not required), the CLI **immediately refuses to run any command** — `status`, `user list`, `form list`, `agent update`, `env show`, everything — and prints the exact `git rm --cached` recipe. There is no partial degradation, no silent fallback to global auth. The user must untrack the file before the CLI does anything else. Exactly two carve-outs: `--help` / `--version` (Click short-circuits them before the callback) so the user can always read instructions, and the `hook` group, which prints the same error to stderr but exits 0 — its contract ([docs/AGENT_HOOKS.md](AGENT_HOOKS.md)) is "always exit 0, never break the agent harness", and hooks never consume env.json auth. If git is not on PATH but a `.git` directory exists in an ancestor, the guard cannot verify tracking and degrades to a loud warning.
> 4. **Write-time gitignore warning (advisory).** `dailybot env add` runs `git check-ignore` after writing and warns on stderr when the file is not covered by any ignore rule.
>
> **If any of these protections appears to be missing or misbehaving on your machine, treat it as a bug and report it — don't work around it.**
>
> **If you have already committed `env.json`**, follow these steps in order:
>
> 1. **Rotate every key in the file immediately** (via the Dailybot dashboard). The old keys are compromised.
> 2. `git rm --cached .dailybot/env.json`
> 3. Verify `.gitignore` contains `.dailybot/*` (add it if missing).
> 4. `git commit -m "chore: untrack .dailybot/env.json"`
> 5. Force-clean the file from git history if the repo has been pushed anywhere (see [GitHub's guide to removing sensitive data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)).
> 6. Only then re-author `env.json` with the freshly rotated keys.
>
> When in doubt, prefer `DAILYBOT_API_KEY` (an environment variable, never on disk in the repo) — that path has no exposure surface at all.

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

Cross-referenced with the top-of-section STOP block. Repeated here so this appears in every table-of-contents jump.

1. **Gitignored by convention (`.gitignore`).** The repo's root `.gitignore` MUST carry `.dailybot/*`. `profile.json` is the ONLY file allowed to be excepted (`!.dailybot/profile.json`). `env.json` is NEVER excepted — no exception, no per-machine dot-file trick, nothing. See the [example .gitignore for this repo](../.gitignore).
2. **`0o600` file permissions.** Every write via `dailybot env` AND every load re-chmods the file to owner-only, defensively (in case an editor created the file with a lax umask). Enforced in `dailybot_cli/config.py::save_repo_env`.
3. **Fatal refuse-if-tracked guard — enforced at the ROOT `cli()` callback.** On every command invocation (yes, including non-`env` commands like `status`, `user list`, `form list`, `agent update`), the CLI runs `load_repo_env()`, which internally runs `git ls-files --error-unmatch .dailybot/env.json`. If the file is tracked, `RepoEnvError` is raised, `print_error()` writes the message to stderr, and `SystemExit(1)` aborts the process **before any subcommand runs**. Sample stderr output:
   ```
   Error: /path/to/repo/.dailybot/env.json is tracked by git. This file contains
   API keys and must never be committed. Fix with:
     git rm --cached .dailybot/env.json
     # ensure your .gitignore ignores .dailybot/env.json
     git commit -m 'chore: untrack .dailybot/env.json'
   The CLI refuses to load env.json while it is tracked.
   ```
   **No auth-consuming command bypasses this** — `dailybot version`, `dailybot upgrade`, `dailybot uninstall`, `dailybot login`, `dailybot logout`, everything is blocked. Only `dailybot --help` / `dailybot --version` (Click short-circuits) still work so the developer can read instructions, and `dailybot hook *` prints the same error to stderr but exits 0 to honor its always-exit-0 harness contract (hooks are local-only and never consume env.json auth). This is the third and final layer that guarantees the CLI cannot silently degrade to global auth while `env.json` (and the keys it contains) leaks in git history.
4. **Masked in all output.** `dailybot env show`, `dailybot env list`, and `dailybot agent profiles --resolve` all mask API keys as `abcd****` (first 4 chars + `****`), matching the pattern used by `dailybot config key`. Full keys never appear in logs, stderr, error traces, or telemetry.
5. **No key export.** There is intentionally no `dailybot env export` or `dailybot env cat` command that would print the raw keys to stdout. Editing the file requires opening it in a text editor (which triggers the developer's own security awareness).

### Auth-resolution precedence (updated)

The full order for **`api_key`**:

1. `.dailybot/env.json` active profile's `api_key` (walk-up from cwd) — new in 3.7.0
2. `DAILYBOT_API_KEY` env var
3. `config.json::api_key` (from `dailybot config key=...`)

Two refinements to keep the whole story honest:

- **Wire preference.** When the key resolves from `env.json` (layer 1), the HTTP client sends `X-API-KEY` on the **first** attempt even if a Bearer login session also exists — see "Interaction with the login Bearer token" below. Keys from layers 2–3 keep the long-standing Bearer-first order (backward compatible).
- **`agent *` commands.** A keyed `agents.json` profile selected with an explicit `--profile` flag supplies its own key and beats `env.json` (a CLI flag is the highest layer). The same profile resolved implicitly — via `profile.json::profile` or as the `agents.json` default — **yields to `env.json`**. `dailybot agent profiles --resolve` always shows exactly what will be sent.

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

> `app_url` is **informational**: it tells you (via `dailybot env show` and `agent profiles --resolve`) which webapp the current context points at. Links printed after actions (e.g. the `View:` URL of a submitted report) come from the **server response**, so they already match the server the request went to.

When `env.json::disabled` is `true` or `active` is empty/null/unknown, the file is transparently skipped and every resolver behaves as if the file didn't exist.

### Interaction with `profile.json`

The two files are **orthogonal** and both can be present:

| File | Committed | Contains | Rules |
|---|---|---|---|
| `.dailybot/profile.json` | Yes (tracked) | `name`, `default_metadata`, `report`, `vars` — **identity** | `key` field fatally rejected. |
| `.dailybot/env.json` | **No** (gitignored) | `api_key`, `api_url`, `app_url` per profile — **auth context** | `agent_name` / `default_metadata` NOT allowed (belongs in `profile.json`). Fatally rejected when tracked. |

`profile.json` still governs how reports are *signed* even when `env.json` provides the credentials to send them.

### Interaction with the login Bearer token

When an `env.json` active profile provides an `api_key` **and** a login Bearer token also exists on disk, the CLI's `DailyBotClient` needs to reconcile the two. It does so with a **transparent alt-credential retry** that makes both single-org and cross-org setups behave sensibly with zero user intervention.

The mechanics:

1. **The env.json key goes FIRST.** When the resolved API key comes from `.dailybot/env.json`, `_headers()` / `_agent_headers()` send `X-API-KEY` on the **first** attempt (`DailyBotClient._prefer_api_key`, auto-detected from the key's provenance via `get_api_key_source()`). This is what makes "env.json overrides the login Bearer session" literally true: the per-repo key wins even when the Bearer would have been accepted by the target server (same-server, different-org setups), and the global session token is never transmitted to whatever server the repo's env.json points at. Keys resolved from `DAILYBOT_API_KEY` / `config.json` keep the long-standing Bearer-first order — every pre-env.json flow is unchanged.
2. **On a 401 or 403 response**, the client's `_request()` / `_agent_request()` helpers automatically retry the same call **once** with the alternative credential (in either direction — a stale env.json key falls back to the Bearer, and a stale Bearer falls back to an API key). The retry is invisible to the caller — it happens inside the HTTP layer, not in each command.
3. **`status --auth` inspects `_agent_auth_mode`** after the call returns to report which credential *actually* succeeded on the wire, so the UX is honest about the effective auth path.

Why retry on 403 too? Django/DRF frequently returns 403 instead of 401 for rejected credentials (see [DRF docs — "If not authenticated, 403"](https://www.django-rest-framework.org/api-guide/authentication/#unauthorized-and-forbidden-responses)). Retrying on only 401 misses this common local-Django case entirely.

Concrete example. You are logged in with `dailybot login` against production, and you `cd` into a repo that has `.dailybot/env.json` with an active `local-admin` profile pointing at `http://localhost:8000`:

```
                            + client.auth_status()
                            |
                            | Attempt 1: X-API-KEY <env.json local-admin>  -> http://localhost:8000
                            |            200 OK   (prod Bearer never leaves the machine)
                            |
                            + returns { user, organization, ... } from LOCAL org
```

`dailybot status --auth` then prints `Authenticated via API key` (not "login (OTP)") because that is what is on the wire. `dailybot user list`, `dailybot form list`, `dailybot kudos give`, etc. all follow the exact same path — one round-trip, correct identity, no "you must log in again" wall. If the env.json key is ever stale, the 401/403 retry silently falls back to the Bearer, and `status --auth` reports that honestly too.

One extra guardrail: **`dailybot login` warns when an active env.json profile is redirecting it.** Login persists the resolved `api_url` (and the token issued by that server) into the GLOBAL `~/.config/dailybot/credentials.json`, so logging in from inside such a repo would repoint every other repo's session. The warning names the profile and the server and suggests `dailybot env off` first; the login itself still proceeds.

For a bulletproof "different org per repo" story, prefer profiles with distinct `api_url`s (which is the whole point of `env.json`). `dailybot logout` remains available if a developer wants to eliminate the Bearer entirely.

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
