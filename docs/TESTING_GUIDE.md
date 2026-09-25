# Testing Guide

## Conventions

- **File naming**: `*_test.py` (enforced by `pytest.ini::python_files = *_test.py`). NEVER `test_*.py`.
- **Location**: `tests/` at the repo root.
- **Test framework**: `pytest`. No `unittest.TestCase` subclassing — use plain functions or grouping classes (e.g., `class TestVersionAndHelp:`).
- **Mocking**: `unittest.mock.MagicMock` and `unittest.mock.patch`.
- **CLI invocation**: `click.testing.CliRunner`.

## Running Tests

```bash
pytest                                   # full suite  (full)
pytest -x                                # stop on first failure
pytest -v                                # verbose
pytest -k <keyword>                      # filter by name  (scoped)
pytest tests/api_client_test.py          # one file  (scoped)
pytest tests/api_client_test.py::TestDailyBotClientAuth::test_request_code   # one test  (scoped)
pytest --tb=short                        # shorter tracebacks
pytest -s                                # don't capture stdout (debugging)
```

Run from the repo root; there is a single `tests/` package (no workspace/monorepo boundaries to cross).

## Scoped Validation & Change-Impact Mapping

**Scoped invocation — verified.** `pytest <path>` selects by file or directory; `pytest -k <keyword>` selects by name substring; both compose (`pytest tests/api_client_test.py -k auth`). Verified against this repo: `pytest tests/api_client_test.py -q` → 150 selected, 150 passed, exit 0 (pytest 9.0.3). Lint and type-check also accept a path: `ruff check dailybot_cli/api_client.py` and `mypy dailybot_cli/api_client.py` — verified, 0 findings each (ruff 0.15.12, mypy 1.20.2). Both tools are cheap enough project-wide that scoping is a convenience, not a load-bearing optimization.

**Source-to-test mapping.** Test files mirror source modules 1:1 by name: `dailybot_cli/api_client.py` → `tests/api_client_test.py`, `dailybot_cli/config.py` → `tests/config_test.py`, `dailybot_cli/commands/<name>.py` → either its own `tests/<name>_test.py` (e.g. `hook.py` → `hook_commands_test.py`, `chat.py` → `chat_commands_test.py`) or a shared file grouping related user-scoped commands (`checkin.py`/`form.py`/`team.py`/`kudos.py`/`user.py` → `public_api_commands_test.py`; `auth.py`/`agent.py`/`interactive.py` → `commands_test.py`). When a source file has no obvious 1:1 test file, check `public_api_commands_test.py` and `commands_test.py` before assuming there is no coverage.

**Dependent-consumer policy.** There is no `--changed`/affected-tests tool wired into this repo (no monorepo task graph, no `pytest-testmon`); the mapping above **is** the affected-tests policy — run the mapped file(s) for the module(s) you touched. `api_client.py` and `display.py` are the two shared/core modules (see escalation below); every other module maps to exactly one test file.

**Known blind spots.** The scoped mapping does not catch: a change to a shared helper in `public_api_helpers.py` (`require_auth`, `resolve_user_/team_by_name_or_uuid`, `ERROR_CODE_MESSAGES`) that is consumed by several command modules but only exercised directly in `public_api_commands_test.py`; a change to `display.py` rendering helpers, which are asserted indirectly through command tests rather than a dedicated `display_test.py`; and Click option/flag wiring that only a full `--help` render or an actual `CliRunner.invoke()` catches (a scoped unit test of a helper function will not catch a broken `--flag/-f` alias).

**Escalation paths — when to widen beyond the mapped file(s):**

- A change to `dailybot_cli/api_client.py` (shared HTTP client) or `dailybot_cli/config.py` (shared credential/config I/O) — run the full suite; both are imported by nearly every command module.
- A change to `dailybot_cli/commands/public_api_helpers.py` — run `pytest tests/public_api_commands_test.py` plus the full suite before committing (it backs `checkin`, `form`, `team`, `kudos`, `user`).
- A change to `pytest.ini`, `pyproject.toml` (deps, `[tool.*]` config), or any `tests/__init__.py` — run the full suite; these affect test discovery/collection itself.
- A change to the auth resolution order (`config.py::get_api_key`/`get_active_env_profile`/`_resolve_agent_context` in `commands/agent.py`) — run the full suite; multiple test files assert this order independently (rule 14, "Auth Resolution Order," in `AGENTS.md`).

**Fallback.** When a change's blast radius is unclear, or it touches more than one of the escalation triggers above, run `pytest` (the full suite) — at 150+ tests completing in under a second, there is little cost to defaulting to it.

**Coverage posture.** Unit-first: fast, deterministic `CliRunner`/mocked-`httpx` tests are the base layer (see Coverage Expectations below) — every new `api_client.py` method gets a request-shape + response-handling test, every new Click command gets a success path and at least one error path, with **no** assertions on internal call sequences beyond what's needed to prove the request payload is correct. There is no live-API integration or e2e layer in this repo (rule 7 in `AGENTS.md`: tests MUST NEVER hit the real Dailybot API) — the mocked-`httpx` unit tests **are** the contract tests for every endpoint, which is why the request-shape assertion (not just the response handling) is mandatory for each one. No test-count or ratio target is enforced; add tests proportional to the surface a change touches.

## File Layout

```
tests/
├── __init__.py                    # empty, just makes the dir importable
├── api_client_test.py             # DailyBotClient + APIError (every HTTP method)
├── tasks_api_client_test.py       # Tasks transport: constants, query datetimes,
│                                  #   idempotency posture, dry-run, timeout tiering
├── tasks_commands_test.py         # `tasks` group: status/entitlements/search/activity/timeline
├── tasks_delta_test.py            # `tasks changes`: cursor lifecycle, window expiry
├── tasks_person_shaped_test.py    # inbox / mine / counts: person-only refusals
├── tasks_catchup_test.py         # pulse bands, inbox read/unread, activity cursor, mentionables
├── task_commands_test.py          # `task` group: reads, writes, collaboration, bulk, archive
├── tasks_owner_wire_test.py      # owner vocabulary: exact query/body on the wire (P0 guard)
├── tasks_beta_ergonomics_test.py # KEY-n args, --sort, board tasks, --updated-since, exit codes, Beta
├── tasks_contract_fixes_test.py  # commands corrected against the write contract (exact wire)
├── task_collaboration_test.py    # comments edit/delete, relations, participants, watch, mute
├── task_structure_test.py         # children, duplicate, events, activity; delegation absent
├── tasks_attachments_test.py      # attach/list/get/delete; credential + redirect boundary
├── board_commands_test.py         # `board` group: reads + container writes
├── board_admin_test.py           # `board` administration: states, members, labels, views
├── project_goal_commands_test.py  # `project` + `goal`: reads, roll-ups, updates, milestones
├── project_goal_admin_test.py    # project update/restore/members/views/milestones; goal update/link
├── tasks_display_test.py          # Tasks renderers + the untrusted-content presenter
├── tasks_error_taxonomy_test.py   # Tasks error codes and credential guidance
├── tasks_security_test.py         # injection boundary, isolation, destructive paths
├── tasks_coverage_test.py         # cross-command sweep: 19 capabilities, flag wiring,
│                                  #   idempotency table, role matrix, sequences
├── transport_errors_test.py       # transport failures -> messages, not tracebacks
├── commands_test.py               # Click commands via CliRunner (auth, agent, interactive)
├── config_test.py                 # ~/.config/dailybot/ file management
├── public_api_commands_test.py    # User-scoped commands: checkin, form (full
│                                  #   lifecycle — get/responses/update/transition/delete),
│                                  #   team (list/get), kudos (--to / --team / both), user
├── form_question_types_test.py    # Type-aware form prompt logic
├── repo_profile_test.py           # `.dailybot/profile.json` resolution
├── agent_init_test.py             # `dailybot agent init` wizard
└── uninstall_test.py              # install-method detection + remove paths
```

When adding a new module, mirror it in `tests/`. New test files **MUST** end in `_test.py`.

### User-scoped command tests

The user-scoped commands (`checkin`, `form`, `team`, `kudos`, `user`) are tested in `public_api_commands_test.py`. The pattern follows the same approach as `commands_test.py` but patches `dailybot_cli.commands.public_api_helpers.get_agent_auth` and `dailybot_cli.commands.public_api_helpers.DailyBotClient` (since the auth resolution for these commands goes through `require_auth()`, which accepts either a Bearer session or an API key). A return value of `None` from `get_agent_auth` simulates the unauthenticated case (exit code 3).

**Forms-lifecycle coverage expectations.** New `form` subcommands (`get`, `responses`, `response get`, `update`, `transition`, `delete`) must include:

1. **Happy path** — assert the client method is called with the right args, and (for mutating calls) that the workflow surface is rendered after success.
2. **Error path** for every server `code` the command can surface. At minimum:
   - `form transition` → `form_response_change_state_forbidden` (403, exit 4) **and** `final_state_locked` (403, exit 4).
   - `form delete` → `form_response_delete_forbidden` (403, exit 4).
   - `form response get` / `form update` → `form_response_not_found` (404, exit 5).
3. **JSON mode** — assert `--json` emits the `code` and `detail` fields alongside `status`, so chat-agent consumers can pattern-match without parsing prose.

**Teams + team-kudos coverage:** `team list` / `team get` exercise the new resolver; `kudos give --team` and `--to + --team` must assert that the POST payload uses `user_uuid_receivers` / `team_uuid_receivers` (the legacy `receivers` key MUST NOT appear).

### Tasks coverage expectations

New Tasks commands must include:

1. **Happy path** — assert the client method is called with the expected request shape.
2. **Error path** for every server `code` the command can surface, dispatched on `code`
   and never on the English `detail`.
3. **JSON mode** — `--json` emits the documented keys; paginated commands emit the
   `{count, next, previous, results}` envelope.
4. **Untrusted rendering** — any user-authored field is asserted to render as quoted data.
5. **Credential posture** — a person-only door is asserted to refuse an API key *before*
   the request, with exit code 3.
6. **Idempotency posture** — the header is asserted present on an accepting door and
   **absent** on an ignoring one. `tests/tasks_coverage_test.py` keeps the table-driven
   version, which is the cheapest guard against drift.
7. **Destructive posture** — the preview is asserted to happen first, `--dry-run` to mutate
   nothing, and a failed preview to abort.

`tests/tasks_coverage_test.py` is the cross-command sweep: it walks the 19 phase-1
capabilities, renders `--help` for every subcommand of every Tasks group (the flag-wiring
blind spot), and asserts no test in the suite calls `httpx` directly.

**A coupling worth knowing:** `goal create` reuses `project._require_person_for_admin`, so
`get_agent_auth` resolves in the **project** namespace. Patching `goal.get_agent_auth` does
nothing. The role-matrix table records the resolving module per row for exactly this reason.

## Mocking HTTP

The CLI **must never** hit the real Dailybot API in tests. The canonical pattern:

```python
from unittest.mock import MagicMock, patch

import httpx
import pytest

from dailybot_cli.api_client import DailyBotClient


@pytest.fixture
def client() -> DailyBotClient:
    return DailyBotClient(
        api_url="http://test-api.example.com",
        token="test-token",
        api_key="test-api-key",
    )


def test_my_endpoint(client: DailyBotClient) -> None:
    mock_response: MagicMock = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"detail": "ok"}

    with patch("httpx.post", return_value=mock_response) as mock_post:
        result: dict[str, Any] = client.my_endpoint(arg1="x")

    mock_post.assert_called_once()
    call_kwargs: dict[str, Any] = mock_post.call_args[1]
    assert call_kwargs["json"] == {"arg1": "x"}
    assert result["detail"] == "ok"
```

### Patching `httpx` from `api_client`

Patch the global `httpx.<method>` rather than a member of `DailyBotClient` — `api_client.py` imports `httpx` and calls `httpx.post(...)` directly.

```python
# ✅ CORRECT — patches the same import the code uses
with patch("httpx.post", return_value=mock_response):
    ...

# ❌ WRONG — DailyBotClient doesn't have a self.post attribute
with patch.object(client, "post", return_value=mock_response):
    ...
```

If you'd prefer to scope the patch to `api_client`'s namespace, use `dailybot_cli.api_client.httpx.post`.

## Testing Click Commands

```python
import pytest
from click.testing import CliRunner
from unittest.mock import MagicMock, patch

from dailybot_cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@patch("dailybot_cli.commands.update.get_token")
@patch("dailybot_cli.commands.update.DailyBotClient")
def test_update_with_message(
    mock_client_cls: MagicMock,
    mock_get_token: MagicMock,
    runner: CliRunner,
) -> None:
    mock_get_token.return_value = "tok"
    mock_client: MagicMock = mock_client_cls.return_value
    mock_client.submit_update.return_value = {
        "followups_count": 1,
        "attached_followups": [{"followup_name": "Standup", "action": "created"}],
    }

    result = runner.invoke(cli, ["update", "Did stuff today"])

    assert result.exit_code == 0
    mock_client.submit_update.assert_called_once_with(
        message="Did stuff today",
        done=None,
        doing=None,
        blocked=None,
    )
```

### Patching at the right import site

Patch where the symbol is **used**, not where it's defined:

```python
# ✅ CORRECT — update.py does `from dailybot_cli.config import get_token`
@patch("dailybot_cli.commands.update.get_token")

# ❌ WRONG — patches the original location, not the bound name update.py uses
@patch("dailybot_cli.config.get_token")
```

This applies to `DailyBotClient`, `print_*` helpers, `questionary.select`, and anything else commands import.

## Testing `~/.config/dailybot/` File I/O

Use `monkeypatch` and `tmp_path`:

```python
def test_save_credentials(monkeypatch, tmp_path):
    fake_dir = tmp_path / "config"
    monkeypatch.setattr("dailybot_cli.config.CONFIG_DIR", fake_dir)
    monkeypatch.setattr("dailybot_cli.config.CREDENTIALS_FILE", fake_dir / "credentials.json")

    from dailybot_cli.config import save_credentials, load_credentials

    save_credentials(token="t", email="e@e", organization="O", organization_uuid="u")
    assert load_credentials()["token"] == "t"
    # Verify mode 0o600
    assert (fake_dir / "credentials.json").stat().st_mode & 0o777 == 0o600
```

Existing tests in `tests/config_test.py` follow this pattern.

## Coverage Expectations

There is no enforced coverage threshold today, but the bar is:

- Every new `api_client.py` method has at least one test that asserts both **the request shape** and **the response handling**.
- Every new Click command has at least one test that asserts **a successful path** and **at least one error path** (e.g., 401, validation error).
- Auth-related code has dedicated tests for the resolution order — when adding a new credential source, add a test that proves the order is preserved.

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| Test name starts with `test_*.py` | Rename to `*_test.py` (pytest config ignores it otherwise) |
| Patches `dailybot_cli.config.get_token` but the command imports it as `from dailybot_cli.config import get_token` | Patch `dailybot_cli.commands.<module>.get_token` instead |
| Real HTTP call leaks through (test hangs or 60s timeout) | You forgot to patch `httpx.post`/`get`/etc.; verify with `pytest -s` |
| `MagicMock(spec=httpx.Response)` doesn't have `.status_code` set | Always set `mock_response.status_code = 2xx` before `.json.return_value = ...` |
| `result.exit_code == 1` but `result.output` is empty | `print_error` writes to **stderr** — use `runner.invoke(cli, [...], mix_stderr=False)` and check `result.stderr` |

## Adding a New Test

1. Open or create `tests/<module>_test.py` matching the source module under test.
2. Use a class to group related tests (`class TestFoo:`) — keeps `pytest -k` filters clean.
3. Mock all external dependencies (`httpx`, `questionary.select.ask`, on-disk paths).
4. Assert on:
   - The HTTP call shape (`mock_post.call_args[1]["json"]`, `headers["Authorization"]`)
   - The CLI exit code (`result.exit_code`)
   - The user-visible output (`result.output` for stdout, `result.stderr` for stderr)
5. Run the targeted test with `-x` first, then the full suite.
