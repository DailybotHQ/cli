# Testing Guide

## Conventions

- **File naming**: `*_test.py` (enforced by `pytest.ini::python_files = *_test.py`). NEVER `test_*.py`.
- **Location**: `tests/` at the repo root.
- **Test framework**: `pytest`. No `unittest.TestCase` subclassing — use plain functions or grouping classes (e.g., `class TestVersionAndHelp:`).
- **Mocking**: `unittest.mock.MagicMock` and `unittest.mock.patch`.
- **CLI invocation**: `click.testing.CliRunner`.

## Running Tests

```bash
pytest                                   # full suite
pytest -x                                # stop on first failure
pytest -v                                # verbose
pytest -k <keyword>                      # filter by name
pytest tests/api_client_test.py          # one file
pytest tests/api_client_test.py::TestDailyBotClientAuth::test_request_code   # one test
pytest --tb=short                        # shorter tracebacks
pytest -s                                # don't capture stdout (debugging)
```

## File Layout

```
tests/
├── __init__.py                    # empty, just makes the dir importable
├── api_client_test.py             # DailyBotClient + APIError (every HTTP method)
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
