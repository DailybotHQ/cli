# Repository Standards

Repository-wide conventions. The mandatory subset lives in [`../AGENTS.md`](../AGENTS.md); this file is the deeper reference.

## Language

All code, comments, docstrings, log messages, error messages, commit messages, and documentation MUST be in English. The CLI is a public open-source product distributed worldwide.

## File & Module Naming

| Kind | Convention | Example |
|------|-----------|---------|
| Module | `snake_case.py` | `api_client.py`, `dailybot_cli/commands/agent.py` |
| Test | `<module>_test.py` (mirrors source) | `tests/api_client_test.py` |
| Class | `PascalCase` | `DailyBotClient`, `APIError` |
| Function/variable | `snake_case` | `submit_update`, `get_token` |
| Constant | `SCREAMING_SNAKE_CASE` | `DEFAULT_API_URL`, `_CHALLENGE_WORD_COUNT` |
| Internal/private | leading `_` | `_resolve_agent_context`, `_handle_response` |

## Import Order (Mandatory)

```python
# 1. Python stdlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

# 2. Third-party (alphabetical)
import click
import httpx
import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# 3. Internal project (alphabetical)
from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.config import get_token, load_credentials, save_credentials
from dailybot_cli.display import console, print_error, print_info, print_success
```

Within each tier, imports are alphabetical. Group `from X import a, b, c` after plain `import X` lines within the same tier.

## Type Hints (Mandatory)

```python
def submit_report(
    content: str,
    structured: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"content": content}
    if structured:
        payload["structured"] = structured
    if metadata:
        payload["metadata"] = metadata
    return payload
```

Use modern syntax: `list[X]`, `dict[K, V]`, `tuple[X, ...]`, `Optional[X]`. Annotate parameters, return type, and meaningful local variables. The codebase favors explicit annotations even where mypy could infer.

## Module-Level Constants

Prefer named constants over magic numbers and repeated strings:

```python
DEFAULT_TIMEOUT_SECS: float = 30.0
LONG_TIMEOUT_SECS: float = 120.0          # AI-processing endpoints
DEFAULT_API_URL: str = "https://api.dailybot.com"
_CHALLENGE_WORD_COUNT: int = 52
```

Use a leading underscore for module-private constants when the value is only meaningful inside the module.

## Docstrings

- One-line summary for trivial helpers.
- Multi-line docstrings for Click commands — Click renders them in `--help`, so keep them user-facing.
- Use `\b` blocks inside Click docstrings to preserve example formatting:

```python
@click.command()
def update(...) -> None:
    """Submit a check-in update.

    \b
      dailybot update "I finished the auth module."
      dailybot update --done "Auth" --doing "Tests"
    """
```

- For internal helpers, document **why** the function exists when the name doesn't say it (e.g., `_solve_challenge`, `_resolve_agent_context`). Do not document what the code already says.

## Comments

Default to writing **no comments**. Only add one when the WHY is non-obvious: a hidden constraint, a workaround, a subtle invariant. Examples in the existing codebase that are kept on purpose:

- The `# noqa: F401 — enables arrow-key editing in input()` next to `import readline` in `interactive.py`.
- The `# Auto-select the only org and retry` comment in `auth.py::_verify_and_save`.
- The `# Profile without key — fall through to Bearer token` in `agent.py::_resolve_agent_context`.

Comments that just narrate ("loop over messages") are noise — delete on sight.

## Error Handling

```python
try:
    with console.status("Doing the thing..."):
        result: dict[str, Any] = client.do_thing(...)
except APIError as e:
    if e.status_code in (401, 403):
        print_error("Session expired. Please log in again: dailybot login")
    elif e.status_code == 429:
        print_error("Rate limited. Try again in a few minutes.")
    else:
        print_error(e.detail)
    raise SystemExit(1)
```

- Always wrap `client.*` calls in `try/except APIError` (or its child).
- Special-case 401/403 → "session expired / re-authenticate".
- Special-case 429 → "rate limited / wait".
- 4xx with a message tied to a specific feature (e.g., "ai processing failed") → rewrite to a useful user message.
- Never let raw `httpx.HTTPError` reach the user — that's a bug; either translate it in `_handle_response` or catch it in the command.

## Click Conventions

| Convention | Example |
|------------|---------|
| Short flags must be consistent across commands | `-n` for name, `-p` for profile, `-d` for metadata, `-j` for json-data, `-m` for milestone, `-c` for co-authors |
| Multi-value flags arrive as `tuple[str, ...]` | `co_authors: tuple[str, ...]` |
| Flags that toggle behavior use `is_flag=True` and a default | `is_flag=True, default=False` |
| Group-level shared state goes in `ctx.obj` | `ctx.obj["profile"] = profile` |
| Always include `\b` blocks in Click docstrings | (see above) |
| Use `SystemExit(1)` to exit with error | Never `sys.exit(1)` from inside Click callbacks |

## Output Conventions

- All user-facing output goes through `dailybot_cli/display.py`.
- Errors → **stderr** (`error_console`).
- Everything else → **stdout** (`console`).
- Use `console.status("...")` around any HTTP call.
- Mask secrets in any output (first 4 chars + `****`).
- Rich markup characters (`[`, `]`) in user content must be escaped with `\\[`.

See [DISPLAY_OUTPUT_BEST_PRACTICES.md](DISPLAY_OUTPUT_BEST_PRACTICES.md) for the full reference.

## Brand Name Spelling

In all **user-facing strings** (docstrings, help text, success/error/info messages, README copy), use **"Dailybot"** with a lowercase `b`. The legacy "DailyBot" appears only in:

- Python identifiers (`DailyBotClient`, `DailyBotHQ` GitHub org)
- HTTP headers and protocol fields (none currently)
- The `install.sh` legacy "DailyBot CLI installer" comment (will be migrated on the next pass)

When in doubt: if the string is shown to a user, use "Dailybot".

## Commit Messages

`<type>(<scope>): <short description>` followed by optional body sections:

- **Types**: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `build`, `ci`
- **Scopes**: `auth`, `agent`, `update`, `status`, `config`, `interactive`, `display`, `client`, `cli`, `release`, `tests`, `docs`

```
feat(agent): add --co-authors flag to agent update

## Summary
Allow agents to credit collaborators on a single report.

## Change Log
- Added repeatable --co-authors option (also accepts comma-separated)
- Forwarded co_authors list to /v1/agent-reports/
- Updated print_success to render co-author names

## Risks
- None for backwards compat — flag is optional
```

A short single-line message is acceptable for trivial commits (`Version bump`, `fix typo in --help`).

## File Permissions

Any file created in `~/.config/dailybot/` that contains a secret MUST be set to `0o600`:

```python
PATH.write_text(json.dumps(data, indent=2))
os.chmod(PATH, 0o600)
```

This includes `credentials.json`, `config.json`, and `agents.json`. `org_cache.json` is non-secret and may skip the chmod.

## Adding a New Dependency

1. Add it to `pyproject.toml::project.dependencies` (pinned with `>=`).
2. Update the **Homebrew formula** in `.github/workflows/release.yml` — every transitive Python dependency must be listed there as a `resource` block with its sdist URL and sha256.
3. Mention the new dependency in the relevant docs (`ARCHITECTURE.md` / `RELEASE_AND_DISTRIBUTION.md`).
4. Run `python -m build` and inspect the resulting wheel to make sure imports still resolve.

> Adding a dep with native code (compiled extensions) makes the Linux binary build harder — confirm that PyInstaller still works in the glibc 2.31 container before merging.
