# AI Agent Onboarding

This is the first-session checklist for any AI agent (Claude Code, Cursor, Codex, Gemini, Copilot, …) starting work on the Dailybot CLI.

> If you only read one document, read [`../AGENTS.md`](../AGENTS.md). This file is the next layer down.

## Step 1 — Confirm Your Environment

This project does **not** require Docker. It is a plain Python package.

```bash
python3 --version           # >= 3.9 expected
which python3               # not the system Python? then a venv is active — good
pip --version               # match the venv
git rev-parse --abbrev-ref HEAD   # which branch
git status -s               # any uncommitted noise?
```

If `python3 --version` reports `< 3.9`, ask the user how they'd like to proceed (`pyenv install 3.11`, `uv venv --python 3.11`, etc.) before doing anything else.

## Step 2 — Install the Package

```bash
pip install -e .
```

Confirm:

```bash
dailybot --version
dailybot --help
```

Both should run without error. If `dailybot` isn't on PATH, the user is probably outside their venv — surface that before continuing.

## Step 3 — Read the Source

The codebase is small (~6 files in `dailybot_cli/` excluding `commands/`, plus 7 command modules). Read them in this order:

1. `dailybot_cli/main.py` — entry point, root group
2. `dailybot_cli/api_client.py` — every HTTP endpoint the CLI hits
3. `dailybot_cli/config.py` — credential and profile management
4. `dailybot_cli/display.py` — every output helper
5. `dailybot_cli/commands/*.py` — one file per command/group; agent.py is the largest

Then skim `tests/` to understand the mocking patterns.

## Step 4 — Read the Docs

| Read | Why |
|------|-----|
| [`../AGENTS.md`](../AGENTS.md) | Mandatory rules; do not violate |
| [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md) | What the CLI does and who uses it |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | How the modules fit together |
| [`API_REFERENCE.md`](API_REFERENCE.md) | The CLI ↔ API contract |
| [`STANDARDS.md`](STANDARDS.md) | Coding standards reference |
| [`TESTING_GUIDE.md`](TESTING_GUIDE.md) | How to write tests |

For the task-specific deep dive, also read whichever of these is most relevant:

- Adding a command? → [`CLI_COMMAND_BEST_PRACTICES.md`](CLI_COMMAND_BEST_PRACTICES.md), [`DISPLAY_OUTPUT_BEST_PRACTICES.md`](DISPLAY_OUTPUT_BEST_PRACTICES.md)
- Touching auth/config? → [`CONFIGURATION.md`](CONFIGURATION.md), [`SECURITY.md`](SECURITY.md)
- Cutting a release? → [`RELEASE_AND_DISTRIBUTION.md`](RELEASE_AND_DISTRIBUTION.md)
- Stuck? → [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)

## Step 5 — Run the Tests

```bash
pytest -x
```

All tests must pass before you make any change. If they don't on a clean checkout, the user has uncommitted changes — investigate before assuming the project is broken.

## Step 6 — Plan Your Change

For any non-trivial change:

1. Identify which files you'll touch (use the [Where to Add Things](ARCHITECTURE.md#where-to-add-things) table).
2. Write or update tests **first** (TDD — see [TESTING_GUIDE.md](TESTING_GUIDE.md)).
3. Confirm the failing test fails for the right reason.
4. Make the minimal change.
5. Re-run targeted tests, then the full suite.
6. Lint / type-check.
7. Commit with a conventional message ([STANDARDS.md](STANDARDS.md#commit-messages)).

## Step 7 — Mandatory Rules Checklist (Quick Recap)

Before submitting any change:

- [ ] All code in English with type hints (modern syntax: `list[X]`, `Optional[X]`)
- [ ] Tests use `*_test.py` naming and pass
- [ ] No real HTTP calls in tests (mock `httpx`)
- [ ] All `client.*` calls wrapped in `try/except APIError`
- [ ] All user-facing output goes through `display.py` (errors → stderr)
- [ ] No raw `print(...)`, no `sys.exit()`, no `import requests`
- [ ] New files in `~/.config/dailybot/` are `chmod 0o600`
- [ ] Secrets are masked in any output (`key[:4] + "****"`)
- [ ] User-facing strings use **"Dailybot"** (lowercase 'b')
- [ ] Version not hardcoded anywhere; only `pyproject.toml::project.version`
- [ ] If a new dep was added: Homebrew formula in `release.yml` updated

## Step 8 — Report Progress

After committing significant work, report through the CLI itself:

```bash
dailybot agent update --name "Claude Code" \
  "Added <thing> — <why it matters in one sentence>." \
  --metadata '{"model":"claude-opus-4-7","repo":"cli"}'
```

For DWP-style multi-task work, use `--milestone` + `--json-data`. See [`.claude/skills/dailybot-progress-report/SKILL.md`](../.claude/skills/dailybot-progress-report/SKILL.md) for the full philosophy.

## Repo Quick Facts

- **Plain Python project** — no Docker, no DB, no background workers.
- **Test files end in `*_test.py`** (enforced by `pytest.ini`).
- **Type hints are mandatory** by convention (see [STANDARDS.md](STANDARDS.md)).
- **English-only** for code, comments, docs, and commits.
- **All user-facing output through `display.py`** — never raw `print(...)`.
- **All HTTP through `DailyBotClient`** — never inline `httpx` in commands.

## Asking the User

If you're unsure about:

- Whether to bump the version (probably no — leave it for the release manager)
- Whether to push to a new branch or commit to main (depends on the user's workflow)
- Whether to publish to PyPI (only with explicit approval — it's irreversible)
- Whether to update `install.sh` (CDN deploy is out-of-band — confirm)

**Ask, don't assume.** Releases are particularly unforgiving (see [RELEASE_AND_DISTRIBUTION.md](RELEASE_AND_DISTRIBUTION.md)).
