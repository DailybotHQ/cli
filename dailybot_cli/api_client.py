"""HTTP client for Dailybot CLI API endpoints."""

from typing import Any

import httpx

from dailybot_cli.config import get_api_key, get_api_url, get_token

_MAX_LIST_PAGES: int = 50  # safety cap for paginated list endpoints


class APIError(Exception):
    """Raised when the API returns a non-success response."""

    def __init__(self, status_code: int, detail: str, code: str | None = None) -> None:
        self.status_code: int = status_code
        self.detail: str = detail
        self.code: str | None = code
        super().__init__(f"API error {status_code}: {detail}")


class DailyBotClient:
    """HTTP client for the Dailybot /v1/cli/* API endpoints."""

    def __init__(
        self,
        api_url: str | None = None,
        token: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_url: str = (api_url or get_api_url()).rstrip("/")
        self.token: str | None = token or get_token()
        self.api_key: str | None = api_key or get_api_key()
        self.timeout: float = timeout
        self._agent_auth_mode: str | None = None

    def _headers(self, authenticated: bool = True) -> dict[str, str]:
        """Build request headers."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if authenticated and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _agent_headers(self) -> dict[str, str]:
        """Build headers for agent authentication (API key preferred, then Bearer)."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
            self._agent_auth_mode = "api_key"
        elif self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            self._agent_auth_mode = "bearer"
        else:
            self._agent_auth_mode = None
        return headers

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Parse API response and raise on errors."""
        if response.status_code >= 400:
            code: str | None = None
            try:
                body: dict[str, Any] = response.json()
                detail: str = body.get("detail", body.get("error", str(body)))
                raw_code: Any = body.get("code")
                if isinstance(raw_code, str):
                    code = raw_code
            except Exception:
                detail = response.text or f"HTTP {response.status_code}"
            if response.status_code in (401, 403) and self._agent_auth_mode == "bearer":
                detail = "Session expired. Run 'dailybot login' to re-authenticate."
            raise APIError(status_code=response.status_code, detail=detail, code=code)
        if response.status_code == 204:
            return {}
        return response.json()

    # --- Auth endpoints ---

    def request_code(self, email: str) -> dict[str, Any]:
        """POST /v1/cli/auth/request-code/"""
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/cli/auth/request-code/",
            json={"email": email},
            headers=self._headers(authenticated=False),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def verify_code(
        self,
        email: str,
        code: str,
        organization_id: int | None = None,
    ) -> dict[str, Any]:
        """POST /v1/cli/auth/verify-code/"""
        payload: dict[str, Any] = {"email": email, "code": code}
        if organization_id is not None:
            payload["organization_id"] = organization_id
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/cli/auth/verify-code/",
            json=payload,
            headers=self._headers(authenticated=False),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def auth_status(self) -> dict[str, Any]:
        """GET /v1/cli/auth/status/"""
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/cli/auth/status/",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def logout(self) -> dict[str, Any]:
        """POST /v1/cli/auth/logout/"""
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/cli/auth/logout/",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    # --- Update/Status endpoints ---

    def submit_update(
        self,
        message: str | None = None,
        done: str | None = None,
        doing: str | None = None,
        blocked: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/cli/updates/"""
        payload: dict[str, str] = {}
        if message:
            payload["message"] = message
        if done:
            payload["done"] = done
        if doing:
            payload["doing"] = doing
        if blocked:
            payload["blocked"] = blocked
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/cli/updates/",
            json=payload,
            headers=self._headers(),
            timeout=120.0,
        )
        return self._handle_response(response)

    def get_status(self) -> dict[str, Any]:
        """GET /v1/cli/status/"""
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/cli/status/",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    # --- User-scoped public API endpoints (Bearer token) ---

    def complete_checkin(
        self,
        followup_uuid: str,
        responses: list[dict[str, Any]],
        last_question_index: int | None = None,
        response_date: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/checkins/<followup_uuid>/responses/"""
        payload: dict[str, Any] = {"responses": responses}
        if last_question_index is not None:
            payload["last_question_index"] = last_question_index
        if response_date:
            payload["response_date"] = response_date
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/checkins/{followup_uuid}/responses/",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def list_forms(self, *, include_questions: bool = False) -> list[dict[str, Any]]:
        """GET /v1/forms/ — optionally expand question definitions per form."""
        params: dict[str, str] = {"include": "questions"} if include_questions else {}
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/forms/",
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            self._handle_response(response)
        return response.json()

    def get_form(self, form_uuid: str) -> dict[str, Any]:
        """GET /v1/forms/<form_uuid>/ — form metadata and question definitions."""
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/forms/{form_uuid}/",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def submit_form_response(
        self,
        form_uuid: str,
        content: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /v1/forms/<form_uuid>/responses/"""
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/forms/{form_uuid}/responses/",
            json={"content": content},
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def list_form_responses(
        self,
        form_uuid: str,
        *,
        state: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/forms/<form_uuid>/responses/ — list the caller's own responses."""
        params: dict[str, str] = {}
        if state:
            params["state"] = state
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/forms/{form_uuid}/responses/",
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            self._handle_response(response)
        body: Any = response.json()
        if isinstance(body, dict) and "results" in body:
            return list(body.get("results", []))
        if isinstance(body, list):
            return body
        return []

    def get_form_response(
        self,
        form_uuid: str,
        response_uuid: str,
    ) -> dict[str, Any]:
        """GET /v1/forms/<form_uuid>/responses/<response_uuid>/"""
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/forms/{form_uuid}/responses/{response_uuid}/",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def update_form_response(
        self,
        form_uuid: str,
        response_uuid: str,
        content: dict[str, Any],
    ) -> dict[str, Any]:
        """PATCH /v1/forms/<form_uuid>/responses/<response_uuid>/"""
        response: httpx.Response = httpx.patch(
            f"{self.api_url}/v1/forms/{form_uuid}/responses/{response_uuid}/",
            json={"content": content},
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def transition_form_response(
        self,
        form_uuid: str,
        response_uuid: str,
        to_state: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/forms/<form_uuid>/responses/<response_uuid>/transition/"""
        payload: dict[str, Any] = {"to_state": to_state}
        if note:
            payload["note"] = note
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/forms/{form_uuid}/responses/{response_uuid}/transition/",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def delete_form_response(
        self,
        form_uuid: str,
        response_uuid: str,
    ) -> dict[str, Any]:
        """DELETE /v1/forms/<form_uuid>/responses/<response_uuid>/"""
        response: httpx.Response = httpx.request(
            "DELETE",
            f"{self.api_url}/v1/forms/{form_uuid}/responses/{response_uuid}/",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def list_users(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        """GET /v1/users/ — fetch all pages and return the combined results list.

        By default returns only members with ``is_active`` truthy. Pass
        ``include_inactive=True`` to get the unfiltered server response (useful
        for admin / audit flows that need to surface deactivated accounts).
        """
        results: list[dict[str, Any]] = []
        url: str | None = f"{self.api_url}/v1/users/"
        pages_fetched: int = 0
        while url is not None and pages_fetched < _MAX_LIST_PAGES:
            response: httpx.Response = httpx.get(
                url,
                headers=self._headers(),
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                self._handle_response(response)
            body: dict[str, Any] = response.json()
            results.extend(body.get("results", []))
            url = body.get("next")
            pages_fetched += 1
        if include_inactive:
            return results
        return [u for u in results if u.get("is_active", True)]

    def give_kudos(
        self,
        content: str,
        user_uuid_receivers: list[str] | None = None,
        team_uuid_receivers: list[str] | None = None,
        company_value: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/kudos/

        At least one of ``user_uuid_receivers`` or ``team_uuid_receivers`` must
        be non-empty — the backend rejects an empty receiver set.
        """
        payload: dict[str, Any] = {"content": content}
        if user_uuid_receivers:
            payload["user_uuid_receivers"] = user_uuid_receivers
        if team_uuid_receivers:
            payload["team_uuid_receivers"] = team_uuid_receivers
        if company_value:
            payload["company_value"] = company_value
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/kudos/",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def list_teams(self) -> list[dict[str, Any]]:
        """GET /v1/teams/ — server scopes results by role (admin sees all, member sees own)."""
        results: list[dict[str, Any]] = []
        url: str | None = f"{self.api_url}/v1/teams/"
        pages_fetched: int = 0
        while url is not None and pages_fetched < _MAX_LIST_PAGES:
            response: httpx.Response = httpx.get(
                url,
                headers=self._headers(),
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                self._handle_response(response)
            body: Any = response.json()
            if isinstance(body, dict) and "results" in body:
                results.extend(body.get("results", []))
                url = body.get("next")
            elif isinstance(body, list):
                results.extend(body)
                url = None
            else:
                url = None
            pages_fetched += 1
        return results

    def get_team(self, team_uuid: str) -> dict[str, Any]:
        """GET /v1/teams/<team_uuid>/"""
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/teams/{team_uuid}/",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def list_team_members(self, team_uuid: str) -> list[dict[str, Any]]:
        """GET /v1/teams/<team_uuid>/members/"""
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/teams/{team_uuid}/members/",
            headers=self._headers(),
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            self._handle_response(response)
        body: Any = response.json()
        if isinstance(body, dict) and "results" in body:
            return list(body.get("results", []))
        if isinstance(body, list):
            return body
        return []

    # --- Agent endpoints ---

    def submit_agent_report(
        self,
        agent_name: str,
        content: str,
        structured: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        is_milestone: bool = False,
        co_authors: list[str] | None = None,
    ) -> dict[str, Any]:
        """POST /v1/agent-reports/"""
        payload: dict[str, Any] = {
            "agent_name": agent_name,
            "content": content,
        }
        if structured:
            payload["structured"] = structured
        if metadata:
            payload["metadata"] = metadata
        if is_milestone:
            payload["is_milestone"] = True
        if co_authors:
            payload["co_authors"] = co_authors
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/agent-reports/",
            json=payload,
            headers=self._agent_headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def submit_agent_health(
        self,
        agent_name: str,
        ok: bool,
        message: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/agent-health/"""
        payload: dict[str, Any] = {
            "agent_name": agent_name,
            "ok": ok,
        }
        if message:
            payload["message"] = message
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/agent-health/",
            json=payload,
            headers=self._agent_headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def get_agent_health(self, agent_name: str) -> dict[str, Any]:
        """GET /v1/agent-health/?agent_name=..."""
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/agent-health/",
            params={"agent_name": agent_name},
            headers=self._agent_headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    # --- Agent webhook endpoints ---

    def register_agent_webhook(
        self,
        agent_name: str,
        webhook_url: str,
        webhook_secret: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/agent-webhook/"""
        payload: dict[str, Any] = {
            "agent_name": agent_name,
            "webhook_url": webhook_url,
        }
        if webhook_secret:
            payload["webhook_secret"] = webhook_secret
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/agent-webhook/",
            json=payload,
            headers=self._agent_headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def unregister_agent_webhook(self, agent_name: str) -> dict[str, Any]:
        """DELETE /v1/agent-webhook/"""
        response: httpx.Response = httpx.request(
            "DELETE",
            f"{self.api_url}/v1/agent-webhook/",
            json={"agent_name": agent_name},
            headers=self._agent_headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    # --- Agent email endpoints ---

    def send_agent_email(
        self,
        agent_name: str,
        to: list[str],
        subject: str,
        body_html: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /v1/agent-email/send/"""
        payload: dict[str, Any] = {
            "agent_name": agent_name,
            "to": to,
            "subject": subject,
            "body_html": body_html,
        }
        if metadata:
            payload["metadata"] = metadata
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/agent-email/send/",
            json=payload,
            headers=self._agent_headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    # --- Chat platform messaging (send-message) ---

    def send_chat_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /v1/send-message/ — send a Dailybot bot message to the chat platform.

        Delivers to users (DM), channels, and/or teams on the org's connected
        chat platform (Slack/Teams/Discord/Google Chat). Authenticated via the
        shared agent header logic: an org API key (``X-API-KEY``) is preferred,
        otherwise the login Bearer token is sent (role-scoped to what the caller
        can reach in their org).

        *payload* is passed through to the API verbatim, so every current and
        future request field (``message``, ``messages``, ``image_url``,
        ``buttons``, ``thread_responses``, ``target_users``,
        ``target_channels``, ``target_teams``, ``platform_settings``,
        ``metadata``, ``skip_users_on_time_off``, ``bot_message_id``, …) is
        supported without changing this method. The caller is responsible for
        assembling and validating the body.

        Returns the API response, which carries a ``bot_message_id`` for the
        parent and — when ``thread_responses`` was sent — one id per reply, all
        of which can be fed back in a later call to edit the same message.
        """
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/send-message/",
            json=payload,
            headers=self._agent_headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    # --- Agent message endpoints ---

    def send_agent_message(
        self,
        agent_name: str,
        content: str,
        message_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        expires_at: str | None = None,
        sender_type: str | None = None,
        sender_name: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/agent-messages/"""
        payload: dict[str, Any] = {
            "agent_name": agent_name,
            "content": content,
        }
        if message_type:
            payload["message_type"] = message_type
        if metadata:
            payload["metadata"] = metadata
        if expires_at:
            payload["expires_at"] = expires_at
        if sender_type:
            payload["sender_type"] = sender_type
        if sender_name:
            payload["sender_name"] = sender_name
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/agent-messages/",
            json=payload,
            headers=self._agent_headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def get_agent_messages(
        self,
        agent_name: str,
        delivered: bool | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/agent-messages/?agent_name=..."""
        params: dict[str, str] = {"agent_name": agent_name}
        if delivered is not None:
            params["delivered"] = "true" if delivered else "false"
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/agent-messages/",
            params=params,
            headers=self._agent_headers(),
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            self._handle_response(response)
        return response.json()

    def mark_agent_messages_read(
        self,
        message_ids: list[str],
    ) -> dict[str, Any]:
        """PATCH /v1/agent-messages/read/"""
        response: httpx.Response = httpx.patch(
            f"{self.api_url}/v1/agent-messages/read/",
            json={"message_ids": message_ids},
            headers=self._agent_headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    # --- Agent registration endpoints ---

    def get_registration_challenge(self) -> dict[str, Any]:
        """GET /v1/agent/register/challenge/ — no auth required."""
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/agent/register/challenge/",
            headers=self._headers(authenticated=False),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def register_agent(
        self,
        challenge_id: str,
        answer: int,
        reason: str,
        org_name: str,
        agent_name: str,
        contact_email: str | None = None,
        timezone: str = "UTC",
    ) -> dict[str, Any]:
        """POST /v1/agent/register/ — no auth required."""
        payload: dict[str, Any] = {
            "challenge_id": challenge_id,
            "answer": answer,
            "reason": reason,
            "org_name": org_name,
            "agent_name": agent_name,
            "timezone": timezone,
        }
        if contact_email:
            payload["contact_email"] = contact_email
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/agent/register/",
            json=payload,
            headers=self._headers(authenticated=False),
            timeout=self.timeout,
        )
        return self._handle_response(response)
