"""Client methods for the notification catalog, personal preferences and channel search (PLAN_004)."""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from dailybot_cli.api_client import DailyBotClient

API_URL: str = "https://api.example.test"
BASE: str = f"{API_URL}/v1/plan/"


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


class TestCatalog:
    def test_reads_the_catalog(self, client: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.get", return_value=_response({"groups": [], "kinds": []})
        ) as get:
            assert client.get_notifications_catalog() == {"groups": [], "kinds": []}
        assert get.call_args.args[0] == f"{BASE}notifications/catalog/"


class TestMyNotifications:
    def test_reads_the_preferences(self, client: DailyBotClient) -> None:
        with patch(
            "dailybot_cli.api_client.httpx.get", return_value=_response({"items": []})
        ) as get:
            client.get_my_notifications()
        assert get.call_args.args[0] == f"{BASE}me/notifications/"

    def test_a_put_sends_only_what_was_passed(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response({})) as put:
            client.put_my_notifications(items=[{"kind": "tasks_commented", "chat": True}])
        assert put.call_args.args[0] == f"{BASE}me/notifications/"
        assert put.call_args.kwargs["json"] == {
            "items": [{"kind": "tasks_commented", "chat": True}]
        }

    def test_a_destination_alone_is_a_valid_put(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response({})) as put:
            client.put_my_notifications(destination={"type": "dm"})
        assert put.call_args.kwargs["json"] == {"destination": {"type": "dm"}}

    def test_a_channel_destination_carries_the_external_id(self, client: DailyBotClient) -> None:
        destination: dict[str, Any] = {"type": "channel", "channel": {"external_id": "C0000000A"}}
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response({})) as put:
            client.put_my_notifications(destination=destination)
        assert put.call_args.kwargs["json"] == {"destination": destination}

    def test_paused_until_is_never_sent(self, client: DailyBotClient) -> None:
        # The API answers 501 for a datetime and only null is accepted: the CLI does not offer it.
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response({})) as put:
            client.put_my_notifications(items=[{"kind": "tasks_assigned", "email": True}])
        assert "paused_until" not in put.call_args.kwargs["json"]

    def test_the_agent_name_is_not_stamped_on_the_put(self, stamped: DailyBotClient) -> None:
        # The door answers 400 unknown_field for agent_name; a preference is not task work.
        with patch("dailybot_cli.api_client.httpx.put", return_value=_response({})) as put:
            stamped.put_my_notifications(items=[{"kind": "tasks_assigned", "chat": False}])
        assert "agent_name" not in put.call_args.kwargs["json"]
        assert not any("agent" in str(k).lower() for k in dict(put.call_args.kwargs["headers"]))

    def test_an_empty_put_is_refused_before_any_request(self, client: DailyBotClient) -> None:
        with patch("dailybot_cli.api_client.httpx.put") as put, pytest.raises(ValueError):
            client.put_my_notifications()
        put.assert_not_called()


class TestChannelSearch:
    def test_search_and_type_are_query_params(self, client: DailyBotClient) -> None:
        page: dict[str, Any] = {
            "count": 1,
            "next": None,
            "previous": None,
            "results": [{"external_id": "C1", "name": "eng", "type": "channel"}],
        }
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(page)) as get:
            result = client.search_channels(search="en", channel_type="channel")
        assert get.call_args.args[0] == f"{BASE}channels/"
        assert get.call_args.kwargs["params"]["search"] == "en"
        assert get.call_args.kwargs["params"]["type"] == "channel"
        assert result.results[0]["external_id"] == "C1"

    def test_no_filters_sends_no_filter_params(self, client: DailyBotClient) -> None:
        page: dict[str, Any] = {"count": 0, "next": None, "previous": None, "results": []}
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(page)) as get:
            client.search_channels()
        params: dict[str, Any] = get.call_args.kwargs.get("params") or {}
        assert "search" not in params and "type" not in params

    def test_paging_helpers_are_honoured(self, client: DailyBotClient) -> None:
        page: dict[str, Any] = {"count": 0, "next": None, "previous": None, "results": []}
        with patch("dailybot_cli.api_client.httpx.get", return_value=_response(page)) as get:
            client.search_channels(page=2, page_size=10)
        params: dict[str, Any] = get.call_args.kwargs["params"]
        assert params["page"] == 2 and params["page_size"] == 10
