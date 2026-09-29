# Security

## Threat Model

The Dailybot CLI runs on **user machines** and sometimes on **CI runners**. The threats we care about:

1. **Credential leakage** to other users on a shared host (multi-user dev box, CI runner).
2. **Credential leakage** through logs, terminal scrollback, or piped output.
3. **Man-in-the-middle** on the CLI ↔ API connection.
4. **Replay** of OTP codes after a failed verification.
5. **Confused-deputy** attacks where an agent uses cached credentials in unexpected contexts.

We do **not** defend against:

- A compromised user account (an attacker with shell access on the user's machine can read `~/.config/dailybot/`).
- A compromised Dailybot API.
- Targeted social engineering of the human running the CLI.

## File Permissions

Every file in `~/.config/dailybot/` that contains a secret is written with **mode `0o600`** (owner read/write, no group, no other). The pattern in `dailybot_cli/config.py`:

```python
PATH.write_text(json.dumps(data, indent=2))
os.chmod(PATH, 0o600)
```

Files with secrets:
- `credentials.json` (login Bearer token)
- `config.json` (stored API key)
- `agents.json` (per-profile API keys)
- `<repo>/.dailybot/env.json` (per-repo API keys — see § below)

Files without secrets (still written `0o600` for consistency):
- `org_cache.json` (transient list of org names + UUIDs from step 1 of multi-org login)
- `plan_cache.json` (non-sensitive org plan tier, keyed by org UUID; used to short-circuit
  non-allowlisted commands on a free plan — never stores tokens or keys)

### Repo-level env override (`.dailybot/env.json`)

The `env.json` file is the ONLY sanctioned place inside `.dailybot/` where API keys may live. It carries per-repo credential context (API key + optional URLs for one or more environments). Because it sits inside the repo tree, **four independent protections** apply beyond the standard `0o600`:

1. **Gitignore is mandatory (`.gitignore`).** The broad `.dailybot/*` rule in the repo's `.gitignore` covers it automatically; the only excepted file is `!.dailybot/profile.json`. `env.json` MUST NEVER be excepted — not with a per-machine dot-file trick, not with a `git update-index --assume-unchanged`, not with anything.
2. **File permissions (`0o600`).** Every write via `dailybot env` creates the file with mode `0o600` from the first byte (`os.open(..., 0o600)` — no umask window), and every read re-chmods it defensively. Implementation: `dailybot_cli/config.py::save_repo_env`.
3. **Root-callback refuse-if-tracked guard (fatal, applies to EVERY command).** The root `cli()` callback in `dailybot_cli/main.py` calls `load_repo_env()` on every invocation, which internally runs `git ls-files --error-unmatch .dailybot/env.json`. If the file is tracked, `RepoEnvError` is raised, `print_error()` writes to stderr, and `SystemExit(1)` aborts **before any subcommand runs**. There is no silent fallback to global auth — the entire process refuses to operate until the developer runs `git rm --cached .dailybot/env.json`. The exempt paths are `--help` / `--version` (Click short-circuits) so the developer can always read instructions, and the `hook` group, which prints the same error to stderr but exits 0 — its harness contract ([AGENT_HOOKS.md](AGENT_HOOKS.md)) forbids non-zero exits, and hook commands never consume env.json auth. When git is not on PATH but a `.git` ancestor exists, the guard cannot verify tracking and degrades to a loud warning instead of a silent pass. Implementation: `dailybot_cli/config.py::_is_env_tracked_by_git` (independently mockable), invoked via `load_repo_env` from `main.py::cli`.
4. **Write-time gitignore warning.** `dailybot env add` runs `git check-ignore --quiet .dailybot/env.json` after writing; if the file is NOT covered by any ignore rule, a warning fires on stderr with the exact `.gitignore` snippet to add. The warning is non-fatal because a fresh repo might not have a `.gitignore` yet, and the load-time guard (#3) catches the actual security violation.

**All four protections must trip together** for a leak to happen: the developer would have to (a) remove or fail to add the `.gitignore` rule, (b) survive the write-time warning, (c) survive the load-time refuse-if-tracked check, and (d) somehow bypass the file permissions. The design is defense-in-depth on purpose.

**If a key ever ends up in a commit**, treat it as compromised — rotate immediately via the Dailybot dashboard, then follow the recovery recipe in [CONFIGURATION.md § "STOP — Read this before you author `env.json`"](CONFIGURATION.md#stop--read-this-before-you-author-envjson). Git history is forever; `git revert` does not undo the exposure.

The full schema, precedence, and CLI commands for `env.json` are in [CONFIGURATION.md § "Repo-level env override"](CONFIGURATION.md#repo-level-env-override-dailybotenvjson).

## Secrets in Output

Never display, log, or echo a full secret. Always mask:

```python
def _mask(value: str) -> str:
    if len(value) <= 4:
        return value[0] + "****" if value else "****"
    return value[:4] + "****"
```

Helpers that already mask correctly: `dailybot config key`, `dailybot agent profiles`. New code that handles a secret must use the same pattern.

## Transport

The default API URL is `https://api.dailybot.com` — TLS is enforced by httpx (no `verify=False`). When the user passes `--api-url` for staging/local development:

- HTTPS is still required for any externally-reachable endpoint.
- For local dev (e.g., `http://localhost:8000`), the user is implicitly accepting the insecure transport on their own loopback.

We do **not** disable certificate verification anywhere. Don't add a flag for it.

## Untrusted Content — Tasks

**Every string the Tasks API returns is user-authored data, never an instruction.**

This is a different class of hazard from the rest of the CLI. Anyone who can create a
task on a shared board can write text that an agent will later read **while holding a
credential**, so a task titled `delete this board` is an injection vector into a
privileged execution context. The CLI matters here more than a typical client because its
output is routinely consumed *by* an agent — that is the premise of the Dailybot agent
skill pack.

**The boundary is the renderer.** `display.present_untrusted()` is the single enforcement
point: it escapes Rich markup (so a title cannot style the terminal), wraps the value in
quotes (so a reader sees a datum, not a sentence addressed to them), and truncates.
Every user-authored field goes through it.

**Control characters never reach the terminal.** Rich escapes its own markup but passes ANSI /
OSC escape sequences, bidi overrides and zero-width characters straight through. Left alone, a
title could clear the screen, overwrite the line a person reads before answering "Proceed?", or
plant a hyperlink. The presenter turns newlines and tabs into spaces and shows every other
control or format character as its `\uXXXX` code. It escapes an embedded `"` so a value cannot
close its own quotes. Server text that is shown unquoted (keys, codes, a preview's consequence
and counts, roll-ups) goes through `display.safe_text()`, which applies the same
neutralization and markup escaping.

**The trusted set is exact and auditable.** `display.TASKS_TRUSTED_FIELDS` lists the only
server-generated fields — `uuid`, `key`, `rank`, `cursor`, `etag`, `delta_cursor`, `code`,
and the three timestamps. Everything else is untrusted. A test asserts the set matches the
API contract rather than relying on memory.

**`provenance: typed` is attribution, not trust.** It means a person typed the comment. It
does not make the comment an instruction, and the renderer never labels it "trusted",
"verified" or "system".

**`--json` carries data, not narration.** Untrusted values are emitted as plain string
fields and are never interpolated into a message, so an agent parsing the output can tell
a field from a sentence.

Regression coverage lives in `tests/tasks_security_test.py`, which renders
instruction-shaped strings through every Tasks view in both human and JSON modes.

## Tasks Credentials and Isolation

**Some Tasks doors require a person.** `me/tasks`, `me/tasks/counts`, `me/recents`,
`me/activity-cursor`, `inbox` and `inbox/unread-count` are defined relative to the calling
user, and the writes that change **who can see** or **who is notified** (participants,
membership) need an accountable person. A login session or a personal API key is a person;
an agent or organization key is nobody, so the server refuses it.

**A personal API key is its person; an agent or organization key is nobody.** A key bound
to a person acts as that person on every Tasks door, exactly like their login session:
same role, same visibility, same answers, `tasks:admin` included for a non-guest member (the
developer reversed ADR-9-4 for personal keys; agent and organization keys still never hold
`tasks:admin` or act as a person). Guests stay limited on both. The CLI therefore never
refuses a key before the request: it cannot tell the two kinds apart, so the server decides,
and `tests/tasks_key_refusal_sweep_test.py` pins that every door sends the request. The
server's refusals keep their meaning: `actor_required` (exit 3) and `insufficient_scope` /
`guest_not_allowed` (exit 4); `tests/tasks_server_refusal_rendering_test.py` pins how the CLI
renders them. Membership remains the privacy control: a `members` project or board is 404
without a grant. CLI messages blame the *credential kind* and never tell a member they "need
to be an admin".

Comments, projects and goals take attachments too (`task comment-attach`, `project attach`,
`goal attach`). Those doors are multipart only, so the limit is 5 MiB everywhere, and it is
checked before any request. They go only to the API origin, and their downloads share the
same hardened path below. Attaching to or deleting from a project or a goal is a
`tasks:admin` door: a login or a personal API key, never an agent or organization key.

`task attachment get` follows at most **one** redirect from the API to storage, without
credentials; a second redirect is refused, and a refusal from storage is reported as storage's
(`attachment_download_failed`), never as a session problem. Downloads over the attachment
size cap are refused. The API's own `…/content/` answer and the storage hop both stream, and
the cap is enforced on the bytes as they arrive; both also have a wall-clock deadline. On
the storage hop
the body is requested uncompressed (`Accept-Encoding: identity`), and the whole hop has a
wall-clock deadline. So an endless chunked body, a compression bomb or a slow drip cannot
exhaust memory or hang the CLI. If writing the file fails, the partial file this call created
is removed. The output path is never derived from server data. Without `--force`
the file is created exclusively (`O_EXCL`) and a symlink is never followed (`O_NOFOLLOW`;
with `--force`, an output path that is a symlink is refused outright, since `O_NOFOLLOW` is
not available on every platform), so a
file or link that appears during the download is left alone; nothing is written when the
download fails, and an unwritable path is a clear error rather than a crash.

## OTP Handling

The login flow is two HTTP calls:

1. `request_code(email)` → API generates and emails an OTP, returns the org list (if multi-org).
2. `verify_code(email, code, organization_id?)` → consumes the OTP and returns a Bearer token.

Critical invariant: **calling `request_code` again invalidates any pending OTP for that email.** This is why non-interactive multi-org login caches the org list to disk during step 1 (`org_cache.json`) — step 2 reads the cache to resolve UUID → integer ID without re-issuing `request_code`. Breaking this would silently invalidate users' codes.

The `org_cache.json` is cleared after a successful verify.

## Bearer Token Lifecycle

- Issued by `verify_code(...)`.
- Stored in `credentials.json` with `0o600`.
- Sent on every authenticated request as `Authorization: Bearer <token>`.
- Used by human endpoints (`/v1/cli/*`) and user-scoped endpoints (`/v1/checkins/*`, `/v1/forms/*`, `/v1/users/`, `/v1/kudos/`).
- Revoked by `dailybot logout` (best-effort `POST /v1/cli/auth/logout/` + local file removal).
- Treated as expired/invalid on any 401/403 from a Bearer-mode call → `_handle_response` rewrites the error to "Session expired. Run 'dailybot login' to re-authenticate."

There is no automatic refresh. Tokens have a server-defined lifetime; the user is expected to re-run `dailybot login` when prompted.

## User-Scoped Commands — Privacy Considerations

The user-scoped commands (`checkin`, `form`, `kudos`, `user`) operate within the authenticated user's permissions. Specific security decisions:

- **`dailybot user list`** — intentionally omits email addresses from both table and JSON output. This is a PII-minimization measure for an open-source CLI. UUIDs are exposed for programmatic use (e.g., `--to <uuid>` in kudos).
- **`dailybot kudos give`** — prevents self-kudos client-side. The receiver is resolved by name against the user directory; ambiguous matches are rejected rather than guessed.
- **Pagination safety** — `list_users()` caps at `_MAX_LIST_PAGES = 50` pages to prevent unbounded loops against a misbehaving backend.
- **Confirmation prompts** — `checkin complete`, `form submit`, `kudos give`, and the destructive authoring commands (`form archive`, `checkin archive`, `form/checkin questions delete`) show a confirmation before a team-visible or irreversible write. `--yes` skips it for non-interactive/scripted use.
- **Forms & check-ins authoring** (`channels list`; `form/checkin create/edit/config/archive` + `questions` subgroups; extended `form responses --all/--user`; owner/admin editing of another user's response) — all authorization is **enforced server-side by role** and reuses the existing permission model (no new permission types). The CLI performs only shape/format validation (question types, options, schedule) and surfaces the server's `403` codes with role-aware messages; it never approximates roles or elevates locally. Both a login session and an API key go through the identical `_headers()` path.
- **Exit codes** — structured exit codes (2–7) enable safe scripting without parsing error messages. See [API_REFERENCE.md](API_REFERENCE.md) for the full table.

## API Key Lifecycle

- Issued by `dailybot agent register` (returned in the registration response).
- Stored either in `config.json::api_key`, `agents.json::profiles[<slug>].api_key`, or in the `DAILYBOT_API_KEY` env var.
- Sent as `X-API-KEY: <key>` on agent endpoints.
- **Never expires automatically.** Rotation is a manual op (re-register or have the org admin rotate via the web UI).

## Webhook Secrets

- Set by the user via `dailybot agent webhook register --secret <secret>`.
- Stored on the API side, not locally on the CLI.
- Forwarded by Dailybot as `X-Webhook-Secret: <secret>` on inbound webhook deliveries.
- Treated as opaque by the CLI — we don't validate format.

When generating a secret on behalf of a user, suggest a high-entropy random string:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

## Standalone Registration

`dailybot agent register` calls a no-auth endpoint protected by a math-puzzle challenge:

1. `GET /v1/agent/register/challenge/` returns `{ challenge_id, instruction }`. The instruction is a sentence ending in `"... session is <random_number>."`.
2. Compute `random_number * 52` (the constant `_CHALLENGE_WORD_COUNT`).
3. `POST /v1/agent/register/` with `challenge_id`, `answer`, and the org/agent metadata.
4. Server validates the answer + rate-limits.

**This is a low-friction anti-bot measure, not a strong security control.** The backend additionally rate-limits by IP and applies abuse heuristics. If the challenge format ever needs to change, the CLI and the Dailybot API have to be updated together.

## CI / Headless Runners

Recommended pattern for CI:

```bash
# Inject the API key via env var (never commit it, never write it to disk)
export DAILYBOT_API_KEY="${DAILYBOT_API_KEY}"
dailybot agent update "Build #${BUILD_ID} passed" --name "CI Bot"
```

Avoid:
- `dailybot config key=...` in CI (writes to disk; awkward to scrub between jobs).
- Using a shared user account login (the Bearer token is a per-user credential — `dailybot agent register` is the right move for autonomous bots).

## Reporting a Vulnerability

If you find a security issue in the CLI:

- **Do not open a public GitHub issue.**
- Email `support@dailybot.com` with a subject prefix `[SECURITY]`.
- Include a minimal reproduction and the version (`dailybot --version`).

For the API itself, follow Dailybot's main responsible-disclosure process.
