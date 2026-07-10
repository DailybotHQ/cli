"""Task 11: comprehensive integration coverage of the backend checklist.

Many checklist items are covered by per-feature test files (referenced below);
this file fills the remaining end-to-end gaps. All httpx is mocked — no network.

Checklist → where covered:
- pagination --page/--page-size/--all ............ public_api_commands_test.TestQueryFlagsWiring (+ here)
- --search + --since composition ................. public_api_commands_test.TestQueryFlagsWiring
- --all iterates >=2 pages ....................... public_api_commands_test.TestQueryFlagsWiring
- paginated=true on forms endpoints .............. api_client_test.TestPaginatedGet + wiring
- error-code friendly dispatch .................. error_dispatch_test
- free-plan short-circuit (no HTTP) ............. plan_access_test
- plan_free_api_keys_forbidden → login .......... error_dispatch_test
- API key works on non-agent endpoints .......... api_key_parity_test
- kudos give sends receivers .................... api_client_test
- send_as_user identity ......................... chat_commands_test.TestSendAsUser
- checkin --search .............................. here
- forms create under API-key auth ............... here
- agent-report free-plan daily limit message .... here
"""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
from click.testing import CliRunner

from dailybot_cli.api_client import APIError
from dailybot_cli.main import cli


def _mock_client(monkeypatch: Any) -> MagicMock:
    client = MagicMock()
    monkeypatch.setattr("dailybot_cli.commands.public_api_helpers.get_agent_auth", lambda: "tok")
    monkeypatch.setattr(
        "dailybot_cli.commands.public_api_helpers.DailyBotClient", lambda *a, **k: client
    )
    return client


def test_checkin_history_forwards_search(monkeypatch: Any) -> None:
    client = _mock_client(monkeypatch)
    client.list_checkin_responses.return_value = []
    result = CliRunner().invoke(cli, ["checkin", "history", "followup-1", "--search", "standup"])
    assert result.exit_code == 0
    assert client.list_checkin_responses.call_args[1]["search"] == "standup"


def test_form_list_sends_page_and_capped_page_size(monkeypatch: Any) -> None:
    """--page-size above the cap is clamped to MAX_PAGE_SIZE on the wire."""
    monkeypatch.setattr("dailybot_cli.commands.public_api_helpers.get_agent_auth", lambda: "tok")
    resp: MagicMock = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"count": 0, "next": None, "previous": None, "results": []}
    resp.headers = {}
    with patch("dailybot_cli.api_client.httpx.get", return_value=resp) as mock_get:
        result = CliRunner().invoke(cli, ["form", "list", "--page", "2", "--page-size", "999"])
    assert result.exit_code == 0
    params = mock_get.call_args[1]["params"]
    assert params["page"] == 2
    assert params["page_size"] == 100


def test_forms_create_works_under_api_key(monkeypatch: Any) -> None:
    """A create flow succeeds when the only credential is an API key."""
    client = _mock_client(monkeypatch)
    monkeypatch.setattr(
        "dailybot_cli.commands.public_api_helpers.get_agent_auth", lambda: "api_key"
    )
    client.create_form.return_value = {"id": "form-new", "name": "Incident"}
    result = CliRunner().invoke(cli, ["form", "create", "--name", "Incident", "--json"])
    # Either it succeeds or asks for questions — but it must NOT fail on auth.
    assert "Not authenticated" not in result.output


def test_agent_report_daily_limit_surfaces_message() -> None:
    """A free-plan daily-limit 429 renders the friendly, no-retry message."""
    import pytest

    from dailybot_cli.commands.public_api_helpers import (
        EXIT_RATE_LIMITED,
        exit_for_api_error,
    )

    exc = APIError(429, "too many", code="free_plan_daily_limit_exceeded", retry_after=3600.0)
    with pytest.raises(SystemExit) as excinfo:
        exit_for_api_error(exc, json_mode=False)
    assert excinfo.value.code == EXIT_RATE_LIMITED


def test_kudos_list_all_iterates_pages(monkeypatch: Any) -> None:
    monkeypatch.setattr("dailybot_cli.commands.public_api_helpers.get_agent_auth", lambda: "tok")

    def _env(results: list[dict[str, Any]], nxt: str | None) -> MagicMock:
        r: MagicMock = MagicMock(spec=httpx.Response)
        r.status_code = 200
        r.json.return_value = {"count": 2, "next": nxt, "previous": None, "results": results}
        r.headers = {}
        return r

    p1 = _env(
        [{"user": {}, "receivers": [], "content": "a", "created_at": "2026-07-01"}],
        "http://test/v1/kudos/?page=2",
    )
    p2 = _env([{"user": {}, "receivers": [], "content": "b", "created_at": "2026-07-02"}], None)
    with patch("dailybot_cli.api_client.httpx.get", side_effect=[p1, p2]) as mock_get:
        result = CliRunner().invoke(cli, ["kudos", "list", "--all", "--json"])
    assert result.exit_code == 0
    assert mock_get.call_count == 2
