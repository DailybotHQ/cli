"""Client methods for the personal briefing and the timeline / task list filters (PLAN_004)."""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from dailybot_cli.api_client import IDEMPOTENCY_KEY_HEADER, DailyBotClient

API_URL: str = "https://api.example.test"
BASE: str = f"{API_URL}/v1/plan/"
PROJECT_A: str = "00000000-0000-0000-0000-0000000000a1"
PROJECT_B: str = "00000000-0000-0000-0000-0000000000a2"
MILESTONE: str = "00000000-0000-0000-0000-0000000000f1"


def _response(payload: Any, status: int = 200) -> Any:
    mock: MagicMock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.json.return_value = payload
    mock.headers = {}
    return mock


@pytest.fixture
def client() -> DailyBotClient:
    return DailyBotClient(api_url=API_URL, token="test-token")


@pytest.fixture
def stamped() -> DailyBotClient:
    return DailyBotClient(api_url=API_URL, token="test-token", agent_name="Claude Code")


class TestBriefing:
    def test_get_and_preview_paths(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response({})) as get:
            client.get_my_briefing()
            assert get.call_args.args[0] == f"{BASE}me/briefing/"
            client.get_my_briefing_preview()
            assert get.call_args.args[0] == f"{BASE}me/briefing/preview/"

    def test_put_sends_only_passed_fields(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response({})) as put:
            client.put_my_briefing(time="08:30", enabled=None, weekdays=None, timezone=None)
        assert put.call_args.args[0] == f"{BASE}me/briefing/"
        assert put.call_args.kwargs["json"] == {"time": "08:30"}

    def test_false_is_a_value_not_an_absence(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response({})) as put:
            client.put_my_briefing(enabled=False, email=False, skip_when_empty=False)
        assert put.call_args.kwargs["json"] == {
            "enabled": False,
            "email": False,
            "skip_when_empty": False,
        }

    def test_the_timezone_is_sent_only_when_passed(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response({})) as put:
            client.put_my_briefing(time="09:00")
            assert "timezone" not in put.call_args.kwargs["json"]
            client.put_my_briefing(timezone="America/Bogota")
            assert put.call_args.kwargs["json"] == {"timezone": "America/Bogota"}

    def test_an_empty_put_is_refused_locally(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.put") as put, pytest.raises(ValueError):
            client.put_my_briefing()
        put.assert_not_called()

    def test_no_agent_stamp_on_the_put(self, stamped: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response({})) as put:
            stamped.put_my_briefing(time="09:00")
        assert "agent_name" not in put.call_args.kwargs["json"]

    def test_send_test_dry_run_and_real(self, client: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.post", return_value=_response({"dry_run": True})
        ) as post:
            client.send_my_briefing_test(dry_run=True)
            assert post.call_args.args[0] == f"{BASE}me/briefing/send-test/"
            assert post.call_args.kwargs["params"] == {"dry_run": "true"}
            assert IDEMPOTENCY_KEY_HEADER not in dict(post.call_args.kwargs.get("headers") or {})
            client.send_my_briefing_test(dry_run=False)
            assert not post.call_args.kwargs.get("params")


class TestTimelineFilters:
    def test_repeated_project_and_milestone_filters_are_repeated_query_keys(
        self, client: DailyBotClient
    ) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response({})) as get:
            client.get_tasks_timeline(
                date_from="2026-10-01",
                date_to="2026-12-31",
                projects=[PROJECT_A, PROJECT_B],
                milestones=[MILESTONE],
            )
        params: dict[str, Any] = get.call_args.kwargs["params"]
        assert params["project"] == [PROJECT_A, PROJECT_B]
        assert params["milestone"] == [MILESTONE]
        assert params["from"] == "2026-10-01" and params["to"] == "2026-12-31"

    def test_no_filters_sends_no_filter_keys(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response({})) as get:
            client.get_tasks_timeline()
        params: dict[str, Any] = get.call_args.kwargs.get("params") or {}
        assert "project" not in params and "milestone" not in params

    def test_list_tasks_passes_a_milestone_filter_through(self, client: DailyBotClient) -> None:
        body: dict[str, Any] = {"count": 0, "next": None, "previous": None, "results": []}
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(body)) as get:
            client.list_tasks(filters={"milestone": [MILESTONE]})
        assert get.call_args.kwargs["params"]["milestone"] == [MILESTONE]

    def test_a_list_value_really_becomes_repeated_keys_on_the_wire(self) -> None:
        # httpx encodes a list as repeated keys; pinned so a change of library behaviour is caught.
        request: httpx.Request = httpx.Request(
            "GET", f"{BASE}timeline/", params={"project": [PROJECT_A, PROJECT_B]}
        )
        assert str(request.url).count("project=") == 2
