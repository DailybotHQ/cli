"""Tests for the API client module."""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from dailybot_cli.api_client import APIError, DailyBotClient


@pytest.fixture
def client() -> DailyBotClient:
    return DailyBotClient(
        api_url="http://test-api.example.com",
        token="test-token",
        api_key="test-api-key",
    )


class TestDailyBotClientAuth:
    def test_request_code(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"detail": "Code sent"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.request_code("user@example.com")

        mock_post.assert_called_once()
        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"] == {"email": "user@example.com"}
        assert result["detail"] == "Code sent"

    def test_verify_code(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "new-token", "organization": "Org"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.verify_code("user@example.com", "123456")

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"]["email"] == "user@example.com"
        assert call_kwargs["json"]["code"] == "123456"
        assert result["token"] == "new-token"

    def test_verify_code_with_org_id(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "new-token"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.verify_code("user@example.com", "123456", organization_id=42)

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"]["organization_id"] == 42

    def test_auth_status(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"email": "user@example.com"}

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result: dict[str, Any] = client.auth_status()

        call_kwargs: dict[str, Any] = mock_get.call_args[1]
        assert "Bearer test-token" in call_kwargs["headers"]["Authorization"]
        assert result["email"] == "user@example.com"

    def test_logout(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"detail": "Logged out"}

        with patch("httpx.post", return_value=mock_response):
            result: dict[str, Any] = client.logout()

        assert result["detail"] == "Logged out"


class TestDailyBotClientUpdates:
    def test_submit_update_message(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"followups_count": 1}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.submit_update(message="Did stuff")

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"] == {"message": "Did stuff"}
        assert result["followups_count"] == 1

    def test_submit_update_structured(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"followups_count": 1}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.submit_update(done="Auth", doing="Tests", blocked="None")

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"]["done"] == "Auth"
        assert call_kwargs["json"]["doing"] == "Tests"
        assert call_kwargs["json"]["blocked"] == "None"

    def test_get_status(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"count": 1, "pending_checkins": []}

        with patch("httpx.get", return_value=mock_response):
            result: dict[str, Any] = client.get_status()

        assert result["count"] == 1


class TestDailyBotClientPublicApi:
    def test_complete_checkin(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"uuid": "response-uuid"}

        responses: list[dict[str, Any]] = [
            {"uuid": "q-0", "index": 0, "response": "Done"},
        ]
        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.complete_checkin(
                followup_uuid="followup-uuid",
                responses=responses,
                last_question_index=0,
            )

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"]["responses"] == responses
        assert "Bearer test-token" in call_kwargs["headers"]["Authorization"]
        assert result["uuid"] == "response-uuid"

    def test_list_forms(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": "form-uuid", "name": "Feedback"}]

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result: list[dict[str, Any]] = client.list_forms()

        assert result[0]["id"] == "form-uuid"
        assert "Bearer test-token" in mock_get.call_args[1]["headers"]["Authorization"]

    def test_submit_form_response(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"uuid": "response-uuid"}

        content: dict[str, str] = {"question-uuid": "Yes"}
        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.submit_form_response("form-uuid", content)

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"] == {"content": content}
        assert result["uuid"] == "response-uuid"

    def test_list_users_paginated(self, client: DailyBotClient) -> None:
        first_response: MagicMock = MagicMock(spec=httpx.Response)
        first_response.status_code = 200
        first_response.json.return_value = {
            "results": [{"uuid": "user-1", "full_name": "Jane Doe"}],
            "next": "http://test-api.example.com/v1/users/?page=2",
        }
        second_response: MagicMock = MagicMock(spec=httpx.Response)
        second_response.status_code = 200
        second_response.json.return_value = {
            "results": [{"uuid": "user-2", "full_name": "John Doe"}],
            "next": None,
        }

        with patch("httpx.get", side_effect=[first_response, second_response]) as mock_get:
            result: list[dict[str, Any]] = client.list_users()

        assert len(result) == 2
        assert mock_get.call_count == 2

    def test_give_kudos(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"uuid": "kudos-uuid"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.give_kudos(
                receivers=["user-uuid"],
                content="Great work!",
                company_value="value-uuid",
            )

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"]["receivers"] == ["user-uuid"]
        assert call_kwargs["json"]["company_value"] == "value-uuid"
        assert "by_dailybot" not in call_kwargs["json"]
        assert result["uuid"] == "kudos-uuid"


class TestDailyBotClientAgent:
    def test_submit_agent_report(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 1, "uuid": "abc"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.submit_agent_report(
                agent_name="Claude Code",
                content="Deployed v2",
            )

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"]["agent_name"] == "Claude Code"
        assert call_kwargs["headers"]["X-API-KEY"] == "test-api-key"
        assert result["id"] == 1

    def test_submit_agent_report_with_milestone(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 2, "is_milestone": True}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.submit_agent_report(
                agent_name="Claude Code",
                content="Big feature",
                is_milestone=True,
            )

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"]["is_milestone"] is True
        assert result["is_milestone"] is True

    def test_submit_agent_report_with_co_authors(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 3, "co_authors": [{"name": "Alice"}]}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.submit_agent_report(
                agent_name="Claude Code",
                content="Paired work",
                co_authors=["alice@co.com", "bob@co.com"],
            )

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"]["co_authors"] == ["alice@co.com", "bob@co.com"]
        assert result["co_authors"] == [{"name": "Alice"}]

    def test_submit_agent_report_defaults_omit_new_fields(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 4}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.submit_agent_report(
                agent_name="Claude Code",
                content="Normal report",
            )

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert "is_milestone" not in call_kwargs["json"]
        assert "co_authors" not in call_kwargs["json"]


class TestAPIError:
    def test_api_error_raised(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.json.return_value = {"detail": "Bad request"}

        with patch("httpx.post", return_value=mock_response), pytest.raises(APIError) as exc_info:
            client.request_code("bad@example.com")

        assert exc_info.value.status_code == 400
        assert "Bad request" in exc_info.value.detail

    def test_api_error_non_json(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.json.side_effect = ValueError("Not JSON")
        mock_response.text = "Internal Server Error"

        with patch("httpx.post", return_value=mock_response), pytest.raises(APIError) as exc_info:
            client.request_code("user@example.com")

        assert exc_info.value.status_code == 500
        assert "Internal Server Error" in exc_info.value.detail


class TestAgentDualAuth:
    def test_agent_headers_prefers_api_key(self) -> None:
        client = DailyBotClient(api_url="http://test.com", token="tok", api_key="key123")
        headers = client._agent_headers()
        assert headers["X-API-KEY"] == "key123"
        assert "Authorization" not in headers
        assert client._agent_auth_mode == "api_key"

    def test_agent_headers_falls_back_to_bearer(self) -> None:
        client = DailyBotClient(api_url="http://test.com", token="tok", api_key=None)
        headers = client._agent_headers()
        assert headers["Authorization"] == "Bearer tok"
        assert "X-API-KEY" not in headers
        assert client._agent_auth_mode == "bearer"

    @patch("dailybot_cli.api_client.get_token", return_value=None)
    @patch("dailybot_cli.api_client.get_api_key", return_value=None)
    def test_agent_headers_no_auth(self, _mock_key: MagicMock, _mock_tok: MagicMock) -> None:
        client = DailyBotClient(api_url="http://test.com", token=None, api_key=None)
        headers = client._agent_headers()
        assert "X-API-KEY" not in headers
        assert "Authorization" not in headers
        assert client._agent_auth_mode is None

    def test_handle_response_401_bearer_message(self) -> None:
        client = DailyBotClient(api_url="http://test.com", token="tok", api_key=None)
        client._agent_headers()  # sets _agent_auth_mode to "bearer"

        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.json.return_value = {"detail": "Unauthorized"}

        with pytest.raises(APIError) as exc_info:
            client._handle_response(mock_response)

        assert "Session expired" in exc_info.value.detail
        assert "dailybot login" in exc_info.value.detail

    def test_handle_response_401_api_key_unchanged(self) -> None:
        client = DailyBotClient(api_url="http://test.com", token="tok", api_key="key123")
        client._agent_headers()  # sets _agent_auth_mode to "api_key"

        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.json.return_value = {"detail": "Invalid API key"}

        with pytest.raises(APIError) as exc_info:
            client._handle_response(mock_response)

        assert exc_info.value.detail == "Invalid API key"
