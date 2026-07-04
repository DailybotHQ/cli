"""HTTP client for Dailybot CLI API endpoints."""

from typing import Any

import httpx

from dailybot_cli.config import get_api_key, get_api_url, get_token

_MAX_LIST_PAGES: int = 50  # safety cap for paginated list endpoints


class APIError(Exception):
    """Raised when the API returns a non-success response."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        self.status_code: int = status_code
        self.detail: str = detail
        self.code: str | None = code
        self.retry_after: float | None = retry_after  # seconds, from a 429 Retry-After header
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
        """Build request headers.

        Prefers the Bearer login token; falls back to the org API key so that
        user-scoped endpoints (users, teams, forms, kudos, check-ins) work under
        either credential. The server accepts both on these endpoints.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if authenticated:
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
                self._agent_auth_mode = "bearer"
            elif self.api_key:
                headers["X-API-KEY"] = self.api_key
                self._agent_auth_mode = "api_key"
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
            retry_after: float | None = None
            if response.status_code == 429:
                raw_retry: str | None = response.headers.get("Retry-After")
                if raw_retry:
                    try:
                        retry_after = float(raw_retry)
                    except ValueError:
                        retry_after = None
            raise APIError(
                status_code=response.status_code,
                detail=detail,
                code=code,
                retry_after=retry_after,
            )
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

    def create_chat_completion(
        self,
        *,
        message: str | None = None,
        history: list[dict[str, Any]] | None = None,
        messages: list[dict[str, Any]] | None = None,
        session_id: str | None = None,
        reset_thread: bool = False,
        available_commands: list[Any] | None = None,
    ) -> dict[str, Any]:
        """POST /v1/cli/chat/completions/"""
        payload: dict[str, Any] = {}
        if message is not None:
            payload["message"] = message
        if history is not None:
            payload["history"] = history
        if messages is not None:
            payload["messages"] = messages
        if session_id is not None:
            payload["session_id"] = session_id
        if reset_thread:
            payload["reset_thread"] = True
        if available_commands is not None:
            payload["available_commands"] = available_commands

        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/cli/chat/completions/",
            json=payload,
            headers=self._headers(),
            timeout=120.0,
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

    def list_checkins(
        self,
        *,
        date: str | None = None,
        include_summary: bool = False,
        include_pending_users: bool = False,
    ) -> list[dict[str, Any]]:
        """GET /v1/checkins/ — fetch visible check-ins with optional completion state."""
        results: list[dict[str, Any]] = []
        params: dict[str, str] = {}
        if date:
            params["date"] = date
        if include_summary:
            params["include_summary"] = "true"
        if include_pending_users:
            params["include_pending_users"] = "true"
        url: str | None = f"{self.api_url}/v1/checkins/"
        pages_fetched: int = 0
        while url is not None and pages_fetched < _MAX_LIST_PAGES:
            response: httpx.Response = httpx.get(
                url,
                headers=self._headers(),
                params=params if pages_fetched == 0 else None,
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

    def get_checkin(self, followup_uuid: str) -> dict[str, Any]:
        """GET /v1/checkins/<followup_uuid>/."""
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/checkins/{followup_uuid}/",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def get_template(
        self,
        template_uuid: str,
        *,
        followup_uuid: str | None = None,
    ) -> dict[str, Any]:
        """GET /v1/templates/<template_uuid>/ — template question definitions."""
        params: dict[str, str] = {}
        if followup_uuid:
            params = {"render_special_vars": "true", "followup_id": followup_uuid}
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/templates/{template_uuid}/",
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def list_checkin_responses(
        self,
        followup_uuid: str,
        *,
        date_start: str | None = None,
        date_end: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/checkins/<followup_uuid>/responses/."""
        params: dict[str, str] = {}
        if date_start:
            params["date_start"] = date_start
        if date_end:
            params["date_end"] = date_end
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/checkins/{followup_uuid}/responses/",
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

    def update_checkin_response(
        self,
        followup_uuid: str,
        responses: list[dict[str, Any]],
        last_question_index: int | None = None,
    ) -> dict[str, Any]:
        """PUT /v1/checkins/<followup_uuid>/responses/ — update today's response."""
        payload: dict[str, Any] = {"responses": responses}
        if last_question_index is not None:
            payload["last_question_index"] = last_question_index
        response: httpx.Response = httpx.put(
            f"{self.api_url}/v1/checkins/{followup_uuid}/responses/",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def delete_checkin_response(
        self,
        followup_uuid: str,
        *,
        response_date: str | None = None,
    ) -> dict[str, Any]:
        """DELETE /v1/checkins/<followup_uuid>/responses/ — reset a submitted response."""
        params: dict[str, str] = {}
        if response_date:
            params["date_start"] = response_date
            params["date_end"] = response_date
        response: httpx.Response = httpx.request(
            "DELETE",
            f"{self.api_url}/v1/checkins/{followup_uuid}/responses/",
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def get_mood(self, mood_date: str | None = None) -> dict[str, Any]:
        """GET /v1/mood/track/ — fetch today's mood response."""
        params: dict[str, str] = {}
        if mood_date:
            params["date"] = mood_date
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/mood/track/",
            headers=self._headers(),
            params=params,
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def track_mood(self, score: int, mood_date: str | None = None) -> dict[str, Any]:
        """POST /v1/mood/track/ — record a mood score."""
        payload: dict[str, Any] = {"score": score}
        if mood_date:
            payload["date"] = mood_date
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/mood/track/",
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
        all_responses: bool = False,
        user: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/forms/<form_uuid>/responses/ — list responses.

        Without filters the server returns only the caller's own responses.
        ``all_responses`` / ``user`` are admin/owner-only server-side (a member
        receives 403); ``date_from`` / ``date_to`` (``YYYY-MM-DD``) narrow the
        window for anyone.
        """
        params: dict[str, str] = {}
        if state:
            params["state"] = state
        if all_responses:
            params["all"] = "true"
        if user:
            params["user"] = user
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
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

    # --- Report channels ---

    def list_report_channels(self) -> list[dict[str, Any]]:
        """GET /v1/report-channels/ — reporting channels available to the caller."""
        response: httpx.Response = httpx.get(
            f"{self.api_url}/v1/report-channels/",
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

    # --- Forms authoring ---

    def create_form(
        self,
        name: str,
        questions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """POST /v1/forms/create/ — create a form with optional inline questions."""
        payload: dict[str, Any] = {"name": name}
        if questions:
            payload["questions"] = questions
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/forms/create/",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def update_form_config(
        self,
        form_uuid: str,
        *,
        name: str | None = None,
        report_channels: list[str] | None = None,
    ) -> dict[str, Any]:
        """PATCH /v1/forms/<form_uuid>/config/ — edit name and/or report channels."""
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if report_channels is not None:
            payload["report_channels"] = report_channels
        response: httpx.Response = httpx.patch(
            f"{self.api_url}/v1/forms/{form_uuid}/config/",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def archive_form(self, form_uuid: str) -> dict[str, Any]:
        """DELETE /v1/forms/<form_uuid>/archive/ — soft-delete a form (204)."""
        response: httpx.Response = httpx.request(
            "DELETE",
            f"{self.api_url}/v1/forms/{form_uuid}/archive/",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def add_form_question(
        self,
        form_uuid: str,
        question: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /v1/forms/<form_uuid>/questions/ — add a question to a form."""
        response: httpx.Response = httpx.post(
            f"{self.api_url}/v1/forms/{form_uuid}/questions/",
            json=question,
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def update_form_question(
        self,
        form_uuid: str,
        question_uuid: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """PATCH /v1/forms/<form_uuid>/questions/<question_uuid>/ — update a question."""
        response: httpx.Response = httpx.patch(
            f"{self.api_url}/v1/forms/{form_uuid}/questions/{question_uuid}/",
            json=fields,
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def delete_form_question(
        self,
        form_uuid: str,
        question_uuid: str,
    ) -> dict[str, Any]:
        """DELETE /v1/forms/<form_uuid>/questions/<question_uuid>/delete/ (204)."""
        response: httpx.Response = httpx.request(
            "DELETE",
            f"{self.api_url}/v1/forms/{form_uuid}/questions/{question_uuid}/delete/",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._handle_response(response)

    def reorder_form_questions(
        self,
        form_uuid: str,
        order: list[str],
    ) -> dict[str, Any]:
        """PUT /v1/forms/<form_uuid>/questions/reorder/ — set a new question order."""
        response: httpx.Response = httpx.put(
            f"{self.api_url}/v1/forms/{form_uuid}/questions/reorder/",
            json={"order": order},
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

        Sends the canonical ``receivers`` list (users + teams merged, for
        validation) plus the type-specific ``users_receivers`` / ``teams_receivers``
        lists the server uses to expand teams into their members. At least one
        receiver must be present — the backend rejects an empty set.
        """
        payload: dict[str, Any] = {"content": content}
        receivers: list[str] = [*(user_uuid_receivers or []), *(team_uuid_receivers or [])]
        if receivers:
            payload["receivers"] = receivers
        if user_uuid_receivers:
            payload["users_receivers"] = user_uuid_receivers
        if team_uuid_receivers:
            payload["teams_receivers"] = team_uuid_receivers
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
