---
name: endpoint-add
description: Wire a new Dailybot API endpoint into api_client.py with tests, no command-side changes.
trigger: /endpoint-add or #endpoint-add
inputs: HTTP method, path, request shape, response shape, auth scheme (Bearer or X-API-KEY-or-Bearer).
prereqs: Endpoint exists on the Dailybot API (or is in flight). You have a sample request/response.
---

# Skill: `endpoint-add`

For wiring a new HTTP endpoint into the CLI's API layer **without** touching commands. Use when the endpoint is needed by an upcoming command, or when refactoring.

If you also need to add a CLI command that uses this endpoint, prefer [`cli-command-add`](../cli-command-add/SKILL.md) — it includes this step.

## Pre-flight

- [ ] You know the **method**, **path**, **request body**, **response shape**, and **auth scheme** (`Bearer` for human, `X-API-KEY` or `Bearer` for agent).
- [ ] You know whether the endpoint can return a 200/201 vs 204 vs a bare list (some endpoints, like `GET /v1/agent-messages/`, return a list, not a wrapped object).
- [ ] You know whether the operation is fast (default 30s timeout) or AI-bound (use `LONG_TIMEOUT_SECS` or a named constant).

## Procedure

### 1. Add the method on `DailyBotClient`

In `dailybot_cli/api_client.py`. Match the section style — group new methods next to related ones (`# --- Auth endpoints ---`, `# --- Agent endpoints ---`, etc.). If the endpoint warrants a new section, add a divider comment.

For a standard request returning a dict:

```python
def my_endpoint(self, arg1: str, arg2: Optional[str] = None) -> dict[str, Any]:
    """POST /v1/my-endpoint/"""
    payload: dict[str, Any] = {"arg1": arg1}
    if arg2:
        payload["arg2"] = arg2
    response: httpx.Response = httpx.post(
        f"{self.api_url}/v1/my-endpoint/",
        json=payload,
        headers=self._agent_headers(),  # or self._headers() / self._headers(authenticated=False)
        timeout=self.timeout,
    )
    return self._handle_response(response)
```

For an endpoint returning a bare list:

```python
def list_my_things(self, agent_name: str) -> list[dict[str, Any]]:
    """GET /v1/my-list/?agent_name=..."""
    response: httpx.Response = httpx.get(
        f"{self.api_url}/v1/my-list/",
        params={"agent_name": agent_name},
        headers=self._agent_headers(),
        timeout=self.timeout,
    )
    if response.status_code >= 400:
        self._handle_response(response)
    return response.json()  # type: ignore[no-any-return]
```

For a long-running endpoint (AI parsing), use a longer timeout:

```python
response: httpx.Response = httpx.post(
    f"{self.api_url}/v1/long-running/",
    json=payload,
    headers=self._headers(),
    timeout=120.0,  # AI parsing — extract to LONG_TIMEOUT_SECS if reused
)
```

For a DELETE with a body, use `httpx.request`:

```python
response: httpx.Response = httpx.request(
    "DELETE",
    f"{self.api_url}/v1/agent-webhook/",
    json={"agent_name": agent_name},
    headers=self._agent_headers(),
    timeout=self.timeout,
)
```

### 2. Pick the right header builder

| Endpoint family | Method to call |
|-----------------|----------------|
| Public (no auth) | `self._headers(authenticated=False)` |
| Human (Bearer-only) | `self._headers()` |
| Agent (X-API-KEY-or-Bearer) | `self._agent_headers()` |

The choice maps directly to the security model — see [docs/ECOSYSTEM_CONTEXT.md](../../../docs/ECOSYSTEM_CONTEXT.md#endpoint-split-human-vs-agent).

### 3. Add tests in `tests/api_client_test.py`

```python
def test_my_endpoint(client: DailyBotClient) -> None:
    mock_response: MagicMock = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"detail": "ok"}

    with patch("httpx.post", return_value=mock_response) as mock_post:
        result: dict[str, Any] = client.my_endpoint(arg1="foo", arg2="bar")

    mock_post.assert_called_once()
    call_kwargs: dict[str, Any] = mock_post.call_args[1]
    assert call_kwargs["json"] == {"arg1": "foo", "arg2": "bar"}
    # Confirm correct auth header
    assert "X-API-KEY" in call_kwargs["headers"]   # for agent endpoints
    # or: assert "Bearer" in call_kwargs["headers"]["Authorization"]
    assert result["detail"] == "ok"
```

Add at least:
- A success path that asserts both the request shape and the response handling.
- A test that exercises optional args (omit them, confirm they're not in the payload).
- An auth-related assertion (header check).

For endpoints returning bare lists, also assert `assert isinstance(result, list)`.

### 4. Update docs

- `docs/API_REFERENCE.md` — add a row in the right HTTP Endpoints table (Human / Agent / Standalone).
- If the endpoint introduces a new auth pattern (e.g., a third header), update `docs/ARCHITECTURE.md` `api_client.py` section and `docs/SECURITY.md`.

### 5. Run the suite

```bash
pytest tests/api_client_test.py -x
```

### 6. Commit

```
feat(client): add my_endpoint for POST /v1/my-endpoint/

## Summary
Wires the my_endpoint API call into DailyBotClient. No command changes.

## Change Log
- DailyBotClient.my_endpoint
- 3 test cases (success, optional args, auth header check)
- API_REFERENCE entry

## Risks
- None — backend endpoint already deployed
```

## Don'ts

- Don't add the command in the same commit — keep this small and reviewable. Land the client method first, then build the command on top.
- Don't introduce a new `httpx` import pattern — match the existing module style.
- Don't catch `httpx.HTTPError` inside the method — let `_handle_response` raise `APIError`.
- Don't hardcode timeouts — use `self.timeout` or extract a named constant.
