---
name: cli-command-add
description: End-to-end procedure for adding a new top-level CLI command or subgroup command.
trigger: /cli-command-add or #cli-command-add
inputs: Command name, signature (flags/args), backend endpoint it should call (or "no endpoint" for purely local commands), and what it should display.
prereqs: Read AGENTS.md, docs/CLI_COMMAND_BEST_PRACTICES.md, docs/API_REFERENCE.md.
---

# Skill: `cli-command-add`

The full procedure for adding a new CLI command, end-to-end. Optimized for getting it right the first time.

## Pre-flight

Before writing any code, confirm with the user:

- [ ] **Command name and group.** Top-level (`dailybot foo`) or under an existing group (`dailybot agent foo`)? If a new group: are there ≥3 subcommands planned? (See [CLI_COMMAND_BEST_PRACTICES.md](../../../docs/CLI_COMMAND_BEST_PRACTICES.md#when-to-add-a-new-command-group).)
- [ ] **Auth scheme.** Bearer (human) or API-key/Bearer (agent)? Will route through `_require_auth` or `_resolve_agent_context`.
- [ ] **Endpoint.** Does the Dailybot API endpoint exist? If not, it must land server-side first (or be in flight) — coordinate before adding the CLI surface.
- [ ] **Output shape.** Panel (action result) or table (list)? Or both?
- [ ] **Flags.** Reuse standard short aliases: `-n` name, `-p` profile, `-d` metadata, `-j` json-data, `-m` milestone, `-c` co-authors. Only invent a new short alias if the long form is unique.

## Procedure

### 1. Add the API client method (if needed)

In `dailybot_cli/api_client.py`, append a method on `DailyBotClient`. Match the file's existing patterns:

```python
def submit_my_thing(
    self,
    arg1: str,
    arg2: Optional[str] = None,
) -> dict[str, Any]:
    """POST /v1/my-endpoint/"""
    payload: dict[str, Any] = {"arg1": arg1}
    if arg2:
        payload["arg2"] = arg2
    response: httpx.Response = httpx.post(
        f"{self.api_url}/v1/my-endpoint/",
        json=payload,
        headers=self._agent_headers(),  # or self._headers() for human endpoints
        timeout=self.timeout,
    )
    return self._handle_response(response)
```

### 2. Add the display helper (if a new shape)

In `dailybot_cli/display.py`:

```python
def print_my_thing(data: dict[str, Any]) -> None:
    """Display the result of my_thing."""
    table: Table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Field A", str(data.get("field_a", "")))
    table.add_row("Field B", str(data.get("field_b", "")))
    console.print(Panel(table, title="[bold]My Thing[/bold]", border_style="green"))
```

### 3. Add the Click command

In `dailybot_cli/commands/<file>.py`. Follow the [Five-Step Command Pattern](../../../docs/CLI_COMMAND_BEST_PRACTICES.md#the-five-step-command-pattern):

```python
@click.command()
@click.argument("arg1")
@click.option("--arg2", "-2", default=None, help="Optional arg2.")
@click.option("--name", "-n", default=None, help="Agent worker name.")
@click.option("--profile", "-p", default=None, help="Agent profile name.")
@click.pass_context
def my_thing(
    ctx: click.Context,
    arg1: str,
    arg2: Optional[str],
    name: Optional[str],
    profile: Optional[str],
) -> None:
    """Do my thing.

    \b
      dailybot my-thing foo
      dailybot my-thing foo --arg2 bar
    """
    profile_flag: Optional[str] = profile or ctx.obj.get("profile")
    agent_name, client = _resolve_agent_context(profile_flag, name)

    try:
        with console.status("Doing my thing..."):
            result: dict[str, Any] = client.submit_my_thing(arg1=arg1, arg2=arg2)
    except APIError as e:
        if e.status_code in (401, 403):
            print_error("Session expired. Run: dailybot login")
        else:
            print_error(e.detail)
        raise SystemExit(1)

    print_my_thing(result)
```

### 4. Register the command

If new top-level: `dailybot_cli/main.py`:

```python
from dailybot_cli.commands.my_thing import my_thing  # add at top

cli.add_command(my_thing)  # add near the other add_command lines
```

If new subcommand of `agent`: it's already wired via the `@agent.command(name="my-thing")` decorator.

### 5. Add tests

In `tests/commands_test.py` (or a new `*_test.py` if it's a whole new module):

```python
@patch("dailybot_cli.commands.my_thing._resolve_agent_context")
def test_my_thing_success(mock_resolve, runner: CliRunner) -> None:
    mock_client: MagicMock = MagicMock()
    mock_client.submit_my_thing.return_value = {"field_a": "x", "field_b": "y"}
    mock_resolve.return_value = ("My Agent", mock_client)

    result = runner.invoke(cli, ["my-thing", "foo", "--arg2", "bar"])

    assert result.exit_code == 0
    mock_client.submit_my_thing.assert_called_once_with(arg1="foo", arg2="bar")
```

Add at least:
- One success path test.
- One auth-failure (401/403) test.
- One generic API-error test.

In `tests/api_client_test.py`, add a test for the new client method that asserts the request shape.

### 6. Update docs

- `README.md` — add a row in the Commands table; add a worked example in the relevant section.
- `docs/API_REFERENCE.md` — add the CLI command entry and the HTTP endpoint row.
- `AGENTS.md` Project Structure section — only if you added a new file.

### 7. Run the suite

```bash
pytest -x
```

### 8. Try it locally

```bash
pip install -e .
dailybot --api-url https://staging.dailybot.com my-thing foo
```

### 9. Commit

```
feat(<scope>): add `dailybot my-thing` command

## Summary
Adds <command> for <use case>.

## Change Log
- DailyBotClient.submit_my_thing for POST /v1/my-endpoint/
- print_my_thing display helper
- Click command in commands/my_thing.py
- 3 test cases (success, 401, generic error)
- README + API_REFERENCE updates

## Risks
- None for backwards compat — new command only
```

## Don'ts

- Don't put business logic in the command callback — push to client/display.
- Don't `print(...)` for output — use `display.py`.
- Don't catch `httpx.HTTPError` — let `_handle_response` translate to `APIError`.
- Don't hardcode the URL inside the command — it belongs in `api_client.py`.
- Don't bump the version (separate concern; see `release-prep`).
