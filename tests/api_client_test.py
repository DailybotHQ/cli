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

    def test_create_chat_completion(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "completed",
            "message": {"role": "assistant", "content": "Hi there."},
        }

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.create_chat_completion(
                message="Hi",
                history=[{"role": "assistant", "content": "Welcome back"}],
                session_id="terminal",
            )

        call_args: tuple[Any, ...] = mock_post.call_args[0]
        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_args[0].endswith("/v1/cli/chat/completions/")
        assert call_kwargs["json"] == {
            "message": "Hi",
            "history": [{"role": "assistant", "content": "Welcome back"}],
            "session_id": "terminal",
        }
        assert "Bearer test-token" in call_kwargs["headers"]["Authorization"]
        assert result["message"]["content"] == "Hi there."


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

    def test_list_checkins(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{"id": "followup-uuid", "name": "Daily Standup"}],
            "next": None,
        }

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result: list[dict[str, Any]] = client.list_checkins()

        assert result[0]["id"] == "followup-uuid"
        assert mock_get.call_args[0][0].endswith("/v1/checkins/")

    def test_get_template_with_followup_context(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "template-uuid", "questions": {"fields": []}}

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result: dict[str, Any] = client.get_template(
                "template-uuid",
                followup_uuid="followup-uuid",
            )

        assert result["id"] == "template-uuid"
        assert mock_get.call_args[1]["params"] == {
            "render_special_vars": "true",
            "followup_id": "followup-uuid",
        }

    def test_get_checkin(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "followup-uuid", "template": "template-uuid"}

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result: dict[str, Any] = client.get_checkin("followup-uuid")

        assert result["template"] == "template-uuid"
        assert mock_get.call_args[0][0].endswith("/v1/checkins/followup-uuid/")

    def test_get_checkin_detail(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "followup-uuid",
            "name": "Standup",
            "questions": [{"uuid": "q1", "index": 0, "required": True, "is_blocker": False}],
            "participants": {"users": [{"uuid": "u1", "name": "Jane Doe"}], "teams": []},
        }

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result: dict[str, Any] = client.get_checkin_detail("followup-uuid")

        assert result["participants"]["users"][0]["name"] == "Jane Doe"
        assert mock_get.call_args[0][0].endswith("/v1/checkins/followup-uuid/detail/")

    def test_list_checkin_responses(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{"uuid": "response-uuid"}],
            "next": None,
        }

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result: list[dict[str, Any]] = client.list_checkin_responses(
                "followup-uuid",
                date_start="2026-07-01",
                date_end="2026-07-01",
            )

        assert result[0]["uuid"] == "response-uuid"
        assert mock_get.call_args[0][0].endswith("/v1/checkins/followup-uuid/responses/")
        assert mock_get.call_args[1]["params"] == {
            "date_start": "2026-07-01",
            "date_end": "2026-07-01",
        }

    def test_list_checkin_responses_user_filter(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [], "next": None}

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client.list_checkin_responses(
                "followup-uuid",
                date_start="2026-07-01",
                date_end="2026-07-31",
                user="user-uuid",
            )

        # Default sends no `all` param; `user` narrows to one participant.
        assert mock_get.call_args[1]["params"] == {
            "date_start": "2026-07-01",
            "date_end": "2026-07-31",
            "user": "user-uuid",
        }

    def test_list_checkin_responses_all_is_backward_compatible_noop(
        self, client: DailyBotClient
    ) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [], "next": None}

        # `all_responses=True` is accepted (legacy callers) even though the server
        # already returns all participants by default.
        with patch("httpx.get", return_value=mock_response) as mock_get:
            client.list_checkin_responses("followup-uuid", all_responses=True)

        assert mock_get.call_args[1]["params"] == {"all": "true"}

    def test_update_checkin_response(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"uuid": "response-uuid"}
        responses: list[dict[str, Any]] = [{"uuid": "q-0", "index": 0, "response": "Edited"}]

        with patch("httpx.put", return_value=mock_response) as mock_put:
            result: dict[str, Any] = client.update_checkin_response(
                "followup-uuid",
                responses,
                last_question_index=0,
            )

        assert result["uuid"] == "response-uuid"
        assert mock_put.call_args[0][0].endswith("/v1/checkins/followup-uuid/responses/")
        assert mock_put.call_args[1]["json"] == {
            "responses": responses,
            "last_question_index": 0,
        }

    def test_delete_checkin_response(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"deleted": True}

        with patch("httpx.request", return_value=mock_response) as mock_request:
            result: dict[str, Any] = client.delete_checkin_response(
                "followup-uuid",
                response_date="2026-07-01",
            )

        assert result["deleted"] is True
        assert mock_request.call_args[0][0] == "DELETE"
        assert mock_request.call_args[0][1].endswith("/v1/checkins/followup-uuid/responses/")
        assert mock_request.call_args[1]["params"] == {
            "date_start": "2026-07-01",
            "date_end": "2026-07-01",
        }

    def test_track_mood(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"details": "The mood response has been tracked"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.track_mood(5)

        assert "tracked" in result["details"]
        assert mock_post.call_args[0][0].endswith("/v1/mood/track/")
        assert mock_post.call_args[1]["json"] == {"score": 5}

    def test_get_mood(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"motivation": {"score": 4}}

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result: dict[str, Any] = client.get_mood("2026-07-01")

        assert result["motivation"]["score"] == 4
        assert mock_get.call_args[0][0].endswith("/v1/mood/track/")
        assert mock_get.call_args[1]["params"] == {"date": "2026-07-01"}

    def test_list_forms(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [{"uuid": "form-uuid", "name": "Feedback"}]

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result: list[dict[str, Any]] = client.list_forms()

        assert result[0]["uuid"] == "form-uuid"
        assert "Bearer test-token" in mock_get.call_args[1]["headers"]["Authorization"]
        assert mock_get.call_args[1]["params"] == {}

    def test_list_forms_include_archived(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": "form-uuid", "is_archived": True}]

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client.list_forms(include_archived=True)

        assert mock_get.call_args[1]["params"] == {
            "include_archived": "true",
        }

    def test_list_forms_with_questions(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": "form-uuid",
                "name": "Feedback",
                "questions": [{"uuid": "q1", "question": "How was it?"}],
            }
        ]

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result: list[dict[str, Any]] = client.list_forms(include_questions=True)

        assert result[0]["questions"][0]["uuid"] == "q1"
        assert mock_get.call_args[1]["params"] == {
            "include": "questions",
        }

    def test_get_form(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "form-uuid",
            "name": "Feedback",
            "questions": [
                {"uuid": "question-uuid", "question": "How was your week?"},
            ],
        }

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result: dict[str, Any] = client.get_form("form-uuid")

        assert result["id"] == "form-uuid"
        assert mock_get.call_args[0][0].endswith("/v1/forms/form-uuid/")
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

    def test_submit_form_response_automation(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"uuid": "response-uuid"}

        content: dict[str, str] = {"question-uuid": "Yes"}
        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.submit_form_response(
                "form-uuid", content, automation=True
            )

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"] == {"content": content, "automation": True}
        assert result["uuid"] == "response-uuid"

    def test_submit_form_response_anonymous(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"uuid": "response-uuid"}

        content: dict[str, str] = {"question-uuid": "Yes"}
        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.submit_form_response(
                "form-uuid", content, anonymous=True
            )

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"] == {"content": content, "anonymous": True}
        assert result["uuid"] == "response-uuid"

    def test_submit_form_response_both_flags(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"uuid": "response-uuid"}

        content: dict[str, str] = {"question-uuid": "Yes"}
        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.submit_form_response(
                "form-uuid", content, automation=True, anonymous=True
            )

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"] == {
            "content": content,
            "automation": True,
            "anonymous": True,
        }
        assert result["uuid"] == "response-uuid"

    def test_submit_form_response_guest_user(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"uuid": "response-uuid", "is_guest_user": True}

        content: dict[str, str] = {"question-uuid": "Yes"}
        guest: dict[str, str] = {"full_name": "Jane Doe", "email": "jane@example.com"}
        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.submit_form_response(
                "form-uuid",
                content,
                automation=True,
                guest_user=guest,
                submission_source="workflow:deploy",
            )

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"] == {
            "content": content,
            "automation": True,
            "guest_user": guest,
            "submission_source": "workflow:deploy",
        }
        assert result["is_guest_user"] is True

    def test_list_forms_with_filter_and_order(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "count": 1,
            "next": None,
            "previous": None,
            "results": [{"uuid": "f-1", "name": "Form"}],
        }

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client.list_forms(
                filter_scope="workflow",
                order="alphabetical",
                is_ascend=True,
            )

        call_kwargs: dict[str, Any] = mock_get.call_args[1]
        assert call_kwargs["params"]["filter"] == "workflow"
        assert call_kwargs["params"]["order"] == "alphabetical"
        assert call_kwargs["params"]["is_ascend"] == "true"

    def test_list_forms_with_owner_user_ids(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "count": 1,
            "next": None,
            "previous": None,
            "results": [{"uuid": "f-1", "name": "Form"}],
        }

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client.list_forms(
                owner_user_ids=["uuid-1", "uuid-2"],
            )

        call_kwargs: dict[str, Any] = mock_get.call_args[1]
        assert call_kwargs["params"]["owner_user_ids"] == "uuid-1,uuid-2"

    def test_list_form_owners(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "count": 1,
            "next": None,
            "previous": None,
            "results": [
                {"uuid": "u-1", "full_name": "Alice", "role": "admin"},
            ],
        }

        with patch("httpx.get", return_value=mock_response) as mock_get:
            data: dict[str, Any] = client.list_form_owners(search="ali", limit=10)

        call_kwargs: dict[str, Any] = mock_get.call_args[1]
        assert call_kwargs["params"]["search"] == "ali"
        assert call_kwargs["params"]["limit"] == 10
        assert data["results"][0]["full_name"] == "Alice"

    def test_list_form_responses_with_filters(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "count": 1,
            "next": None,
            "previous": None,
            "results": [{"uuid": "r-1"}],
        }

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client.list_form_responses(
                "f-1",
                all_responses=True,
                submission_sources="member,automation",
                flow_status="pending",
                order="oldest",
            )

        call_kwargs: dict[str, Any] = mock_get.call_args[1]
        assert call_kwargs["params"]["all"] == "true"
        assert call_kwargs["params"]["submission_sources"] == "member,automation"
        assert call_kwargs["params"]["flow_status"] == "pending"
        assert call_kwargs["params"]["order"] == "oldest"

    def test_list_users_paginated(self, client: DailyBotClient) -> None:
        first_response: MagicMock = MagicMock(spec=httpx.Response)
        first_response.status_code = 200
        first_response.json.return_value = {
            "results": [{"uuid": "user-1", "full_name": "Jane Doe", "is_active": True}],
            "next": "http://test-api.example.com/v1/users/?page=2",
        }
        second_response: MagicMock = MagicMock(spec=httpx.Response)
        second_response.status_code = 200
        second_response.json.return_value = {
            "results": [{"uuid": "user-2", "full_name": "John Doe", "is_active": True}],
            "next": None,
        }

        with patch("httpx.get", side_effect=[first_response, second_response]) as mock_get:
            result: list[dict[str, Any]] = client.list_users()

        assert len(result) == 2
        assert mock_get.call_count == 2

    def test_list_users_filters_inactive_by_default(self, client: DailyBotClient) -> None:
        page: MagicMock = MagicMock(spec=httpx.Response)
        page.status_code = 200
        page.json.return_value = {
            "results": [
                {"uuid": "u1", "full_name": "Active Alice", "is_active": True},
                {"uuid": "u2", "full_name": "Deactivated Dan", "is_active": False},
                {"uuid": "u3", "full_name": "Missing-flag User"},
            ],
            "next": None,
        }

        with patch("httpx.get", return_value=page):
            result: list[dict[str, Any]] = client.list_users()

        uuids: set[str] = {u["uuid"] for u in result}
        assert "u1" in uuids
        assert "u2" not in uuids  # is_active=False dropped
        assert "u3" in uuids  # missing flag defaults to active for forward-compat

    def test_list_users_include_inactive(self, client: DailyBotClient) -> None:
        page: MagicMock = MagicMock(spec=httpx.Response)
        page.status_code = 200
        page.json.return_value = {
            "results": [
                {"uuid": "u1", "full_name": "Active Alice", "is_active": True},
                {"uuid": "u2", "full_name": "Deactivated Dan", "is_active": False},
            ],
            "next": None,
        }

        with patch("httpx.get", return_value=page):
            result: list[dict[str, Any]] = client.list_users(include_inactive=True)

        assert len(result) == 2

    def test_list_users_include_email_adds_query(self, client: DailyBotClient) -> None:
        page: MagicMock = MagicMock(spec=httpx.Response)
        page.status_code = 200
        page.json.return_value = {"results": [], "next": None}

        with patch("httpx.get", return_value=page) as mock_get:
            client.list_users(include_email=True)

        assert mock_get.call_args[0][0].endswith("/v1/users/?include_email=true")

    def test_list_users_page_cap(self, client: DailyBotClient) -> None:
        """Pagination must stop at _MAX_LIST_PAGES even if the backend keeps returning next."""
        from dailybot_cli.api_client import _MAX_LIST_PAGES

        infinite_page: MagicMock = MagicMock(spec=httpx.Response)
        infinite_page.status_code = 200
        infinite_page.json.return_value = {
            "results": [{"uuid": "user-x"}],
            "next": "http://test-api.example.com/v1/users/?page=999",
        }

        with patch("httpx.get", return_value=infinite_page) as mock_get:
            result: list[dict[str, Any]] = client.list_users()

        assert mock_get.call_count == _MAX_LIST_PAGES
        assert len(result) == _MAX_LIST_PAGES

    def test_give_kudos(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"uuid": "kudos-uuid"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.give_kudos(
                content="Great work!",
                user_uuid_receivers=["user-uuid"],
                company_value="value-uuid",
            )

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert call_kwargs["json"]["receivers"] == ["user-uuid"]
        assert call_kwargs["json"]["users_receivers"] == ["user-uuid"]
        assert "teams_receivers" not in call_kwargs["json"]
        assert call_kwargs["json"]["company_value"] == "value-uuid"
        assert result["uuid"] == "kudos-uuid"

    def test_give_kudos_team(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"uuid": "kudos-uuid"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.give_kudos(
                content="Team shipped it",
                user_uuid_receivers=["user-uuid"],
                team_uuid_receivers=["team-uuid"],
            )

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        # `receivers` merges users+teams; the type-specific lists drive team expansion.
        assert call_kwargs["json"]["receivers"] == ["user-uuid", "team-uuid"]
        assert call_kwargs["json"]["users_receivers"] == ["user-uuid"]
        assert call_kwargs["json"]["teams_receivers"] == ["team-uuid"]

    def test_list_teams(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{"uuid": "team-1", "name": "General"}],
            "next": None,
        }

        with patch("httpx.get", return_value=mock_response) as mock_get:
            teams: list[dict[str, Any]] = client.list_teams()

        assert mock_get.call_count == 1
        assert teams == [{"uuid": "team-1", "name": "General"}]

    def test_get_team(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"uuid": "team-1", "name": "General"}

        with patch("httpx.get", return_value=mock_response) as mock_get:
            data: dict[str, Any] = client.get_team("team-1")

        assert mock_get.call_args[0][0].endswith("/v1/teams/team-1/")
        assert data["name"] == "General"

    def test_list_team_members(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [{"uuid": "user-1", "full_name": "Jane"}]

        with patch("httpx.get", return_value=mock_response) as mock_get:
            members: list[dict[str, Any]] = client.list_team_members("team-1")

        assert mock_get.call_args[0][0].endswith("/v1/teams/team-1/members/")
        assert members[0]["full_name"] == "Jane"

    def test_list_form_responses(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": "r1", "current_state": "qa"},
        ]

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result: list[dict[str, Any]] = client.list_form_responses("form-uuid", state="qa")

        call_kwargs: dict[str, Any] = mock_get.call_args[1]
        assert call_kwargs["params"] == {"state": "qa"}
        assert result[0]["current_state"] == "qa"

    def test_get_form_response(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "r1", "current_state": "pre_release"}

        with patch("httpx.get", return_value=mock_response) as mock_get:
            data: dict[str, Any] = client.get_form_response("form-uuid", "r1")

        assert mock_get.call_args[0][0].endswith("/v1/forms/form-uuid/responses/r1/")
        assert data["id"] == "r1"

    def test_update_form_response(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "r1"}

        with patch("httpx.patch", return_value=mock_response) as mock_patch:
            client.update_form_response("form-uuid", "r1", {"q-uuid": "Updated"})

        call_kwargs: dict[str, Any] = mock_patch.call_args[1]
        assert call_kwargs["json"]["content"] == {"q-uuid": "Updated"}

    def test_transition_form_response(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "r1", "current_state": "qa"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.transition_form_response("form-uuid", "r1", "qa", note="QA assigned")

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert mock_post.call_args[0][0].endswith("/v1/forms/form-uuid/responses/r1/transition/")
        assert call_kwargs["json"] == {"to_state": "qa", "note": "QA assigned"}

    def test_delete_form_response(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 204
        mock_response.json.return_value = {}

        with patch("httpx.request", return_value=mock_response) as mock_request:
            client.delete_form_response("form-uuid", "r1")

        assert mock_request.call_args[0][0] == "DELETE"
        assert mock_request.call_args[0][1].endswith("/v1/forms/form-uuid/responses/r1/")

    def test_api_error_carries_code(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "detail": "Forbidden",
            "code": "form_response_change_state_forbidden",
        }

        from dailybot_cli.api_client import APIError as _APIError

        with patch("httpx.post", return_value=mock_response):
            try:
                client.transition_form_response("form-uuid", "r1", "qa")
            except _APIError as exc:
                assert exc.code == "form_response_change_state_forbidden"
                assert exc.status_code == 403
                return
        raise AssertionError("APIError not raised")

    def test_api_error_429_carries_retry_after(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 429
        mock_response.json.return_value = {"detail": "Request was throttled."}
        mock_response.headers = {"Retry-After": "2"}

        from dailybot_cli.api_client import APIError as _APIError

        with patch("httpx.post", return_value=mock_response):
            try:
                client.create_chat_completion(message="hi")
            except _APIError as exc:
                assert exc.status_code == 429
                assert exc.retry_after == 2.0
                return
        raise AssertionError("APIError not raised")


class TestDailyBotClientAgent:
    def test_submit_agent_report(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 1, "uuid": "abc"}

        with patch("dailybot_cli.api_client.httpx.request", return_value=mock_response) as mock_req:
            result: dict[str, Any] = client.submit_agent_report(
                agent_name="Claude Code",
                content="Deployed v2",
            )

        call_kwargs: dict[str, Any] = mock_req.call_args[1]
        assert call_kwargs["json"]["agent_name"] == "Claude Code"
        assert call_kwargs["headers"]["Authorization"] == "Bearer test-token"
        assert result["id"] == 1

    def test_submit_agent_report_with_milestone(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 2, "is_milestone": True}

        with patch("dailybot_cli.api_client.httpx.request", return_value=mock_response) as mock_req:
            result: dict[str, Any] = client.submit_agent_report(
                agent_name="Claude Code",
                content="Big feature",
                is_milestone=True,
            )

        call_kwargs: dict[str, Any] = mock_req.call_args[1]
        assert call_kwargs["json"]["is_milestone"] is True
        assert result["is_milestone"] is True

    def test_submit_agent_report_with_co_authors(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 3, "co_authors": [{"name": "Alice"}]}

        with patch("dailybot_cli.api_client.httpx.request", return_value=mock_response) as mock_req:
            result: dict[str, Any] = client.submit_agent_report(
                agent_name="Claude Code",
                content="Paired work",
                co_authors=["alice@co.com", "bob@co.com"],
            )

        call_kwargs: dict[str, Any] = mock_req.call_args[1]
        assert call_kwargs["json"]["co_authors"] == ["alice@co.com", "bob@co.com"]
        assert result["co_authors"] == [{"name": "Alice"}]

    def test_submit_agent_report_defaults_omit_new_fields(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 4}

        with patch("dailybot_cli.api_client.httpx.request", return_value=mock_response) as mock_req:
            client.submit_agent_report(
                agent_name="Claude Code",
                content="Normal report",
            )

        call_kwargs: dict[str, Any] = mock_req.call_args[1]
        assert "is_milestone" not in call_kwargs["json"]
        assert "co_authors" not in call_kwargs["json"]

    def test_get_agent_messages_paginated_envelope(self, client: DailyBotClient) -> None:
        """Regression: API returns {count, results} envelope — CORE-2260."""
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "count": 1,
            "next": None,
            "previous": None,
            "results": [
                {"id": "msg-1", "content": "hello", "delivered": False},
            ],
        }

        with patch("dailybot_cli.api_client.httpx.request", return_value=mock_response):
            result: list[dict[str, Any]] = client.get_agent_messages(agent_name="Bot")

        assert len(result) == 1
        assert result[0]["id"] == "msg-1"

    def test_get_agent_messages_plain_list(self, client: DailyBotClient) -> None:
        """If the API ever returns a plain list, handle it gracefully."""
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": "msg-1", "content": "hello"},
        ]

        with patch("dailybot_cli.api_client.httpx.request", return_value=mock_response):
            result: list[dict[str, Any]] = client.get_agent_messages(agent_name="Bot")

        assert len(result) == 1
        assert result[0]["id"] == "msg-1"

    def test_get_agent_messages_empty_envelope(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "count": 0,
            "next": None,
            "previous": None,
            "results": [],
        }

        with patch("dailybot_cli.api_client.httpx.request", return_value=mock_response):
            result: list[dict[str, Any]] = client.get_agent_messages(agent_name="Bot")

        assert result == []


class TestDailyBotClientChat:
    def test_send_chat_message_passes_payload_through(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"bot_message_id": "123"}

        payload: dict[str, Any] = {
            "message": "Deploy finished",
            "target_channels": ["C0123"],
            "platform_settings": {"bot_username": "Release Bot"},
        }
        with patch("dailybot_cli.api_client.httpx.request", return_value=mock_response) as mock_req:
            result: dict[str, Any] = client.send_chat_message(payload)

        call_kwargs: dict[str, Any] = mock_req.call_args[1]
        assert mock_req.call_args[0][1] == "http://test-api.example.com/v1/send-message/"
        assert call_kwargs["json"] == payload
        assert call_kwargs["headers"]["Authorization"] == "Bearer test-token"
        assert result["bot_message_id"] == "123"

    def test_send_chat_message_returns_update_id(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"bot_message_id": "task-uuid"}

        with patch("dailybot_cli.api_client.httpx.request", return_value=mock_response) as mock_req:
            result: dict[str, Any] = client.send_chat_message(
                {"bot_message_id": "task-uuid", "message": "DONE", "target_channels": ["C0"]}
            )

        assert mock_req.call_args[1]["json"]["bot_message_id"] == "task-uuid"
        assert result["bot_message_id"] == "task-uuid"


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
        mock_response.headers = {"content-type": "text/plain"}

        with patch("httpx.post", return_value=mock_response), pytest.raises(APIError) as exc_info:
            client.request_code("user@example.com")

        assert exc_info.value.status_code == 500
        assert "Internal Server Error" in exc_info.value.detail


class TestAgentDualAuth:
    def test_agent_headers_prefers_bearer_over_api_key(self) -> None:
        """Unified priority: Bearer first, API key second — same as _headers()."""
        client = DailyBotClient(api_url="http://test.com", token="tok", api_key="key123")
        headers = client._agent_headers()
        assert headers["Authorization"] == "Bearer tok"
        assert "X-API-KEY" not in headers
        assert client._agent_auth_mode == "bearer"

    def test_agent_headers_falls_back_to_api_key(self) -> None:
        client = DailyBotClient(api_url="http://test.com", token=None, api_key="key123")
        headers = client._agent_headers()
        assert headers["X-API-KEY"] == "key123"
        assert "Authorization" not in headers
        assert client._agent_auth_mode == "api_key"

    def test_agent_headers_bearer_only(self) -> None:
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
        client = DailyBotClient(api_url="http://test.com", token=None, api_key="key123")
        client._agent_headers()  # sets _agent_auth_mode to "api_key"

        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.json.return_value = {"detail": "Invalid API key"}

        with pytest.raises(APIError) as exc_info:
            client._handle_response(mock_response)

        assert exc_info.value.detail == "Invalid API key"


class TestAgentAuthFallback:
    """On 401, _agent_request retries with the alternative credential."""

    def test_bearer_rejected_retries_with_api_key(self) -> None:
        """Primary Bearer fails → retry with API key."""
        client = DailyBotClient(
            api_url="http://test.com", token="expired-token", api_key="valid-key"
        )
        rejected: MagicMock = MagicMock(spec=httpx.Response)
        rejected.status_code = 401
        rejected.json.return_value = {"detail": "Unauthorized"}

        success: MagicMock = MagicMock(spec=httpx.Response)
        success.status_code = 200
        success.json.return_value = {"id": 1, "uuid": "abc"}

        with patch(
            "dailybot_cli.api_client.httpx.request", side_effect=[rejected, success]
        ) as mock_req:
            result: dict[str, Any] = client.submit_agent_report(
                agent_name="Test Agent", content="Hello"
            )

        assert result == {"id": 1, "uuid": "abc"}
        assert mock_req.call_count == 2
        first_headers: dict[str, str] = mock_req.call_args_list[0][1]["headers"]
        assert first_headers.get("Authorization") == "Bearer expired-token"
        retry_headers: dict[str, str] = mock_req.call_args_list[1][1]["headers"]
        assert retry_headers.get("X-API-KEY") == "valid-key"
        assert "Authorization" not in retry_headers

    def test_api_key_rejected_retries_with_bearer(self) -> None:
        """API-key-only client (no Bearer) fails → no retry. But if Bearer
        is added later (e.g. only api_key set at init), retry would work."""
        client = DailyBotClient(api_url="http://test.com", token=None, api_key="stale-key")
        rejected: MagicMock = MagicMock(spec=httpx.Response)
        rejected.status_code = 401
        rejected.json.return_value = {"detail": "API Key Not Valid"}

        with (
            patch("dailybot_cli.api_client.httpx.request", return_value=rejected) as mock_req,
            pytest.raises(APIError) as exc_info,
        ):
            client.submit_agent_report(agent_name="Test", content="Hi")

        assert exc_info.value.status_code == 401
        assert mock_req.call_count == 1

    def test_no_retry_on_non_401_errors(self) -> None:
        client = DailyBotClient(api_url="http://test.com", token="valid-token", api_key="key")
        forbidden: MagicMock = MagicMock(spec=httpx.Response)
        forbidden.status_code = 403
        forbidden.json.return_value = {"detail": "Forbidden"}

        with (
            patch("dailybot_cli.api_client.httpx.request", return_value=forbidden) as mock_req,
            pytest.raises(APIError) as exc_info,
        ):
            client.submit_agent_report(agent_name="Test", content="Hi")

        assert exc_info.value.status_code == 403
        assert mock_req.call_count == 1

    def test_no_retry_when_only_one_credential(self) -> None:
        """Bearer-only client: no alternative credential → no retry."""
        client = DailyBotClient(api_url="http://test.com", token="expired-token", api_key=None)
        rejected: MagicMock = MagicMock(spec=httpx.Response)
        rejected.status_code = 401
        rejected.json.return_value = {"detail": "Unauthorized"}

        with (
            patch("dailybot_cli.api_client.httpx.request", return_value=rejected) as mock_req,
            pytest.raises(APIError) as exc_info,
        ):
            client.submit_agent_report(agent_name="Test", content="Hi")

        assert mock_req.call_count == 1
        assert "Session expired" in exc_info.value.detail

    def test_fallback_works_for_agent_health(self) -> None:
        client = DailyBotClient(
            api_url="http://test.com", token="expired-token", api_key="valid-key"
        )
        rejected: MagicMock = MagicMock(spec=httpx.Response)
        rejected.status_code = 401

        success: MagicMock = MagicMock(spec=httpx.Response)
        success.status_code = 200
        success.json.return_value = {"ok": True}

        with patch("dailybot_cli.api_client.httpx.request", side_effect=[rejected, success]):
            result: dict[str, Any] = client.submit_agent_health(agent_name="Test", ok=True)

        assert result == {"ok": True}

    def test_both_credentials_available_bearer_goes_first(self) -> None:
        """When both credentials exist, Bearer is tried first (unified priority)."""
        client = DailyBotClient(api_url="http://test.com", token="good-token", api_key="good-key")
        success: MagicMock = MagicMock(spec=httpx.Response)
        success.status_code = 200
        success.json.return_value = {"id": 1}

        with patch("dailybot_cli.api_client.httpx.request", return_value=success) as mock_req:
            client.submit_agent_report(agent_name="Test", content="Hi")

        assert mock_req.call_count == 1
        headers: dict[str, str] = mock_req.call_args[1]["headers"]
        assert headers.get("Authorization") == "Bearer good-token"
        assert "X-API-KEY" not in headers


class TestHeadersDualAuth:
    def test_headers_sends_api_key_when_no_token(self) -> None:
        """_headers() sends X-API-KEY when no Bearer token is available."""
        client = DailyBotClient(api_key="test-key", token=None)
        headers = client._headers()
        assert headers["X-API-KEY"] == "test-key"
        assert "Authorization" not in headers

    def test_headers_prefers_bearer_over_api_key(self) -> None:
        """_headers() sends Bearer when both token and api_key are set."""
        client = DailyBotClient(api_key="test-key", token="test-token")
        headers = client._headers()
        assert headers["Authorization"] == "Bearer test-token"
        assert "X-API-KEY" not in headers

    def test_headers_unauthenticated_sends_neither(self) -> None:
        """_headers(authenticated=False) sends no auth."""
        client = DailyBotClient(api_key="test-key", token="test-token")
        headers = client._headers(authenticated=False)
        assert "Authorization" not in headers
        assert "X-API-KEY" not in headers


class TestDailyBotClientCheckinsExtended:
    def test_list_checkins_sends_summary_params(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [], "next": None}

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client.list_checkins(date="2026-07-01", include_summary=True)

        call_kwargs: dict[str, Any] = mock_get.call_args[1]
        assert call_kwargs["params"] == {"date": "2026-07-01", "include_summary": "true"}

    def test_list_checkins_include_archived(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [], "next": None}

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client.list_checkins(include_archived=True)

        assert mock_get.call_args[1]["params"] == {"include_archived": "true"}

    def test_delete_checkin_response_uses_date_range(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"deleted": True, "deleted_count": 1}

        with patch("httpx.request", return_value=mock_response) as mock_request:
            result: dict[str, Any] = client.delete_checkin_response(
                "followup-uuid", response_date="2026-07-01"
            )

        call_kwargs: dict[str, Any] = mock_request.call_args[1]
        assert call_kwargs["params"] == {"date_start": "2026-07-01", "date_end": "2026-07-01"}
        assert result["deleted_count"] == 1


class TestFormsAuthoring:
    def test_list_report_channels(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"uuid": "chan-1", "name": "#engineering", "platform": "slack"},
        ]

        with patch("httpx.get", return_value=mock_response) as mock_get:
            result: list[dict[str, Any]] = client.list_report_channels()

        assert mock_get.call_args[0][0].endswith("/v1/report-channels/")
        assert result[0]["uuid"] == "chan-1"
        assert "Bearer test-token" in mock_get.call_args[1]["headers"]["Authorization"]

    def test_list_report_channels_unwraps_results(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [{"uuid": "chan-1"}]}

        with patch("httpx.get", return_value=mock_response):
            result: list[dict[str, Any]] = client.list_report_channels()

        assert result == [{"uuid": "chan-1"}]

    def test_list_report_channels_unwraps_channels_key(self, client: DailyBotClient) -> None:
        # The live endpoint returns {"channels": [...], "total": N}.
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "channels": [
                {"id": "C04C1GL9RH8", "name": "general", "platform": "slack", "type": "channel"},
            ],
            "total": 1,
        }

        with patch("httpx.get", return_value=mock_response):
            result: list[dict[str, Any]] = client.list_report_channels()

        assert len(result) == 1
        assert result[0]["id"] == "C04C1GL9RH8"
        assert result[0]["name"] == "general"

    def test_create_form_with_questions(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "form-uuid", "name": "Retro"}

        questions: list[dict[str, Any]] = [
            {"question_type": "text", "question": "What went well?"},
        ]
        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.create_form("Retro", questions)

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert mock_post.call_args[0][0].endswith("/v1/forms/create/")
        assert call_kwargs["json"] == {"name": "Retro", "questions": questions}
        assert result["id"] == "form-uuid"

    def test_create_form_omits_empty_questions(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "form-uuid"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.create_form("Retro")

        assert mock_post.call_args[1]["json"] == {"name": "Retro"}

    def test_create_form_merges_config(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "form-uuid"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.create_form("Retro", config={"is_anonymous": True, "command": "retro"})

        assert mock_post.call_args[1]["json"] == {
            "name": "Retro",
            "is_anonymous": True,
            "command": "retro",
        }

    def test_update_form_config_merges_config(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "form-uuid"}

        with patch("httpx.patch", return_value=mock_response) as mock_patch:
            client.update_form_config("form-uuid", config={"workflow": {"enabled": False}})

        assert mock_patch.call_args[1]["json"] == {"workflow": {"enabled": False}}

    def test_create_form_with_report_channels_inline(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "form-uuid"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.create_form("Retro", report_channels=["chan-1", "chan-2"])

        assert mock_post.call_args[1]["json"] == {
            "name": "Retro",
            "report_channels": ["chan-1", "chan-2"],
        }

    def test_update_form_config(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "form-uuid", "name": "Renamed"}

        with patch("httpx.patch", return_value=mock_response) as mock_patch:
            client.update_form_config("form-uuid", name="Renamed", report_channels=["chan-1"])

        call_kwargs: dict[str, Any] = mock_patch.call_args[1]
        assert mock_patch.call_args[0][0].endswith("/v1/forms/form-uuid/config/")
        assert call_kwargs["json"] == {"name": "Renamed", "report_channels": ["chan-1"]}

    def test_update_form_config_sends_only_provided_fields(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "form-uuid"}

        with patch("httpx.patch", return_value=mock_response) as mock_patch:
            client.update_form_config("form-uuid", name="Only name")

        assert mock_patch.call_args[1]["json"] == {"name": "Only name"}

    def test_archive_form(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 204
        mock_response.json.return_value = {}

        with patch("httpx.request", return_value=mock_response) as mock_request:
            result: dict[str, Any] = client.archive_form("form-uuid")

        assert mock_request.call_args[0][0] == "DELETE"
        assert mock_request.call_args[0][1].endswith("/v1/forms/form-uuid/archive/")
        assert result == {}

    def test_add_form_question(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"uuid": "q-new"}

        question: dict[str, Any] = {"question_type": "numeric", "question": "1-10?"}
        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.add_form_question("form-uuid", question)

        assert mock_post.call_args[0][0].endswith("/v1/forms/form-uuid/questions/")
        assert mock_post.call_args[1]["json"] == question
        assert result["uuid"] == "q-new"

    def test_update_form_question(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"uuid": "q1"}

        with patch("httpx.patch", return_value=mock_response) as mock_patch:
            client.update_form_question("form-uuid", "q1", {"question": "New text?"})

        assert mock_patch.call_args[0][0].endswith("/v1/forms/form-uuid/questions/q1/")
        assert mock_patch.call_args[1]["json"] == {"question": "New text?"}

    def test_delete_form_question(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 204
        mock_response.json.return_value = {}

        with patch("httpx.request", return_value=mock_response) as mock_request:
            client.delete_form_question("form-uuid", "q1")

        assert mock_request.call_args[0][0] == "DELETE"
        assert mock_request.call_args[0][1].endswith("/v1/forms/form-uuid/questions/q1/delete/")

    def test_reorder_form_questions(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"reordered": True}

        with patch("httpx.put", return_value=mock_response) as mock_put:
            client.reorder_form_questions("form-uuid", ["q2", "q1"])

        assert mock_put.call_args[0][0].endswith("/v1/forms/form-uuid/questions/reorder/")
        assert mock_put.call_args[1]["json"] == {"question_uuids": ["q2", "q1"]}

    def test_list_form_responses_admin_filters(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": "r1"}]

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client.list_form_responses(
                "form-uuid",
                all_responses=True,
                user="user-uuid",
                date_from="2026-01-01",
                date_to="2026-12-31",
            )

        assert mock_get.call_args[1]["params"] == {
            "all": "true",
            "user": "user-uuid",
            "date_from": "2026-01-01",
            "date_to": "2026-12-31",
        }

    def test_archive_form_raises_api_error_with_code(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 403
        mock_response.json.return_value = {"detail": "Forbidden", "code": "form_edit_forbidden"}

        with (
            patch("httpx.request", return_value=mock_response),
            pytest.raises(APIError) as exc_info,
        ):
            client.archive_form("form-uuid")

        assert exc_info.value.code == "form_edit_forbidden"
        assert exc_info.value.status_code == 403


class TestCheckinsAuthoring:
    def test_create_checkin(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "followup-uuid", "name": "Standup"}

        schedule: dict[str, Any] = {"days": [1, 2, 3], "time": "09:00", "timezone": "UTC"}
        participants: dict[str, Any] = {"user_uuids": ["u1"], "team_uuids": []}
        questions: list[dict[str, Any]] = [{"question_type": "text", "question": "Yesterday?"}]
        with patch("httpx.post", return_value=mock_response) as mock_post:
            result: dict[str, Any] = client.create_checkin(
                "Standup",
                schedule=schedule,
                participants=participants,
                questions=questions,
                report_channels=["chan-1"],
            )

        call_kwargs: dict[str, Any] = mock_post.call_args[1]
        assert mock_post.call_args[0][0].endswith("/v1/checkins/create/")
        assert call_kwargs["json"] == {
            "name": "Standup",
            "schedule": schedule,
            "participants": participants,
            "questions": questions,
            "report_channels": ["chan-1"],
        }
        assert result["id"] == "followup-uuid"

    def test_create_checkin_minimal(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "followup-uuid"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.create_checkin("Standup")

        assert mock_post.call_args[1]["json"] == {"name": "Standup"}

    def test_create_checkin_merges_config(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "followup-uuid"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.create_checkin(
                "Standup", config={"reminders_max_count": 3, "frequency_type": "weekly"}
            )

        assert mock_post.call_args[1]["json"] == {
            "name": "Standup",
            "reminders_max_count": 3,
            "frequency_type": "weekly",
        }

    def test_create_checkin_sends_generate_short_question(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "followup-uuid"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.create_checkin("Standup", generate_short_question=True)

        assert mock_post.call_args[1]["json"]["generate_short_question"] is True

    def test_create_checkin_omits_generate_short_question_by_default(
        self, client: DailyBotClient
    ) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "followup-uuid"}

        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.create_checkin("Standup")

        assert "generate_short_question" not in mock_post.call_args[1]["json"]

    def test_update_checkin_config_sends_is_active_false(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "followup-uuid", "is_active": False}

        with patch("httpx.patch", return_value=mock_response) as mock_patch:
            client.update_checkin_config("followup-uuid", is_active=False)

        assert mock_patch.call_args[0][0].endswith("/v1/checkins/followup-uuid/config/")
        assert mock_patch.call_args[1]["json"] == {"is_active": False}

    def test_update_checkin_config_partial(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "followup-uuid"}

        with patch("httpx.patch", return_value=mock_response) as mock_patch:
            client.update_checkin_config("followup-uuid", name="Renamed")

        assert mock_patch.call_args[1]["json"] == {"name": "Renamed"}

    def test_update_checkin_config_sends_participants(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "followup-uuid"}

        with patch("httpx.patch", return_value=mock_response) as mock_patch:
            client.update_checkin_config("followup-uuid", participants={"team_uuids": ["t-1"]})

        assert mock_patch.call_args[1]["json"] == {"participants": {"team_uuids": ["t-1"]}}

    def test_update_checkin_config_merges_config(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "followup-uuid"}

        with patch("httpx.patch", return_value=mock_response) as mock_patch:
            client.update_checkin_config(
                "followup-uuid", config={"reminders_max_count": 2, "allow_past_responses": False}
            )

        assert mock_patch.call_args[1]["json"] == {
            "reminders_max_count": 2,
            "allow_past_responses": False,
        }

    def test_archive_checkin(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 204
        mock_response.json.return_value = {}

        with patch("httpx.request", return_value=mock_response) as mock_request:
            result: dict[str, Any] = client.archive_checkin("followup-uuid")

        assert mock_request.call_args[0][0] == "DELETE"
        assert mock_request.call_args[0][1].endswith("/v1/checkins/followup-uuid/archive/")
        assert result == {}

    def test_add_checkin_question(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"uuid": "q-new"}

        question: dict[str, Any] = {"question_type": "boolean", "question": "Blockers?"}
        with patch("httpx.post", return_value=mock_response) as mock_post:
            client.add_checkin_question("followup-uuid", question)

        assert mock_post.call_args[0][0].endswith("/v1/checkins/followup-uuid/questions/")
        assert mock_post.call_args[1]["json"] == question

    def test_update_checkin_question(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"uuid": "q1"}

        with patch("httpx.patch", return_value=mock_response) as mock_patch:
            client.update_checkin_question("followup-uuid", "q1", {"question": "New?"})

        assert mock_patch.call_args[0][0].endswith("/v1/checkins/followup-uuid/questions/q1/")
        assert mock_patch.call_args[1]["json"] == {"question": "New?"}

    def test_delete_checkin_question(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 204
        mock_response.json.return_value = {}

        with patch("httpx.request", return_value=mock_response) as mock_request:
            client.delete_checkin_question("followup-uuid", "q1")

        assert mock_request.call_args[0][0] == "DELETE"
        assert mock_request.call_args[0][1].endswith(
            "/v1/checkins/followup-uuid/questions/q1/delete/"
        )

    def test_reorder_checkin_questions(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"reordered": True}

        with patch("httpx.put", return_value=mock_response) as mock_put:
            client.reorder_checkin_questions("followup-uuid", ["q2", "q1"])

        assert mock_put.call_args[0][0].endswith("/v1/checkins/followup-uuid/questions/reorder/")
        assert mock_put.call_args[1]["json"] == {"question_uuids": ["q2", "q1"]}

    def test_list_checkin_responses_admin_filters(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [{"uuid": "r1"}]

        with patch("httpx.get", return_value=mock_response) as mock_get:
            client.list_checkin_responses(
                "followup-uuid",
                all_responses=True,
                user="user-uuid",
                date_start="2026-01-01",
                date_end="2026-12-31",
            )

        assert mock_get.call_args[1]["params"] == {
            "date_start": "2026-01-01",
            "date_end": "2026-12-31",
            "all": "true",
            "user": "user-uuid",
        }

    def test_archive_checkin_raises_api_error_with_code(self, client: DailyBotClient) -> None:
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "detail": "Forbidden",
            "code": "checkin_permission_denied",
        }

        with (
            patch("httpx.request", return_value=mock_response),
            pytest.raises(APIError) as exc_info,
        ):
            client.archive_checkin("followup-uuid")

        assert exc_info.value.code == "checkin_permission_denied"
        assert exc_info.value.status_code == 403


class TestSearchQueryValidation:
    """Client-side search query length validation (CORE-2263)."""

    def test_search_query_too_long_raises_api_error(self, client: DailyBotClient) -> None:
        long_query: str = "a" * 257
        with pytest.raises(APIError) as exc_info:
            client.list_forms(search=long_query)
        assert exc_info.value.status_code == 400
        assert exc_info.value.code == "search_query_too_long"

    def test_search_query_at_limit_passes(self, client: DailyBotClient) -> None:
        query_at_limit: str = "a" * 256
        mock_response: MagicMock = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "count": 0,
            "next": None,
            "previous": None,
            "results": [],
        }
        with patch("httpx.get", return_value=mock_response):
            result: list[dict[str, Any]] = client.list_forms(search=query_at_limit)
        assert result == []

    def test_search_query_whitespace_normalized(self, client: DailyBotClient) -> None:
        """Whitespace-padded query exceeding 256 after normalization is rejected."""
        padded_query: str = "a " * 200
        with pytest.raises(APIError) as exc_info:
            client.list_forms(search=padded_query)
        assert exc_info.value.code == "search_query_too_long"


class TestPaginatedGet:
    """Unit tests for the shared _paginated_get helper (Task 1)."""

    def _resp(self, body: Any, status: int = 200) -> MagicMock:
        r: MagicMock = MagicMock(spec=httpx.Response)
        r.status_code = status
        r.json.return_value = body
        return r

    def test_envelope_parsing(self, client: DailyBotClient) -> None:
        page = self._resp(
            {
                "count": 2,
                "next": None,
                "previous": None,
                "results": [{"id": "a"}, {"id": "b"}],
            }
        )
        with patch("httpx.get", return_value=page):
            result = client._paginated_get("http://test-api.example.com/v1/things/")
        assert [r["id"] for r in result.results] == ["a", "b"]
        assert result.count == 2
        assert result.next is None
        assert result.previous is None

    def test_bare_list_fallback(self, client: DailyBotClient) -> None:
        page = self._resp([{"id": "a"}, {"id": "b"}, {"id": "c"}])
        with patch("httpx.get", return_value=page):
            result = client._paginated_get("http://test-api.example.com/v1/things/")
        assert len(result.results) == 3
        assert result.count == 3
        assert result.next is None

    def test_forms_no_longer_request_the_envelope(self, client: DailyBotClient) -> None:
        """Every /v1 list endpoint returns the envelope unconditionally now."""
        page = self._resp({"count": 0, "next": None, "results": []})
        with patch("httpx.get", return_value=page) as mock_get:
            client.list_forms()
        assert "paginated" not in mock_get.call_args[1]["params"]

    def test_no_paginated_param_by_default(self, client: DailyBotClient) -> None:
        page = self._resp({"count": 0, "next": None, "results": []})
        with patch("httpx.get", return_value=page) as mock_get:
            client._paginated_get("http://test-api.example.com/v1/checkins/")
        assert "paginated" not in mock_get.call_args[1]["params"]

    def test_page_size_clamped_to_max(self, client: DailyBotClient) -> None:
        page = self._resp({"count": 0, "next": None, "results": []})
        with patch("httpx.get", return_value=page) as mock_get:
            client._paginated_get("http://test-api.example.com/v1/things/", page_size=999)
        assert mock_get.call_args[1]["params"]["page_size"] == 100

    def test_fetch_all_iterates_next(self, client: DailyBotClient) -> None:
        first = self._resp(
            {
                "count": 3,
                "next": "http://test-api.example.com/v1/things/?page=2",
                "results": [{"id": "a"}, {"id": "b"}],
            }
        )
        second = self._resp({"count": 3, "next": None, "results": [{"id": "c"}]})
        with patch("httpx.get", side_effect=[first, second]) as mock_get:
            result = client._paginated_get("http://test-api.example.com/v1/things/", fetch_all=True)
        assert [r["id"] for r in result.results] == ["a", "b", "c"]
        assert mock_get.call_count == 2

    def test_single_page_mode_stops_after_one_request(self, client: DailyBotClient) -> None:
        page = self._resp(
            {
                "count": 9,
                "next": "http://test-api.example.com/v1/things/?page=2",
                "results": [{"id": "a"}],
            }
        )
        with patch("httpx.get", return_value=page) as mock_get:
            result = client._paginated_get(
                "http://test-api.example.com/v1/things/", fetch_all=False
            )
        assert mock_get.call_count == 1
        assert len(result.results) == 1
        assert result.next == "http://test-api.example.com/v1/things/?page=2"

    def test_limit_caps_total_collected(self, client: DailyBotClient) -> None:
        first = self._resp(
            {
                "count": 100,
                "next": "http://test-api.example.com/v1/things/?page=2",
                "results": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            }
        )
        with patch("httpx.get", return_value=first) as mock_get:
            result = client._paginated_get(
                "http://test-api.example.com/v1/things/", fetch_all=True, limit=2
            )
        assert len(result.results) == 2
        assert mock_get.call_count == 1


class TestErrorCodesAndRateLimits:
    """Task 2: APIError code/extra parsing and 429 retry behavior."""

    def _resp(
        self,
        status: int,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> MagicMock:
        r: MagicMock = MagicMock(spec=httpx.Response)
        r.status_code = status
        r.json.return_value = {} if body is None else body
        r.headers = headers or {}
        return r

    def test_api_error_parses_code_extra_and_upgrade_url(self, client: DailyBotClient) -> None:
        resp = self._resp(
            403,
            {
                "detail": "nope",
                "code": "plan_upgrade_required",
                "upgrade_url": "https://app.example.com/upgrade",
                "extra": {"required_role": "admin"},
            },
        )
        with pytest.raises(APIError) as excinfo:
            client._handle_response(resp)
        err = excinfo.value
        assert err.code == "plan_upgrade_required"
        assert err.extra["upgrade_url"] == "https://app.example.com/upgrade"
        assert err.extra["required_role"] == "admin"

    def test_api_error_without_code_is_none(self, client: DailyBotClient) -> None:
        resp = self._resp(400, {"detail": "bad request"})
        with pytest.raises(APIError) as excinfo:
            client._handle_response(resp)
        assert excinfo.value.code is None
        assert excinfo.value.extra == {}

    def test_no_retry_on_free_plan_daily_limit(self, client: DailyBotClient) -> None:
        resp = self._resp(429, {"code": "free_plan_daily_limit_exceeded"})
        send = MagicMock(return_value=resp)
        with patch("dailybot_cli.api_client.time.sleep") as sleep:
            out = client._send_with_retry(send)
        assert send.call_count == 1
        assert sleep.call_count == 0
        assert out is resp

    def test_generic_429_retries_then_returns(self, client: DailyBotClient) -> None:
        from dailybot_cli.api_client import MAX_RATE_LIMIT_RETRIES

        resp = self._resp(429, {"code": "rate_limited"}, {"Retry-After": "1"})
        send = MagicMock(return_value=resp)
        with patch("dailybot_cli.api_client.time.sleep") as sleep:
            out = client._send_with_retry(send)
        # 1 initial attempt + MAX_RATE_LIMIT_RETRIES retries
        assert send.call_count == 1 + MAX_RATE_LIMIT_RETRIES
        assert sleep.call_count == MAX_RATE_LIMIT_RETRIES
        assert out.status_code == 429

    def test_success_after_one_retry(self, client: DailyBotClient) -> None:
        limited = self._resp(429, {"code": "rate_limited"}, {"Retry-After": "1"})
        ok = self._resp(200, {"results": []})
        send = MagicMock(side_effect=[limited, ok])
        with patch("dailybot_cli.api_client.time.sleep") as sleep:
            out = client._send_with_retry(send)
        assert send.call_count == 2
        assert sleep.call_count == 1
        assert out.status_code == 200
