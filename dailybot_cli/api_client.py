"""HTTP client for Dailybot CLI API endpoints."""

from typing import Any, Optional

import httpx

from dailybot_cli.config import get_api_key, get_api_url, get_token


class APIError(Exception):
    """Raised when the API returns a non-success response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code: int = status_code
        self.detail: str = detail
        super().__init__(f"API error {status_code}: {detail}")


class DailyBotClient:
    """HTTP client for the Dailybot /v1/cli/* API endpoints."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        token: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_url: str = (api_url or get_api_url()).rstrip("/")
        self.token: Optional[str] = token or get_token()
        self.api_key: Optional[str] = api_key or get_api_key()
        self.timeout: float = timeout
        self._agent_auth_mode: Optional[str] = None

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
            try:
                body: dict[str, Any] = response.json()
                detail: str = body.get("detail", body.get("error", str(body)))
            except Exception:
                detail = response.text or f"HTTP {response.status_code}"
            if response.status_code in (401, 403) and self._agent_auth_mode == "bearer":
                detail = "Session expired. Run 'dailybot login' to re-authenticate."
            raise APIError(status_code=response.status_code, detail=detail)
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
        organization_id: Optional[int] = None,
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
        message: Optional[str] = None,
        done: Optional[str] = None,
        doing: Optional[str] = None,
        blocked: Optional[str] = None,
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

    # --- Agent endpoints ---

    def submit_agent_report(
        self,
        agent_name: str,
        content: str,
        structured: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
        is_milestone: bool = False,
        co_authors: Optional[list[str]] = None,
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
        message: Optional[str] = None,
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
        webhook_secret: Optional[str] = None,
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
        metadata: Optional[dict[str, Any]] = None,
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

    # --- Agent message endpoints ---

    def send_agent_message(
        self,
        agent_name: str,
        content: str,
        message_type: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        expires_at: Optional[str] = None,
        sender_type: Optional[str] = None,
        sender_name: Optional[str] = None,
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
        delivered: Optional[bool] = None,
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
        contact_email: Optional[str] = None,
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
