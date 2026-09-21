"""Tasks transport layer in ``api_client.py`` (plan task 2).

Every test patches ``httpx`` at the call site — no test here reaches the network
(``AGENTS.md`` rule 7).
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from dailybot_cli.api_client import (
    IDEMPOTENCY_KEY_HEADER,
    IDEMPOTENCY_REPLAYED_HEADER,
    TASKS_BASE_PATH,
    TASKS_BULK_MAX_ITEMS,
    TASKS_DELTA_MAX_WINDOW_DAYS,
    DailyBotClient,
    as_query_datetime,
)


@pytest.fixture
def client() -> DailyBotClient:
    return DailyBotClient(
        api_url="http://test-api.example.com",
        token="test-token",
        api_key="test-api-key",
    )


def _response(
    status: int = 200,
    payload: Any = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = {} if payload is None else payload
    mock.headers = headers or {}
    return mock


def _envelope(results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"count": len(results or []), "next": None, "previous": None, "results": results or []}


class TestTasksConstants:
    def test_constants_are_named_not_inline(self) -> None:
        assert TASKS_BASE_PATH == "/v1/tasks/"
        assert TASKS_BULK_MAX_ITEMS == 100
        assert TASKS_DELTA_MAX_WINDOW_DAYS == 7
        assert IDEMPOTENCY_KEY_HEADER == "Idempotency-Key"
        assert IDEMPOTENCY_REPLAYED_HEADER == "Idempotency-Replayed"


class TestQueryDatetime:
    """C-6 — the ``+00:00`` trap from MEASURED_ANSWERS.md §4.

    ``datetime.isoformat()`` ends in ``+00:00``; unencoded in a query string the
    ``+`` decodes to a space and the server refuses a value that IS ISO-8601.
    """

    def test_renders_the_z_form_and_never_a_plus(self) -> None:
        rendered: str = as_query_datetime(datetime(2026, 9, 19, 13, 13, 37, tzinfo=timezone.utc))
        assert rendered == "2026-09-19T13:13:37Z"
        assert "+" not in rendered

    def test_non_utc_offset_is_converted_not_rejected(self) -> None:
        bogota: timezone = timezone(timedelta(hours=-5))
        rendered: str = as_query_datetime(datetime(2026, 9, 19, 8, 13, 37, tzinfo=bogota))
        assert rendered == "2026-09-19T13:13:37Z"
        assert "+" not in rendered

    def test_naive_datetime_is_treated_as_utc(self) -> None:
        rendered: str = as_query_datetime(datetime(2026, 9, 19, 13, 13, 37))
        assert rendered.endswith("Z")
        assert "+" not in rendered

    def test_microseconds_are_dropped_for_a_stable_cursor(self) -> None:
        rendered: str = as_query_datetime(
            datetime(2026, 9, 19, 13, 13, 37, 123456, tzinfo=timezone.utc)
        )
        assert rendered == "2026-09-19T13:13:37Z"

    def test_a_z_form_string_is_stable(self) -> None:
        assert as_query_datetime("2026-09-19T13:13:37Z") == "2026-09-19T13:13:37Z"

    def test_a_server_cursor_carrying_an_offset_is_normalised(self) -> None:
        # The server's delta_cursor is an ISO-8601 timestamp and can carry
        # `+00:00`. Echoing it back verbatim would reproduce the exact bug this
        # helper exists to prevent, so a parseable string IS normalised.
        assert as_query_datetime("2026-09-19T13:13:37+00:00") == "2026-09-19T13:13:37Z"

    def test_a_genuinely_opaque_token_is_passed_through(self) -> None:
        # Not a timestamp: not ours to reinterpret.
        assert as_query_datetime("opaque-cursor-abc123") == "opaque-cursor-abc123"


class TestTasksReadDoors:
    def test_pulse_targets_the_tasks_base_path(self, client: DailyBotClient) -> None:
        with patch("httpx.get", return_value=_response(payload={"open": 96})) as mock_get:
            result: dict[str, Any] = client.get_tasks_pulse()
        assert mock_get.call_args[0][0] == "http://test-api.example.com/v1/tasks/pulse/"
        assert result["open"] == 96

    def test_entitlements_is_a_plain_read(self, client: DailyBotClient) -> None:
        with patch("httpx.get", return_value=_response(payload={"enabled": True})) as mock_get:
            result: dict[str, Any] = client.get_tasks_entitlements()
        assert mock_get.call_args[0][0].endswith("/v1/tasks/entitlements/")
        assert result["enabled"] is True

    def test_task_list_returns_the_pagination_envelope(self, client: DailyBotClient) -> None:
        body: dict[str, Any] = _envelope([{"uuid": "t-1", "title": "a task"}])
        with patch("httpx.get", return_value=_response(payload=body)):
            result = client.list_tasks()
        assert result.count == 1
        assert result.results[0]["uuid"] == "t-1"
        assert result.next is None

    def test_task_get_uses_the_single_object_path(self, client: DailyBotClient) -> None:
        with patch("httpx.get", return_value=_response(payload={"uuid": "t-1"})) as mock_get:
            client.get_task("t-1")
        assert mock_get.call_args[0][0].endswith("/v1/tasks/tasks/t-1/")

    def test_board_delta_sends_a_z_form_cursor(self, client: DailyBotClient) -> None:
        cursor: datetime = datetime(2026, 9, 19, 13, 13, 37, tzinfo=timezone.utc)
        with patch("httpx.get", return_value=_response(payload={"changed": []})) as mock_get:
            client.get_board_delta("b-1", updated_since=cursor)
        params: dict[str, Any] = mock_get.call_args[1]["params"]
        assert params["updated_since"] == "2026-09-19T13:13:37Z"
        assert "+" not in params["updated_since"]


class TestTasksIdempotency:
    def test_task_create_sends_a_generated_key(self, client: DailyBotClient) -> None:
        with patch("httpx.post", return_value=_response(201, {"uuid": "t-1"})) as mock_post:
            client.create_task(title="a task")
        headers: dict[str, str] = mock_post.call_args[1]["headers"]
        assert IDEMPOTENCY_KEY_HEADER in headers
        assert len(headers[IDEMPOTENCY_KEY_HEADER]) >= 32

    def test_generated_keys_differ_between_invocations(self, client: DailyBotClient) -> None:
        seen: set[str] = set()
        for _ in range(3):
            with patch("httpx.post", return_value=_response(201, {"uuid": "t"})) as mock_post:
                client.create_task(title="a task")
            seen.add(mock_post.call_args[1]["headers"][IDEMPOTENCY_KEY_HEADER])
        # Two keys in one organization share an idempotency namespace
        # (MEASURED_ANSWERS.md §6 Q5), so a guessable default would collide.
        assert len(seen) == 3

    def test_an_explicit_key_is_sent_verbatim(self, client: DailyBotClient) -> None:
        with patch("httpx.post", return_value=_response(201, {"uuid": "t-1"})) as mock_post:
            client.create_task(title="a task", idempotency_key="caller-supplied")
        assert mock_post.call_args[1]["headers"][IDEMPOTENCY_KEY_HEADER] == "caller-supplied"

    def test_bulk_requires_and_always_sends_a_key(self, client: DailyBotClient) -> None:
        with patch("httpx.post", return_value=_response(200, {"results": []})) as mock_post:
            client.bulk_tasks(operation="archive", items=[{"uuid": "t-1"}])
        assert IDEMPOTENCY_KEY_HEADER in mock_post.call_args[1]["headers"]

    def test_an_ignored_door_does_not_receive_the_header(self, client: DailyBotClient) -> None:
        # IDEMPOTENCY.md marks the subscription door "ignored"; sending the header
        # there would advertise a guarantee the server does not honour.
        with patch("httpx.post", return_value=_response(200, {})) as mock_post:
            client.subscribe_task("t-1")
        assert IDEMPOTENCY_KEY_HEADER not in mock_post.call_args[1]["headers"]

    def test_a_replay_is_surfaced_to_the_caller(self, client: DailyBotClient) -> None:
        replayed = _response(201, {"uuid": "t-1"}, {IDEMPOTENCY_REPLAYED_HEADER: "true"})
        with patch("httpx.post", return_value=replayed):
            result: dict[str, Any] = client.create_task(title="a task")
        assert result["_idempotency_replayed"] is True

    def test_a_fresh_write_is_not_marked_as_a_replay(self, client: DailyBotClient) -> None:
        with patch("httpx.post", return_value=_response(201, {"uuid": "t-1"})):
            result: dict[str, Any] = client.create_task(title="a task")
        assert result["_idempotency_replayed"] is False


class TestTasksDryRun:
    def test_archive_appends_dry_run_only_when_asked(self, client: DailyBotClient) -> None:
        with patch("httpx.post", return_value=_response(200, {"dry_run": True})) as mock_post:
            client.archive_task("t-1", dry_run=True)
        assert mock_post.call_args[1]["params"]["dry_run"] == "true"

    def test_a_real_archive_sends_no_dry_run_parameter(self, client: DailyBotClient) -> None:
        with patch("httpx.post", return_value=_response(200, {})) as mock_post:
            client.archive_task("t-1")
        assert "dry_run" not in (mock_post.call_args[1].get("params") or {})

    def test_the_dry_run_body_is_returned_unshaped(self, client: DailyBotClient) -> None:
        preview: dict[str, Any] = {
            "operation": "task.archive",
            "dry_run": True,
            "reversible": True,
            "restore_path": "/v1/tasks/tasks/t-1/restore/",
            "consequence": "Soft-archives this task.",
            "affects": {"tasks": 1},
        }
        with patch("httpx.post", return_value=_response(200, preview)):
            result: dict[str, Any] = client.archive_task("t-1", dry_run=True)
        for key in ("operation", "reversible", "restore_path", "consequence", "affects"):
            assert key in result


class TestTasksTimeoutTiering:
    """docs/PERFORMANCE.md §2 — a new endpoint is read-tier by default."""

    def test_reads_use_the_default_timeout(self, client: DailyBotClient) -> None:
        with patch("httpx.get", return_value=_response(payload={})) as mock_get:
            client.get_tasks_pulse()
        assert mock_get.call_args[1]["timeout"] == client.timeout

    def test_writes_also_use_the_read_tier(self, client: DailyBotClient) -> None:
        # No Tasks door runs server-side AI processing, so none earns the submit tier.
        with patch("httpx.post", return_value=_response(201, {})) as mock_post:
            client.create_task(title="a task")
        assert mock_post.call_args[1]["timeout"] == client.timeout


class TestTasksPersonShapedDoors:
    def test_me_tasks_targets_the_person_shaped_path(self, client: DailyBotClient) -> None:
        with patch("httpx.get", return_value=_response(payload=_envelope())) as mock_get:
            client.list_my_tasks()
        assert mock_get.call_args[0][0].endswith("/v1/tasks/me/tasks/")

    def test_inbox_targets_the_person_shaped_path(self, client: DailyBotClient) -> None:
        with patch("httpx.get", return_value=_response(payload=_envelope())) as mock_get:
            client.list_tasks_inbox()
        assert mock_get.call_args[0][0].endswith("/v1/tasks/inbox/")
