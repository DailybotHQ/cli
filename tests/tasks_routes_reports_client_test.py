"""Client methods for organization notification routes and scheduled reports (PLAN_004)."""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from dailybot_cli.api_client import IDEMPOTENCY_KEY_HEADER, DailyBotClient

API_URL: str = "https://api.example.test"
BASE: str = f"{API_URL}/v1/plan/"
ROUTE: str = "00000000-0000-0000-0000-0000000000a1"
REPORT: str = "00000000-0000-0000-0000-0000000000b1"
CHANNEL: dict[str, str] = {"external_id": "C0000000A"}


def _response(payload: Any, status: int = 200, headers: dict[str, str] | None = None) -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = payload
    mock.headers = headers or {}
    return mock


def _page(rows: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    items = rows or []
    return {"count": len(items), "next": None, "previous": None, "results": items, **extra}


@pytest.fixture
def client() -> DailyBotClient:
    return DailyBotClient(api_url=API_URL, token="test-token")


@pytest.fixture
def stamped() -> DailyBotClient:
    return DailyBotClient(api_url=API_URL, token="test-token", agent_name="Claude Code")


def _headers(call: Any) -> dict[str, str]:
    return dict(call.kwargs.get("headers") or {})


class TestListEnvelopeExtras:
    def test_viewer_survives_to_the_caller(self, client: DailyBotClient) -> None:
        body = _page([{"uuid": ROUTE}], viewer={"can_manage": True})
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(body)):
            result = client.list_notification_routes()
        assert result.extra["viewer"] == {"can_manage": True}
        assert result.results[0]["uuid"] == ROUTE

    def test_a_plain_list_has_no_extras(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(_page())):
            assert client.list_boards().extra == {}


class TestRoutes:
    def test_list_get_and_deliveries_paths(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(_page())) as get:
            client.list_notification_routes()
            assert get.call_args.args[0] == f"{BASE}notification-routes/"
            client.list_route_deliveries(ROUTE)
            assert get.call_args.args[0] == f"{BASE}notification-routes/{ROUTE}/deliveries/"
        with patch(
            "dailybot_cli.api_client.httpx.get", return_value=_response({"uuid": ROUTE})
        ) as get:
            client.get_notification_route(ROUTE)
        assert get.call_args.args[0] == f"{BASE}notification-routes/{ROUTE}/"

    def test_create_sends_the_body_and_an_idempotency_key(self, client: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": ROUTE}, 201)
        ) as post:
            result = client.create_notification_route(
                name="Completions", channel=CHANNEL, kinds=["task.completed"]
            )
        assert post.call_args.args[0] == f"{BASE}notification-routes/"
        assert post.call_args.kwargs["json"] == {
            "name": "Completions",
            "channel": CHANNEL,
            "kinds": ["task.completed"],
        }
        assert IDEMPOTENCY_KEY_HEADER in _headers(post.call_args)
        assert result["_idempotency_key"]

    def test_create_passes_scope_and_enabled_only_when_given(self, client: DailyBotClient) -> None:
        scope: dict[str, Any] = {"type": "boards", "uuids": [ROUTE]}
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({}, 201)) as post:
            client.create_notification_route(
                name="n", channel=CHANNEL, kinds=["task.created"], scope=scope, enabled=False
            )
        body = post.call_args.kwargs["json"]
        assert body["scope"] == scope and body["enabled"] is False

    def test_a_given_key_is_reused(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({}, 201)) as post:
            client.create_notification_route(
                name="n", channel=CHANNEL, kinds=["task.created"], idempotency_key="mine"
            )
        assert _headers(post.call_args)[IDEMPOTENCY_KEY_HEADER] == "mine"

    def test_update_is_a_partial_patch_without_a_key(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.patch", return_value=_response({})) as patch_:
            client.update_notification_route(ROUTE, name="New", enabled=None, kinds=None)
        assert patch_.call_args.args[0] == f"{BASE}notification-routes/{ROUTE}/"
        assert patch_.call_args.kwargs["json"] == {"name": "New"}
        assert IDEMPOTENCY_KEY_HEADER not in _headers(patch_.call_args)

    def test_update_with_nothing_is_refused_locally(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.patch") as patch_, pytest.raises(ValueError):
            client.update_notification_route(ROUTE)
        patch_.assert_not_called()

    def test_delete(self, client: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.request", return_value=_response({}, 204)
        ) as request:
            client.delete_notification_route(ROUTE)
        assert request.call_args.args[:2] == ("DELETE", f"{BASE}notification-routes/{ROUTE}/")

    def test_send_test_dry_run_is_a_query_param(self, client: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"dry_run": True})
        ) as post:
            client.send_route_test(ROUTE, dry_run=True)
        assert post.call_args.args[0] == f"{BASE}notification-routes/{ROUTE}/send-test/"
        assert post.call_args.kwargs["params"] == {"dry_run": "true"}
        assert IDEMPOTENCY_KEY_HEADER not in _headers(post.call_args)

    def test_a_real_send_test_has_no_dry_run_param(self, client: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"sent": True})
        ) as post:
            client.send_route_test(ROUTE, dry_run=False)
        assert not post.call_args.kwargs.get("params")

    def test_the_agent_name_is_not_stamped(self, stamped: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({}, 201)) as post:
            stamped.create_notification_route(name="n", channel=CHANNEL, kinds=["task.created"])
        assert "agent_name" not in post.call_args.kwargs["json"]
        assert not any("agent" in k.lower() for k in _headers(post.call_args))

    def test_a_uuid_with_a_slash_is_refused_before_any_request(
        self, client: DailyBotClient
    ) -> None:
        with patch("dailybot_cli.api_client.httpx.get") as get, pytest.raises(Exception) as raised:
            client.get_notification_route("x/../../boards")
        get.assert_not_called()
        assert "identifier" in str(raised.value).lower()


class TestReports:
    def test_list_get_preview_runs_paths(self, client: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.get",
            return_value=_response(
                _page(),
            ),
        ) as get:
            client.list_reports()
            assert get.call_args.args[0] == f"{BASE}reports/"
            client.list_report_runs(REPORT)
            assert get.call_args.args[0] == f"{BASE}reports/{REPORT}/runs/"
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response({})) as get:
            client.get_report(REPORT)
            assert get.call_args.args[0] == f"{BASE}reports/{REPORT}/"
            client.get_report_preview(REPORT)
            assert get.call_args.args[0] == f"{BASE}reports/{REPORT}/preview/"

    def test_create_body_and_key(self, client: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"uuid": REPORT}, 201)
        ) as post:
            client.create_report(
                name="Week End",
                kind="week_end",
                weekdays=[5],
                time="09:00",
                channel=CHANNEL,
                email_recipients=["00000000-0000-0000-0000-0000000000c1"],
            )
        body = post.call_args.kwargs["json"]
        assert body == {
            "name": "Week End",
            "kind": "week_end",
            "weekdays": [5],
            "time": "09:00",
            "channel": CHANNEL,
            "email_recipients": ["00000000-0000-0000-0000-0000000000c1"],
        }
        assert IDEMPOTENCY_KEY_HEADER in _headers(post.call_args)

    def test_timezone_is_sent_only_when_given(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({}, 201)) as post:
            client.create_report(
                name="n", kind="daily", weekdays=[1], time="09:00", channel=CHANNEL
            )
            assert "timezone" not in post.call_args.kwargs["json"]
            client.create_report(
                name="n",
                kind="daily",
                weekdays=[1],
                time="09:00",
                channel=CHANNEL,
                timezone="America/Bogota",
            )
            assert post.call_args.kwargs["json"]["timezone"] == "America/Bogota"

    def test_update_sends_only_passed_fields(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.patch", return_value=_response({})) as patch_:
            client.update_report(REPORT, time="10:15", name=None)
        assert patch_.call_args.kwargs["json"] == {"time": "10:15"}

    def test_explicit_clears_are_sendable(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.patch", return_value=_response({})) as patch_:
            client.update_report(REPORT, clear_channel=True)
            assert patch_.call_args.kwargs["json"] == {"channel": None}
            client.update_report(REPORT, clear_email_recipients=True)
            assert patch_.call_args.kwargs["json"] == {"email_recipients": []}

    def test_delete_and_send_test(self, client: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.request", return_value=_response({}, 204)
        ) as request:
            client.delete_report(REPORT)
        assert request.call_args.args[:2] == ("DELETE", f"{BASE}reports/{REPORT}/")
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"dry_run": True})
        ) as post:
            client.send_report_test(REPORT, dry_run=True)
        assert post.call_args.args[0] == f"{BASE}reports/{REPORT}/send-test/"
        assert post.call_args.kwargs["params"] == {"dry_run": "true"}

    def test_the_agent_name_is_not_stamped(self, stamped: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.post", return_value=_response({}, 201)) as post:
            stamped.create_report(
                name="n", kind="daily", weekdays=[1], time="09:00", channel=CHANNEL
            )
        assert "agent_name" not in post.call_args.kwargs["json"]
