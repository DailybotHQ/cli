# Python Development Guidelines

The "how" of writing Python in this codebase. Read alongside [STANDARDS.md](STANDARDS.md) (rules) and [CLI_COMMAND_BEST_PRACTICES.md](CLI_COMMAND_BEST_PRACTICES.md) (Click-specific).

## Type Hints

### Always Annotate

```python
# ✅ CORRECT
def get_status(self) -> dict[str, Any]:
    response: httpx.Response = httpx.get(
        f"{self.api_url}/v1/cli/status/",
        headers=self._headers(),
        timeout=self.timeout,
    )
    return self._handle_response(response)

# ❌ WRONG
def get_status(self):
    response = httpx.get(...)
    return self._handle_response(response)
```

### Modern Syntax (Python 3.9+)

```python
# ✅ CORRECT
items: list[str]
mapping: dict[str, Any]
maybe: Optional[int]
fixed: tuple[str, str, int]
variadic: tuple[str, ...]

# ❌ WRONG (legacy 3.8 style)
from typing import List, Dict, Tuple
items: List[str]
mapping: Dict[str, Any]
fixed: Tuple[str, str, int]
```

### `Optional` and `None`

```python
# ✅ When a value can be None, mark it explicitly
def get_token() -> Optional[str]: ...
def save_credentials(token: str, email: str) -> None: ...

# Reading optional dict values
result: Optional[str] = data.get("token")
if not result:
    print_error("Authentication failed: no token received.")
    raise SystemExit(1)
```

### Annotating Click Callbacks

Click decorators wrap a function but the signature still gets type-checked. Annotate every parameter:

```python
@click.command()
@click.argument("content")
@click.option("--name", "-n", default=None, help="Agent worker name.")
@click.option("--milestone", "-m", is_flag=True, default=False)
@click.option("--co-authors", "-c", multiple=True)
@click.pass_context
def agent_update(
    ctx: click.Context,
    content: str,
    name: Optional[str],
    milestone: bool,
    co_authors: tuple[str, ...],
) -> None:
    ...
```

`multiple=True` flags arrive as `tuple[str, ...]`. `is_flag=True` flags are `bool`. Optional flags without a default behave as `Optional[<type>]`.

## Error Handling

### `APIError` is the Boundary

```python
# ✅ CORRECT — catch APIError, translate, exit
try:
    with console.status("Submitting..."):
        result: dict[str, Any] = client.submit_update(message=message)
    print_update_result(result)
except APIError as e:
    if e.status_code in (401, 403):
        print_error("Session expired. Please log in again: dailybot login")
    else:
        print_error(e.detail)
    raise SystemExit(1)

# ❌ WRONG — letting raw httpx exceptions surface
result = client.submit_update(message=message)  # might raise httpx.HTTPError
print_update_result(result)
```

### `httpx.TimeoutException`

Long-running endpoints (`update`) catch the timeout separately because the operation may have succeeded server-side:

```python
except httpx.TimeoutException:
    print_error(
        "The request timed out. Dailybot may be processing your update — "
        "please check your check-ins before retrying."
    )
    raise SystemExit(1)
```

Don't add this catch to fast endpoints — it just hides a real problem.

### `SystemExit`, not `sys.exit`

```python
# ✅ CORRECT
raise SystemExit(1)

# ❌ WRONG
import sys
sys.exit(1)
```

`SystemExit` interacts cleanly with Click's `result.exit_code` in `CliRunner`. `sys.exit(...)` works at runtime but is harder to mock and reads as a foreign idiom in this codebase.

## I/O Patterns

### Reading JSON Files

```python
def load_credentials() -> Optional[dict[str, Any]]:
    if not CREDENTIALS_FILE.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(CREDENTIALS_FILE.read_text())
        return data if data.get("token") else None
    except (json.JSONDecodeError, KeyError):
        return None
```

Catch `json.JSONDecodeError` and `OSError`/`KeyError` and return a safe default. Never let a corrupted config file crash the CLI on startup.

### Writing JSON Files (with secrets)

```python
def save_credentials(token: str, email: str, ...) -> None:
    get_config_dir()  # ensures the parent dir exists
    CREDENTIALS_FILE.write_text(json.dumps({...}, indent=2))
    os.chmod(CREDENTIALS_FILE, 0o600)
```

Always:
1. Ensure parent dir exists (`get_config_dir()`).
2. Write the file.
3. `os.chmod(..., 0o600)` if it contains secrets.

## httpx Patterns

### Standard Request

```python
def submit_agent_report(self, agent_name: str, content: str, ...) -> dict[str, Any]:
    payload: dict[str, Any] = {"agent_name": agent_name, "content": content}
    # ... build payload from optional args
    response: httpx.Response = httpx.post(
        f"{self.api_url}/v1/agent-reports/",
        json=payload,
        headers=self._agent_headers(),
        timeout=self.timeout,
    )
    return self._handle_response(response)
```

### DELETE with a Body

httpx's convenience helpers don't accept a body on DELETE; use `httpx.request`:

```python
response: httpx.Response = httpx.request(
    "DELETE",
    f"{self.api_url}/v1/agent-webhook/",
    json={"agent_name": agent_name},
    headers=self._agent_headers(),
    timeout=self.timeout,
)
```

### Endpoints That Return Bare Lists

Most endpoints return a `dict`, but a few (`GET /v1/agent-messages/`) return a bare list. The pattern:

```python
def get_agent_messages(self, ...) -> list[dict[str, Any]]:
    response: httpx.Response = httpx.get(...)
    if response.status_code >= 400:
        self._handle_response(response)   # raises APIError
    return response.json()  # type: ignore[no-any-return]
```

The `# type: ignore[no-any-return]` is acceptable here — `response.json()` returns `Any`, but we know the contract.

## Click Patterns

### Group with Shared State

```python
@click.group()
@click.option("--profile", "-p", default=None)
@click.pass_context
def agent(ctx: click.Context, profile: Optional[str]) -> None:
    """Agent commands (requires API key or login session)."""
    ctx.ensure_object(dict)
    ctx.obj["profile"] = profile
```

Subcommands then read `ctx.obj.get("profile")` and accept their own `--profile` to override.

### Multi-Value Flags

```python
@click.option("--co-authors", "-c", multiple=True, help="...")
def agent_update(co_authors: tuple[str, ...]) -> None:
    co_author_list: list[str] = []
    for val in co_authors:
        for part in val.split(","):  # accept comma-separated too
            stripped: str = part.strip()
            if stripped:
                co_author_list.append(stripped)
```

Arrives as `tuple[str, ...]`. If you also want to accept comma-separated values, flatten as above.

### Detecting "Flag Was Provided" vs "Flag Has Default"

Click can't directly tell you whether a flag was provided on the command line vs. came from a `prompt`. Use the parameter source API:

```python
@click.command()
@click.option("--email", prompt="Email")
@click.pass_context
def login(ctx: click.Context, email: str) -> None:
    email_from_flag: bool = (
        ctx.get_parameter_source("email") == click.core.ParameterSource.COMMANDLINE
    )
    if email_from_flag:
        # non-interactive path
        ...
    else:
        # prompted path
        ...
```

This is how `commands/auth.py` distinguishes interactive from non-interactive login.

## Idioms

### Slugify

```python
import re

def _slugify(name: str) -> str:
    slug: str = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "default"
```

Used for profile keys derived from agent display names.

### Masking Secrets

```python
def _mask(value: str) -> str:
    if len(value) <= 4:
        return value[0] + "****" if value else "****"
    return value[:4] + "****"
```

Always mask before printing, logging, or returning to user code.

### Transactional Writes

The CLI is stateless with respect to transactions — there is no DB. If a write to `~/.config/dailybot/` partially fails, the user will see the error and can retry. Don't introduce transaction-like wrappers around file I/O; keep it simple.

## What Not To Do

| Don't | Why |
|-------|-----|
| `print(...)` for user output | Use `display.py` helpers — they handle stdout/stderr split + Rich rendering |
| `import sys; sys.exit(N)` | Use `raise SystemExit(N)` |
| `requests` library | We use `httpx` — adding `requests` doubles the install size |
| `urllib3` directly | Same — `httpx` is the boundary |
| Custom JSON parsers | `json.loads` / `json.dumps(..., indent=2)` is enough |
| Bare `except:` | Always catch a specific class. `except Exception:` is acceptable around third-party code that raises unknowns |
| Mutable default args (`def f(x=[]):`) | Use `Optional[X] = None` and assign the default inside the body |
| Circular imports | If you need a config helper from a command module, it belongs in `config.py` instead |
