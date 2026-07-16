# Review overrides for Dailybot CLI

This repo is the **Dailybot CLI** (`dailybot-cli`) — a public, open-source
Python Click package that talks to the Dailybot HTTP API. Agents and humans
edit it constantly; every finding here is high-stakes for credential hygiene,
auth-resolution order, and user-facing output contracts.

The load-bearing rules live in [`AGENTS.md`](../AGENTS.md) and
[`docs/SECURITY.md`](../docs/SECURITY.md); this file overrides the base
prompt for the patterns most likely to slip a review.

## Severity overrides for this codebase

- **Always `critical`:** writing any secret-bearing file under
  `~/.config/dailybot/` (or `.dailybot/env.json`) without mode `0o600`
  (`os.open(..., 0o600)` / `os.chmod(..., 0o600)`). See AGENTS.md Rule 11 /
  `docs/SECURITY.md`.
- **Always `critical`:** logging, printing, or echoing a full API key,
  Bearer token, OTP, or webhook secret. Mask with first-4 + `****` (or the
  existing `_mask` helper).
- **Always `critical`:** committing or un-ignoring `.dailybot/env.json`,
  real credentials, real org/user UUIDs, or internal hostnames into tracked
  files. This repo is PUBLIC — AGENTS.md Rule 11.a.
- **Always `critical`:** breaking the documented auth resolution order in
  `_resolve_agent_context` / `get_api_key` / `DailyBotClient._agent_headers`
  (AGENTS.md Rule 14) without an explicit migration + docs update.
- **Always `critical`:** removing or weakening the root `cli()` tracked-
  `env.json` guard in `dailybot_cli/main.py` (hard abort before
  subcommands; hook-group carve-out must keep exit 0).
- **Always `critical`:** hitting the real Dailybot API from tests, or
  adding a network call that is not mocked at
  `dailybot_cli.api_client.httpx.*`.
- **Always `critical`:** piping a remote installer into a shell, or
  recommending `curl | sh` / equivalent in docs or install paths that this
  PR introduces.

- **Always `warning`:** new Python without type hints (parameters, return
  types, meaningful locals) — modern syntax only (`list[str]`, `X | None`).
- **Always `warning`:** new test file named `test_*.py` instead of
  `*_test.py` (enforced by `pytest.ini`).
- **Always `warning`:** raw `print(...)` / `click.echo(...)` for
  user-facing output outside the documented exceptions (`hook` group,
  `_print_org_list`). Must go through `dailybot_cli/display.py`; errors to
  stderr via `print_error`.
- **Always `warning`:** Click command callback embedding business logic,
  JSON shaping, or Rich rendering — keep callbacks thin
  (parse → resolve → client → display).
- **Always `warning`:** `except APIError` missing, or error handling that
  branches on human `detail` prose instead of the machine-readable `code`
  field (`ERROR_CODE_MESSAGES`).
- **Always `warning`:** hardcoded timeouts, limits, or magic strings that
  belong in module-level constants.
- **Always `warning`:** new user-facing string that spells the product
  "DailyBot" (capital B). Identifiers like `DailyBotClient` are OK.
- **Always `warning`:** new Python dependency without a matching Homebrew
  `resource` block in `.github/workflows/release.yml`.
- **Always `warning`:** changing schemas of `credentials.json` /
  `config.json` / `agents.json` / `org_cache.json` by renaming/removing
  keys without a migration path (AGENTS.md Rule 16).

- **Always `info` (do not block):** style already covered by `ruff` /
  formatter; docstring polish; comment wording; import-order nits that
  ruff would catch.

## Don't comment on

- Vendored skill trees under `.agents/skills/deepworkplan/`,
  `.agents/skills/dailybot/`, and `.agents/skills/ai-diff-reviewer/`
  unless the PR deliberately edits them (dogfood / sync PRs). Prefer
  reviewing the sync intent, not upstream skill internals.
- Pure `skills-lock.json` hash updates that accompany a deliberate skill
  bump — note the version change once; do not nit the hash.
- Auto-generated `CHANGELOG.md` / `pyproject.toml` version bumps from
  `auto-release.yml`.
- **Accepted, documented design decisions** — do not re-flag these on
  every round:
  - `pr-review.yml` deliberately omits the `synchronize` trigger (cost
    control). The stale-green-gate trade-off is documented in the
    workflow header, the trigger comment, and
    `docs/PR_REVIEW_WORKFLOW.md` § "Re-running the review after a fix
    push". Only comment if a change makes the documentation and the
    behavior disagree.
  - A skipped `AI review gate` counting as passing for external and
    fork PRs — same doc, § "Fork and external-contributor PRs skip the
    gate".

## Reviewer style additions

- Cite the AGENTS.md rule number (or `docs/SECURITY.md` section) in the
  first line of a finding when one applies.
- Prefer concrete fix shapes that match existing helpers
  (`print_error` + `raise SystemExit(1)`, `console.status`, `_mask`,
  `exit_for_api_error`) over inventing new patterns.
- When flagging auth/credential changes, name which resolution layer moved
  (1–7) so the author can verify the order is preserved.
