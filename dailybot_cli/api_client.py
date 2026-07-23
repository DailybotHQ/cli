"""HTTP client for Dailybot CLI API endpoints."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from dailybot_cli.config import (
    API_KEY_SOURCE_ENV_JSON,
    get_api_key,
    get_api_key_source,
    get_api_url,
    get_token,
)

_MAX_LIST_PAGES: int = 50  # safety cap for paginated list endpoints
LONG_TIMEOUT_SECS: float = 120.0  # AI-processing endpoints (ask, submit_update)

# HTTP status codes that trigger the alt-credential auth retry. 401 is the
# standards-compliant "credentials rejected" answer; 403 is what many
# Django/DRF backends actually send for the same condition (including for
# "credentials not provided" when the primary credential was silently
# stripped or malformed). Retrying on both makes env.json + a stale
# session work seamlessly regardless of which convention the server uses.
_AUTH_RETRY_STATUS_CODES: frozenset[int] = frozenset({401, 403})
DEFAULT_PAGE_SIZE: int = 25  # server default page size for paginated list endpoints
MAX_PAGE_SIZE: int = 100  # server clamps above this; the client clamps too

MAX_RATE_LIMIT_RETRIES: int = 3  # attempts to retry a generic 429 before raising
DEFAULT_RETRY_AFTER_SECS: float = 1.0  # backoff floor when a 429 omits Retry-After
# A free-plan daily throttle is NOT transient — retrying can never succeed today.
FREE_PLAN_DAILY_LIMIT_CODE: str = "free_plan_daily_limit_exceeded"

MAX_FALLBACK_DETAIL_CHARS: int = 160  # cap for a non-JSON error body echoed to the user
MAX_SEARCH_QUERY_LENGTH: int = 256  # server rejects search queries longer than this
MAX_OWNER_USER_IDS: int = 50  # server rejects owner_user_ids lists longer than this


def _fallback_detail(response: httpx.Response) -> str:
    """Build an error detail when the body is not the expected JSON envelope.

    A 5xx can return a rendered HTML page. Echoing that verbatim floods the
    terminal and leaks server internals (tracebacks, settings, file paths), so
    only short non-HTML bodies are surfaced.
    """
    content_type: str = response.headers.get("content-type", "")
    text: str = (response.text or "").strip()
    if not text or "html" in content_type.lower() or text.startswith("<"):
        return f"HTTP {response.status_code}"
    return text[:MAX_FALLBACK_DETAIL_CHARS]


def resource_uuid(payload: dict[str, Any]) -> str:
    """Return a resource's canonical identifier from an API payload.

    The API is mid-migration from ``id`` to ``uuid``: forms and their responses
    now expose only ``uuid``, agent resources expose both with the same value,
    and check-ins / kudos / workflows still expose only ``id``. Reading through
    this helper keeps every caller correct under all three shapes.
    """
    return str(payload.get("uuid") or payload.get("id") or "")


@dataclass
class PaginatedResult:
    """Normalized result of a paginated list request.

    Tolerates both the DRF envelope (``{count, next, previous, results}``) and a
    legacy bare-array response, exposing a single shape to callers.
    """

    results: list[dict[str, Any]] = field(default_factory=list)
    count: int | None = None
    next: str | None = None
    previous: str | None = None


def _merge_list_query(
    params: dict[str, Any],
    *,
    search: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Merge the shared list query params (search / date range) into ``params``.

    Raises :class:`APIError` with ``search_query_too_long`` if *search* exceeds
    :data:`MAX_SEARCH_QUERY_LENGTH` — matching the server-side validation so the
    user gets instant feedback instead of a round-trip 400.
    """
    if search is not None:
        normalized: str = " ".join(search.split())
        if len(normalized) > MAX_SEARCH_QUERY_LENGTH:
            raise APIError(
                400,
                "Search query is too long.",
                code="search_query_too_long",
            )
        params["search"] = search
    if start_date is not None:
        params["start_date"] = start_date
    if end_date is not None:
        params["end_date"] = end_date
    return params


def _fill_meta(meta: dict[str, Any] | None, result: "PaginatedResult") -> None:
    """Populate a caller-provided meta dict with pagination totals, if given."""
    if meta is not None:
        meta["count"] = result.count
        meta["next"] = result.next
        meta["previous"] = result.previous


class APIError(Exception):
    """Raised when the API returns a non-success response."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str | None = None,
        retry_after: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.status_code: int = status_code
        self.detail: str = detail
        self.code: str | None = code
        self.retry_after: float | None = retry_after  # seconds, from a 429 Retry-After header
        # Extra machine-readable context from the error body (e.g. upgrade_url,
        # required_role / current_role). Never a mutable default arg.
        self.extra: dict[str, Any] = extra or {}
        super().__init__(f"API error {status_code}: {detail}")


class DailyBotClient:
    """HTTP client for the Dailybot /v1/cli/* API endpoints."""

    def __init__(
        self,
        api_url: str | None = None,
        token: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
        prefer_api_key: bool | None = None,
    ) -> None:
        self.api_url: str = (api_url or get_api_url()).rstrip("/")
        self.token: str | None = token or get_token()
        self.api_key: str | None = api_key or get_api_key()
        self.timeout: float = timeout
        self._agent_auth_mode: str | None = None
        # Credential preference on the wire. A key resolved from
        # `.dailybot/env.json` expresses per-repo intent, so it must beat the
        # global Bearer session on the FIRST attempt — otherwise the Bearer
        # would silently win whenever the target server accepts it (wrong
        # identity) and the session token would leak to whatever server the
        # repo's env.json points at. Explicit `api_key` args and keys from
        # env var / config.json keep the long-standing Bearer-first order.
        if prefer_api_key is not None:
            self._prefer_api_key: bool = prefer_api_key
        else:
            self._prefer_api_key = (
                api_key is None
                and self.api_key is not None
                and get_api_key_source() == API_KEY_SOURCE_ENV_JSON
            )

    def _headers(self, authenticated: bool = True) -> dict[str, str]:
        """Build request headers.

        Default priority is Bearer login token first, org API key second —
        the server accepts both on user-scoped endpoints (users, teams,
        forms, kudos, check-ins). When the key came from ``.dailybot/env.json``
        (``self._prefer_api_key``), the order inverts so the per-repo key
        wins on the first attempt; the 401/403 retry covers the reverse.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if authenticated:
            if self.api_key and (self._prefer_api_key or not self.token):
                headers["X-API-KEY"] = self.api_key
                self._agent_auth_mode = "api_key"
            elif self.token:
                headers["Authorization"] = f"Bearer {self.token}"
                self._agent_auth_mode = "bearer"
        return headers

    def _agent_headers(self) -> dict[str, str]:
        """Build headers for agent authentication.

        Uses the same priority as ``_headers()`` — Bearer first, API key
        second, inverted when the key came from ``.dailybot/env.json`` — so
        that all endpoints behave consistently. The server accepts both on
        every ``/v1/agent*`` endpoint.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key and (self._prefer_api_key or not self.token):
            headers["X-API-KEY"] = self.api_key
            self._agent_auth_mode = "api_key"
        elif self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            self._agent_auth_mode = "bearer"
        else:
            self._agent_auth_mode = None
        return headers

    def _alt_auth_headers(self) -> dict[str, str] | None:
        """Build headers using the alternative credential for a 401 retry.

        If the primary was Bearer, tries API key; if the primary was API key,
        tries Bearer. Returns ``None`` when no alternative is available.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._agent_auth_mode == "bearer" and self.api_key:
            headers["X-API-KEY"] = self.api_key
            self._agent_auth_mode = "api_key"
            return headers
        if self._agent_auth_mode == "api_key" and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            self._agent_auth_mode = "bearer"
            return headers
        return None

    def _agent_request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Execute an agent-authenticated request with automatic alt-credential retry.

        Tries with ``_agent_headers()`` (Bearer preferred, API key fallback).
        If the server returns 401 or 403 and an alternative credential is
        available, retries once with it. This covers both directions: expired
        Bearer retried with API key, and stale API key retried with Bearer.

        Why 401 **and** 403: many Django/DRF APIs return 403 for "credentials
        rejected" or "credentials not provided" rather than the more
        standards-compliant 401. Retrying on both makes the behaviour
        consistent across backends and lets ``.dailybot/env.json`` work
        seamlessly even when a stale prod Bearer session is still on disk.
        """
        kwargs: dict[str, Any] = {"headers": self._agent_headers(), "timeout": self.timeout}
        if json is not None:
            kwargs["json"] = json
        if params is not None:
            kwargs["params"] = params

        response: httpx.Response = httpx.request(method, url, **kwargs)

        if response.status_code in _AUTH_RETRY_STATUS_CODES:
            alt: dict[str, str] | None = self._alt_auth_headers()
            if alt is not None:
                kwargs["headers"] = alt
                response = httpx.request(method, url, **kwargs)

        return response

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """Execute a user-scoped authenticated request with alt-credential retry.

        Sibling of :meth:`_agent_request` for the endpoints that authenticate
        via :meth:`_headers` (user-scoped: auth_status, checkin, form, kudos,
        chat, ask, user, team, ...). Same retry semantics — on 401/403 with
        an alternative credential present, retries once transparently.

        Do **not** use for login-lifecycle endpoints (``request_code``,
        ``verify_code``, ``logout``, ``register_agent``) — those must never
        fall back because the credential IS the thing under negotiation
        (or, for logout, we're actively invalidating it).

        ``timeout`` defaults to ``self.timeout`` (the standard read timeout);
        pass an explicit value for AI/AI-processing endpoints that need
        the longer :data:`LONG_TIMEOUT_SECS`.

        The dispatch to ``httpx.get`` / ``httpx.post`` / ``httpx.patch`` /
        ``httpx.put`` / ``httpx.request`` (for ``DELETE``) preserves the
        long-standing per-method patchable surface used by the test suite;
        both invocations (primary + retry) go through the same dispatch so
        the retry is transparent to callers and to test mocks alike.
        """
        kwargs: dict[str, Any] = {
            "headers": self._headers(),
            "timeout": self.timeout if timeout is None else timeout,
        }
        if params is not None:
            kwargs["params"] = params
        if json is not None:
            kwargs["json"] = json

        response: httpx.Response = self._dispatch_http(method, url, **kwargs)

        if response.status_code in _AUTH_RETRY_STATUS_CODES:
            alt: dict[str, str] | None = self._alt_auth_headers()
            if alt is not None:
                kwargs["headers"] = alt
                response = self._dispatch_http(method, url, **kwargs)

        return response

    @staticmethod
    def _dispatch_http(method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Route to the per-method ``httpx`` function so per-method patches
        (``patch("httpx.get", ...)``) keep working. ``DELETE`` goes through
        the generic ``httpx.request`` because ``httpx.delete`` does not
        accept a ``json`` body in all supported versions.
        """
        method_upper: str = method.upper()
        if method_upper == "GET":
            return httpx.get(url, **kwargs)
        if method_upper == "POST":
            return httpx.post(url, **kwargs)
        if method_upper == "PATCH":
            return httpx.patch(url, **kwargs)
        if method_upper == "PUT":
            return httpx.put(url, **kwargs)
        return httpx.request(method_upper, url, **kwargs)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Parse API response and raise on errors."""
        if response.status_code >= 400:
            code: str | None = None
            extra: dict[str, Any] = {}
            try:
                body: dict[str, Any] = response.json()
                detail: str = body.get("detail", body.get("error", str(body)))
                raw_code: Any = body.get("code")
                if isinstance(raw_code, str):
                    code = raw_code
                raw_extra: Any = body.get("extra")
                if isinstance(raw_extra, dict):
                    extra = dict(raw_extra)
                # Plan-gating responses carry upgrade_url at the top level; surface it
                # in extra so downstream reads a single place.
                upgrade_url: Any = body.get("upgrade_url")
                if isinstance(upgrade_url, str):
                    extra["upgrade_url"] = upgrade_url
            except Exception:
                detail = _fallback_detail(response)
            # Only a 401 means the session is unusable. A 403 is an authorization
            # verdict (wrong role, wrong plan) whose server detail explains the
            # actual cause — overwriting it sends the user into a re-login loop.
            if response.status_code == 401 and self._agent_auth_mode == "bearer":
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
                extra=extra,
            )
        if response.status_code == 204:
            return {}
        return response.json()

    def _send_with_retry(self, send: Callable[[], httpx.Response]) -> httpx.Response:
        """Issue a request via ``send`` with bounded retry on a transient 429.

        Honors the ``Retry-After`` header and backs off exponentially from it, up
        to ``MAX_RATE_LIMIT_RETRIES`` retries. A ``free_plan_daily_limit_exceeded``
        429 is NOT transient — it is returned immediately (no retry) so the caller
        raises a clear error. Any non-429 response is returned as-is. ``time.sleep``
        is referenced through the module so tests can patch it.
        """
        attempt: int = 0
        while True:
            response: httpx.Response = send()
            if response.status_code != 429:
                return response
            code: str | None = None
            try:
                body: Any = response.json()
                raw_code: Any = body.get("code") if isinstance(body, dict) else None
                if isinstance(raw_code, str):
                    code = raw_code
            except Exception:
                code = None
            if code == FREE_PLAN_DAILY_LIMIT_CODE or attempt >= MAX_RATE_LIMIT_RETRIES:
                return response
            retry_after: float = DEFAULT_RETRY_AFTER_SECS
            raw_retry: str | None = response.headers.get("Retry-After")
            if raw_retry:
                try:
                    retry_after = float(raw_retry)
                except ValueError:
                    retry_after = DEFAULT_RETRY_AFTER_SECS
            time.sleep(retry_after * (2**attempt))
            attempt += 1

    def _paginated_get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        page: int | None = None,
        page_size: int | None = None,
        fetch_all: bool = False,
        limit: int | None = None,
    ) -> PaginatedResult:
        """GET a list endpoint, tolerating both the DRF envelope and a bare array.

        - ``page`` / ``page_size`` are sent when provided; ``page_size`` is clamped
          to ``[1, MAX_PAGE_SIZE]``. ``limit`` is a legacy alias that also caps the
          total number of collected items.
        - ``fetch_all`` follows ``next`` (bounded by ``_MAX_LIST_PAGES``); otherwise a
          single page is returned.
        - Every ``/v1`` list endpoint now returns the envelope unconditionally. The
          bare-array branch below is kept only so an older deployment degrades to a
          single page instead of raising.
        """
        query: dict[str, Any] = dict(params) if params else {}
        if page is not None:
            query["page"] = page
        effective_page_size: int | None = page_size if page_size is not None else limit
        if effective_page_size is not None:
            query["page_size"] = max(1, min(effective_page_size, MAX_PAGE_SIZE))

        collected: list[dict[str, Any]] = []
        count: int | None = None
        next_url: str | None = None
        previous: str | None = None
        current_url: str | None = url
        first: bool = True
        pages_fetched: int = 0

        while current_url is not None and pages_fetched < _MAX_LIST_PAGES:
            page_url: str = current_url
            page_params: dict[str, Any] | None = query if first else None

            def _do_get(
                url: str = page_url, prm: dict[str, Any] | None = page_params
            ) -> httpx.Response:
                return self._request("GET", url, params=prm)

            response: httpx.Response = self._send_with_retry(_do_get)
            if response.status_code >= 400:
                self._handle_response(response)
            body: Any = response.json()
            if isinstance(body, dict) and "results" in body:
                collected.extend(body.get("results", []))
                count = body.get("count", count)
                next_url = body.get("next")
                previous = body.get("previous", previous)
            elif isinstance(body, list):
                collected.extend(body)
                if count is None:
                    count = len(body)
                next_url = None
            else:
                next_url = None
            pages_fetched += 1
            first = False

            if limit is not None and len(collected) >= limit:
                collected = collected[:limit]
                next_url = None
                break
            if not fetch_all:
                break
            current_url = next_url

        return PaginatedResult(results=collected, count=count, next=next_url, previous=previous)

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
        response: httpx.Response = self._request("GET", f"{self.api_url}/v1/cli/auth/status/")
        return self._handle_response(response)

    def logout(self) -> dict[str, Any]:
        """POST /v1/cli/auth/logout/

        Uses ``_headers`` directly (no fallback) because logout is a
        Bearer-only lifecycle operation — retrying with an API key would
        neither succeed nor be semantically meaningful.
        """
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
        response: httpx.Response = self._request(
            "POST",
            f"{self.api_url}/v1/cli/updates/",
            json=payload,
            timeout=LONG_TIMEOUT_SECS,
        )
        return self._handle_response(response)

    def get_status(self) -> dict[str, Any]:
        """GET /v1/cli/status/"""
        response: httpx.Response = self._request("GET", f"{self.api_url}/v1/cli/status/")
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

        response: httpx.Response = self._request(
            "POST",
            f"{self.api_url}/v1/cli/chat/completions/",
            json=payload,
            timeout=LONG_TIMEOUT_SECS,
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
        response: httpx.Response = self._request(
            "POST",
            f"{self.api_url}/v1/checkins/{followup_uuid}/responses/",
            json=payload,
        )
        return self._handle_response(response)

    def list_checkins(
        self,
        *,
        date: str | None = None,
        include_summary: bool = False,
        include_pending_users: bool = False,
        include_archived: bool = False,
        search: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        fetch_all: bool = True,
        limit: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/checkins/ — fetch visible check-ins with optional search/paging."""
        params: dict[str, Any] = {}
        if date:
            params["date"] = date
        if include_summary:
            params["include_summary"] = "true"
        if include_pending_users:
            params["include_pending_users"] = "true"
        if include_archived:
            params["include_archived"] = "true"
        _merge_list_query(params, search=search, start_date=start_date, end_date=end_date)
        result: PaginatedResult = self._paginated_get(
            f"{self.api_url}/v1/checkins/",
            params=params,
            page=page,
            page_size=page_size,
            fetch_all=fetch_all,
            limit=limit,
        )
        _fill_meta(meta, result)
        return result.results

    def get_checkin(self, followup_uuid: str) -> dict[str, Any]:
        """GET /v1/checkins/<followup_uuid>/."""
        response: httpx.Response = self._request(
            "GET", f"{self.api_url}/v1/checkins/{followup_uuid}/"
        )
        return self._handle_response(response)

    def get_checkin_detail(self, followup_uuid: str) -> dict[str, Any]:
        """GET /v1/checkins/<followup_uuid>/detail/ — canonical authoring read.

        Returns the check-in with the canonical question shape, resolved
        ``participants`` (users/teams with names), attached ``report_channels``
        and the ``is_archived`` flag — the shape aligned with form detail. Use
        this for authoring/verification rather than the v2 retrieve serializer.
        """
        response: httpx.Response = self._request(
            "GET", f"{self.api_url}/v1/checkins/{followup_uuid}/detail/"
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
        response: httpx.Response = self._request(
            "GET",
            f"{self.api_url}/v1/templates/{template_uuid}/",
            params=params,
        )
        return self._handle_response(response)

    def list_checkin_responses(
        self,
        followup_uuid: str,
        *,
        date_start: str | None = None,
        date_end: str | None = None,
        all_responses: bool = False,
        user: str | None = None,
        search: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        fetch_all: bool = True,
        limit: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/checkins/<followup_uuid>/responses/.

        Without a ``user`` filter the server returns **all participants'**
        responses in the date range — check-ins default to the whole team, unlike
        forms (which default to the caller's own). ``user`` narrows to one
        participant for admin/manager callers; a member caller has the requested
        UUID ignored and only ever receives their own responses (server-side
        guard, no 403). ``all_responses`` is a no-op kept for backward
        compatibility — the default already returns everything. Note check-ins use
        ``date_start`` / ``date_end`` (forms use ``date_from`` / ``date_to``).
        """
        params: dict[str, str] = {}
        if date_start:
            params["date_start"] = date_start
        if date_end:
            params["date_end"] = date_end
        if all_responses:
            params["all"] = "true"
        if user:
            params["user"] = user
        _merge_list_query(params, search=search, start_date=start_date, end_date=end_date)
        result: PaginatedResult = self._paginated_get(
            f"{self.api_url}/v1/checkins/{followup_uuid}/responses/",
            params=params,
            page=page,
            page_size=page_size,
            fetch_all=fetch_all,
            limit=limit,
        )
        _fill_meta(meta, result)
        return result.results

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
        response: httpx.Response = self._request(
            "PUT",
            f"{self.api_url}/v1/checkins/{followup_uuid}/responses/",
            json=payload,
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
        response: httpx.Response = self._request(
            "DELETE",
            f"{self.api_url}/v1/checkins/{followup_uuid}/responses/",
            params=params,
        )
        return self._handle_response(response)

    # --- Check-ins authoring ---

    def create_checkin(
        self,
        name: str,
        *,
        schedule: dict[str, Any] | None = None,
        participants: dict[str, Any] | None = None,
        questions: list[dict[str, Any]] | None = None,
        report_channels: list[str] | None = None,
        config: dict[str, Any] | None = None,
        generate_short_question: bool = False,
    ) -> dict[str, Any]:
        """POST /v1/checkins/create/ — create a check-in with schedule + questions.

        ``config`` carries the extra scheduling/behavior fields (frequency,
        reminders, timezone mode, submission rules, privacy, …) merged inline.
        ``generate_short_question`` opts into AI report-title generation for
        questions that were seeded without an explicit ``short_question``.
        """
        payload: dict[str, Any] = {"name": name}
        if schedule is not None:
            payload["schedule"] = schedule
        if participants is not None:
            payload["participants"] = participants
        if questions:
            payload["questions"] = questions
        if report_channels is not None:
            payload["report_channels"] = report_channels
        if generate_short_question:
            payload["generate_short_question"] = True
        if config:
            payload.update(config)
        response: httpx.Response = self._request(
            "POST",
            f"{self.api_url}/v1/checkins/create/",
            json=payload,
        )
        return self._handle_response(response)

    def update_checkin_config(
        self,
        followup_uuid: str,
        *,
        name: str | None = None,
        schedule: dict[str, Any] | None = None,
        report_channels: list[str] | None = None,
        is_active: bool | None = None,
        participants: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """PATCH /v1/checkins/<followup_uuid>/config/ — edit config (partial update).

        ``config`` carries the extra scheduling/behavior fields (frequency,
        reminders, timezone mode, submission rules, privacy, …); only the keys
        present are changed.
        """
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if schedule is not None:
            payload["schedule"] = schedule
        if report_channels is not None:
            payload["report_channels"] = report_channels
        if is_active is not None:
            payload["is_active"] = is_active
        if participants is not None:
            payload["participants"] = participants
        if config:
            payload.update(config)
        response: httpx.Response = self._request(
            "PATCH",
            f"{self.api_url}/v1/checkins/{followup_uuid}/config/",
            json=payload,
        )
        return self._handle_response(response)

    def archive_checkin(self, followup_uuid: str) -> dict[str, Any]:
        """DELETE /v1/checkins/<followup_uuid>/archive/ — soft-delete a check-in (204)."""
        response: httpx.Response = self._request(
            "DELETE",
            f"{self.api_url}/v1/checkins/{followup_uuid}/archive/",
        )
        return self._handle_response(response)

    def add_checkin_question(
        self,
        followup_uuid: str,
        question: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /v1/checkins/<followup_uuid>/questions/ — add a question."""
        response: httpx.Response = self._request(
            "POST",
            f"{self.api_url}/v1/checkins/{followup_uuid}/questions/",
            json=question,
        )
        return self._handle_response(response)

    def update_checkin_question(
        self,
        followup_uuid: str,
        question_uuid: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """PATCH /v1/checkins/<followup_uuid>/questions/<question_uuid>/ — update a question."""
        response: httpx.Response = self._request(
            "PATCH",
            f"{self.api_url}/v1/checkins/{followup_uuid}/questions/{question_uuid}/",
            json=fields,
        )
        return self._handle_response(response)

    def delete_checkin_question(
        self,
        followup_uuid: str,
        question_uuid: str,
    ) -> dict[str, Any]:
        """DELETE /v1/checkins/<followup_uuid>/questions/<question_uuid>/delete/ (204)."""
        response: httpx.Response = self._request(
            "DELETE",
            f"{self.api_url}/v1/checkins/{followup_uuid}/questions/{question_uuid}/delete/",
        )
        return self._handle_response(response)

    def reorder_checkin_questions(
        self,
        followup_uuid: str,
        order: list[str],
    ) -> dict[str, Any]:
        """PUT /v1/checkins/<followup_uuid>/questions/reorder/ — set a new question order."""
        response: httpx.Response = self._request(
            "PUT",
            f"{self.api_url}/v1/checkins/{followup_uuid}/questions/reorder/",
            json={"question_uuids": order},
        )
        return self._handle_response(response)

    def get_mood(self, mood_date: str | None = None) -> dict[str, Any]:
        """GET /v1/mood/track/ — fetch today's mood response."""
        params: dict[str, str] = {}
        if mood_date:
            params["date"] = mood_date
        response: httpx.Response = self._request(
            "GET",
            f"{self.api_url}/v1/mood/track/",
            params=params,
        )
        return self._handle_response(response)

    def track_mood(self, score: int, mood_date: str | None = None) -> dict[str, Any]:
        """POST /v1/mood/track/ — record a mood score."""
        payload: dict[str, Any] = {"score": score}
        if mood_date:
            payload["date"] = mood_date
        response: httpx.Response = self._request(
            "POST",
            f"{self.api_url}/v1/mood/track/",
            json=payload,
        )
        return self._handle_response(response)

    def list_forms(
        self,
        *,
        include_questions: bool = False,
        include_archived: bool = False,
        owner: str | None = None,
        owner_user_ids: list[str] | None = None,
        filter_scope: str | None = None,
        order: str | None = None,
        is_ascend: bool = False,
        search: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        fetch_all: bool = True,
        limit: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/forms/ — optionally expand questions, search, and page.

        The default response is org-wide (every form in the caller's org).
        Capabilities are governed by each form's permissions. Pass
        ``owner_user_ids`` to filter by specific owners, or
        ``filter_scope`` to apply a server-side scope filter.

        When ``meta`` is given it is populated with ``count`` / ``next`` for a
        pagination footer.
        """
        params: dict[str, Any] = {}
        if include_questions:
            params["include"] = "questions"
        if include_archived:
            params["include_archived"] = "true"
        if owner:
            params["owner"] = owner
        if owner_user_ids:
            params["owner_user_ids"] = ",".join(owner_user_ids)
        if filter_scope:
            params["filter"] = filter_scope
        if order:
            params["order"] = order
        if is_ascend:
            params["is_ascend"] = "true"
        _merge_list_query(params, search=search, start_date=start_date, end_date=end_date)
        result: PaginatedResult = self._paginated_get(
            f"{self.api_url}/v1/forms/",
            params=params,
            page=page,
            page_size=page_size,
            fetch_all=fetch_all,
            limit=limit,
        )
        _fill_meta(meta, result)
        return result.results

    def list_form_owners(
        self,
        *,
        search: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """GET /v1/forms/form-owners/ — paginated picker of org members who own forms.

        Returns the raw paginated envelope ``{count, next, previous, results}``.
        Each result has ``uuid``, ``full_name``, ``image``, ``role``, and
        optionally ``email`` (only visible to admins/managers).
        """
        params: dict[str, Any] = {}
        if search:
            params["search"] = search
        if offset is not None:
            params["offset"] = offset
        if limit is not None:
            params["limit"] = limit
        response: httpx.Response = self._request(
            "GET",
            f"{self.api_url}/v1/forms/form-owners/",
            params=params,
        )
        return self._handle_response(response)

    def get_form(self, form_uuid: str) -> dict[str, Any]:
        """GET /v1/forms/<form_uuid>/ — form metadata and question definitions."""
        response: httpx.Response = self._request("GET", f"{self.api_url}/v1/forms/{form_uuid}/")
        return self._handle_response(response)

    def submit_form_response(
        self,
        form_uuid: str,
        content: dict[str, Any],
        *,
        automation: bool = False,
        anonymous: bool = False,
        guest_user: dict[str, str] | None = None,
        submission_source: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/forms/<form_uuid>/responses/"""
        payload: dict[str, Any] = {"content": content}
        if automation:
            payload["automation"] = True
        if anonymous:
            payload["anonymous"] = True
        if guest_user:
            payload["guest_user"] = guest_user
        if submission_source:
            payload["submission_source"] = submission_source
        response: httpx.Response = self._request(
            "POST",
            f"{self.api_url}/v1/forms/{form_uuid}/responses/",
            json=payload,
        )
        return self._handle_response(response)

    def list_form_responses(
        self,
        form_uuid: str,
        *,
        state: str | None = None,
        all_responses: bool = False,
        user: str | None = None,
        submission_sources: str | None = None,
        submitter_user_ids: str | None = None,
        flow_status: str | None = None,
        order: str | None = None,
        is_ascend: bool = False,
        date_from: str | None = None,
        date_to: str | None = None,
        search: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        fetch_all: bool = True,
        limit: int | None = None,
        meta: dict[str, Any] | None = None,
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
        if submission_sources:
            params["submission_sources"] = submission_sources
        if submitter_user_ids:
            params["submitter_user_ids"] = submitter_user_ids
        if flow_status:
            params["flow_status"] = flow_status
        if order:
            params["order"] = order
        if is_ascend:
            params["is_ascend"] = "true"
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        _merge_list_query(params, search=search, start_date=start_date, end_date=end_date)
        result: PaginatedResult = self._paginated_get(
            f"{self.api_url}/v1/forms/{form_uuid}/responses/",
            params=params,
            page=page,
            page_size=page_size,
            fetch_all=fetch_all,
            limit=limit,
        )
        _fill_meta(meta, result)
        return result.results

    def get_form_response(
        self,
        form_uuid: str,
        response_uuid: str,
    ) -> dict[str, Any]:
        """GET /v1/forms/<form_uuid>/responses/<response_uuid>/"""
        response: httpx.Response = self._request(
            "GET",
            f"{self.api_url}/v1/forms/{form_uuid}/responses/{response_uuid}/",
        )
        return self._handle_response(response)

    def update_form_response(
        self,
        form_uuid: str,
        response_uuid: str,
        content: dict[str, Any],
    ) -> dict[str, Any]:
        """PATCH /v1/forms/<form_uuid>/responses/<response_uuid>/"""
        response: httpx.Response = self._request(
            "PATCH",
            f"{self.api_url}/v1/forms/{form_uuid}/responses/{response_uuid}/",
            json={"content": content},
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
        response: httpx.Response = self._request(
            "POST",
            f"{self.api_url}/v1/forms/{form_uuid}/responses/{response_uuid}/transition/",
            json=payload,
        )
        return self._handle_response(response)

    def delete_form_response(
        self,
        form_uuid: str,
        response_uuid: str,
    ) -> dict[str, Any]:
        """DELETE /v1/forms/<form_uuid>/responses/<response_uuid>/"""
        response: httpx.Response = self._request(
            "DELETE",
            f"{self.api_url}/v1/forms/{form_uuid}/responses/{response_uuid}/",
        )
        return self._handle_response(response)

    # --- Report channels ---

    def list_report_channels(self) -> list[dict[str, Any]]:
        """GET /v1/report-channels/ — reporting channels available to the caller.

        The endpoint returns ``{"channels": [{id, name, platform, type}], "total": N}``;
        older/other deployments may return ``{"results": [...]}`` or a bare list.
        All three are accepted.
        """
        response: httpx.Response = self._request("GET", f"{self.api_url}/v1/report-channels/")
        if response.status_code >= 400:
            self._handle_response(response)
        body: Any = response.json()
        if isinstance(body, dict):
            if "channels" in body:
                return list(body.get("channels", []))
            if "results" in body:
                return list(body.get("results", []))
        if isinstance(body, list):
            return body
        return []

    # --- Forms authoring ---

    def create_form(
        self,
        name: str,
        questions: list[dict[str, Any]] | None = None,
        *,
        report_channels: list[str] | None = None,
        generate_short_question: bool = False,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /v1/forms/create/ — create a form with optional questions + channels.

        ``generate_short_question`` opts into AI report-title generation for
        questions seeded without an explicit ``short_question``. ``config`` carries
        the form-level fields (privacy/workflow/permissions/anonymous/public/approval/
        command) merged inline.
        """
        payload: dict[str, Any] = {"name": name}
        if questions:
            payload["questions"] = questions
        if report_channels:
            payload["report_channels"] = report_channels
        if generate_short_question:
            payload["generate_short_question"] = True
        if config:
            payload.update(config)
        response: httpx.Response = self._request(
            "POST",
            f"{self.api_url}/v1/forms/create/",
            json=payload,
        )
        return self._handle_response(response)

    def update_form_config(
        self,
        form_uuid: str,
        *,
        name: str | None = None,
        report_channels: list[str] | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """PATCH /v1/forms/<form_uuid>/config/ — edit name, channels, and/or config.

        ``config`` carries the form-level fields (workflow/permissions/anonymous/
        public/approval/command) merged inline; only the keys present change.
        """
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if report_channels is not None:
            payload["report_channels"] = report_channels
        if config:
            payload.update(config)
        response: httpx.Response = self._request(
            "PATCH",
            f"{self.api_url}/v1/forms/{form_uuid}/config/",
            json=payload,
        )
        return self._handle_response(response)

    def archive_form(self, form_uuid: str) -> dict[str, Any]:
        """DELETE /v1/forms/<form_uuid>/archive/ — soft-delete a form (204)."""
        response: httpx.Response = self._request(
            "DELETE",
            f"{self.api_url}/v1/forms/{form_uuid}/archive/",
        )
        return self._handle_response(response)

    def add_form_question(
        self,
        form_uuid: str,
        question: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /v1/forms/<form_uuid>/questions/ — add a question to a form."""
        response: httpx.Response = self._request(
            "POST",
            f"{self.api_url}/v1/forms/{form_uuid}/questions/",
            json=question,
        )
        return self._handle_response(response)

    def update_form_question(
        self,
        form_uuid: str,
        question_uuid: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """PATCH /v1/forms/<form_uuid>/questions/<question_uuid>/ — update a question."""
        response: httpx.Response = self._request(
            "PATCH",
            f"{self.api_url}/v1/forms/{form_uuid}/questions/{question_uuid}/",
            json=fields,
        )
        return self._handle_response(response)

    def delete_form_question(
        self,
        form_uuid: str,
        question_uuid: str,
    ) -> dict[str, Any]:
        """DELETE /v1/forms/<form_uuid>/questions/<question_uuid>/delete/ (204)."""
        response: httpx.Response = self._request(
            "DELETE",
            f"{self.api_url}/v1/forms/{form_uuid}/questions/{question_uuid}/delete/",
        )
        return self._handle_response(response)

    def reorder_form_questions(
        self,
        form_uuid: str,
        order: list[str],
    ) -> dict[str, Any]:
        """PUT /v1/forms/<form_uuid>/questions/reorder/ — set a new question order."""
        response: httpx.Response = self._request(
            "PUT",
            f"{self.api_url}/v1/forms/{form_uuid}/questions/reorder/",
            json={"question_uuids": order},
        )
        return self._handle_response(response)

    def list_users(
        self, *, include_inactive: bool = False, include_email: bool = False
    ) -> list[dict[str, Any]]:
        """GET /v1/users/ — fetch all pages and return the combined results list.

        By default returns only members with ``is_active`` truthy. Pass
        ``include_inactive=True`` to get the unfiltered server response (useful
        for admin / audit flows that need to surface deactivated accounts).
        ``include_email=True`` requests the ``email`` field (server-gated to
        admins/managers; silently omitted otherwise) so callers can resolve a
        person by email.
        """
        base_url: str = f"{self.api_url}/v1/users/"
        url: str = f"{base_url}?include_email=true" if include_email else base_url
        result: PaginatedResult = self._paginated_get(url, fetch_all=True)
        results: list[dict[str, Any]] = result.results
        if include_inactive:
            return results
        return [u for u in results if u.get("is_active", True)]

    def get_me(self, *, include_email: bool = False) -> dict[str, Any]:
        """GET /v1/me/ — the authenticated user + organization context."""
        params: dict[str, str] = {}
        if include_email:
            params["include_email"] = "true"
        response: httpx.Response = self._request(
            "GET",
            f"{self.api_url}/v1/me/",
            params=params,
        )
        return self._handle_response(response)

    def get_organization(self) -> dict[str, Any]:
        """GET /v1/organization/ — the org the current credential is scoped to."""
        response: httpx.Response = self._request("GET", f"{self.api_url}/v1/organization/")
        return self._handle_response(response)

    def get_user(self, user_uuid: str, *, include_email: bool = False) -> dict[str, Any]:
        """GET /v1/users/<uuid>/ — a single user's profile."""
        params: dict[str, str] = {}
        if include_email:
            params["include_email"] = "true"
        response: httpx.Response = self._request(
            "GET",
            f"{self.api_url}/v1/users/{user_uuid}/",
            params=params,
        )
        return self._handle_response(response)

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
        response: httpx.Response = self._request(
            "POST",
            f"{self.api_url}/v1/kudos/",
            json=payload,
        )
        return self._handle_response(response)

    def list_kudos(
        self,
        *,
        kudos_filter: str | None = None,
        search: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        fetch_all: bool = True,
        limit: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/kudos/ — list kudos (paginated), optionally filtered."""
        params: dict[str, Any] = {}
        if kudos_filter:
            params["filter"] = kudos_filter
        _merge_list_query(params, search=search, start_date=start_date, end_date=end_date)
        result: PaginatedResult = self._paginated_get(
            f"{self.api_url}/v1/kudos/",
            params=params,
            page=page,
            page_size=page_size,
            fetch_all=fetch_all,
            limit=limit,
        )
        _fill_meta(meta, result)
        return result.results

    def list_workflows(
        self,
        *,
        search: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        fetch_all: bool = True,
        limit: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/workflows/ — list workflows (plan-gated feature)."""
        params: dict[str, Any] = {}
        _merge_list_query(params, search=search, start_date=start_date, end_date=end_date)
        result: PaginatedResult = self._paginated_get(
            f"{self.api_url}/v1/workflows/",
            params=params,
            page=page,
            page_size=page_size,
            fetch_all=fetch_all,
            limit=limit,
        )
        _fill_meta(meta, result)
        return result.results

    def get_workflow(self, workflow_uuid: str) -> dict[str, Any]:
        """GET /v1/workflows/<uuid>/ — a single workflow's configuration."""
        response: httpx.Response = self._request(
            "GET", f"{self.api_url}/v1/workflows/{workflow_uuid}/"
        )
        return self._handle_response(response)

    def trigger_workflow(
        self,
        workflow_uuid: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /v1/workflows/<uuid>/trigger/ — queue an ``api_trigger`` workflow.

        Only workflows whose trigger type is ``api_trigger`` ("When triggered via
        API or button") can be fired this way. The run is asynchronous — success
        is ``202 {queued: true, workflow_uuid, detail}`` with no run output.
        Optional *payload* (a JSON object ≤ 8 KiB) is exposed to workflow steps
        as ``{{trigger.body.*}}`` variables.
        """
        body: dict[str, Any] = {}
        if payload is not None:
            body["payload"] = payload
        response: httpx.Response = self._request(
            "POST",
            f"{self.api_url}/v1/workflows/{workflow_uuid}/trigger/",
            json=body,
        )
        return self._handle_response(response)

    def list_kudos_organization(
        self,
        *,
        search: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        fetch_all: bool = True,
        limit: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/kudos/organization/ — every kudos in the org (admin-only).

        The org-wide counterpart of ``list_kudos``, which is scoped to the caller.
        Returns the same paginated envelope, not an aggregate statistics object.
        """
        params: dict[str, Any] = {}
        _merge_list_query(params, search=search, start_date=start_date, end_date=end_date)
        result: PaginatedResult = self._paginated_get(
            f"{self.api_url}/v1/kudos/organization/",
            params=params,
            page=page,
            page_size=page_size,
            fetch_all=fetch_all,
            limit=limit,
        )
        _fill_meta(meta, result)
        return result.results

    def get_kudos_wall_of_fame(self, *, limit: int | None = None) -> dict[str, Any]:
        """GET /v1/kudos/wall-of-fame/ — leaderboard rankings."""
        params: dict[str, str] = {}
        if limit is not None:
            params["limit"] = str(limit)
        response: httpx.Response = self._request(
            "GET",
            f"{self.api_url}/v1/kudos/wall-of-fame/",
            params=params,
        )
        return self._handle_response(response)

    def list_teams(self) -> list[dict[str, Any]]:
        """GET /v1/teams/ — server scopes results by role (admin sees all, member sees own)."""
        result: PaginatedResult = self._paginated_get(f"{self.api_url}/v1/teams/", fetch_all=True)
        return result.results

    def get_team(self, team_uuid: str) -> dict[str, Any]:
        """GET /v1/teams/<team_uuid>/"""
        response: httpx.Response = self._request("GET", f"{self.api_url}/v1/teams/{team_uuid}/")
        return self._handle_response(response)

    def list_team_members(self, team_uuid: str) -> list[dict[str, Any]]:
        """GET /v1/teams/<team_uuid>/members/"""
        response: httpx.Response = self._request(
            "GET", f"{self.api_url}/v1/teams/{team_uuid}/members/"
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
        response: httpx.Response = self._agent_request(
            "POST",
            f"{self.api_url}/v1/agent-reports/",
            json=payload,
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
        response: httpx.Response = self._agent_request(
            "POST",
            f"{self.api_url}/v1/agent-health/",
            json=payload,
        )
        return self._handle_response(response)

    def get_agent_health(self, agent_name: str) -> dict[str, Any]:
        """GET /v1/agent-health/?agent_name=..."""
        response: httpx.Response = self._agent_request(
            "GET",
            f"{self.api_url}/v1/agent-health/",
            params={"agent_name": agent_name},
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
        response: httpx.Response = self._agent_request(
            "POST",
            f"{self.api_url}/v1/agent-webhook/",
            json=payload,
        )
        return self._handle_response(response)

    def unregister_agent_webhook(self, agent_name: str) -> dict[str, Any]:
        """DELETE /v1/agent-webhook/"""
        response: httpx.Response = self._agent_request(
            "DELETE",
            f"{self.api_url}/v1/agent-webhook/",
            json={"agent_name": agent_name},
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
        response: httpx.Response = self._agent_request(
            "POST",
            f"{self.api_url}/v1/agent-email/send/",
            json=payload,
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
        response: httpx.Response = self._agent_request(
            "POST",
            f"{self.api_url}/v1/send-message/",
            json=payload,
        )
        return self._handle_response(response)

    def open_conversation(self, users_uuids: list[str]) -> dict[str, Any]:
        """POST /v1/open-conversation/ — open (or fetch) a Slack group DM (MPIM).

        Opens a private Slack group conversation that includes the given org
        users plus the Dailybot bot (Slack adds the bot because the call uses the
        org's bot token). The call is idempotent: the same set of users returns
        the same channel if it already exists.

        Slack-only and org-admin-only, both server-enforced. Authenticated via
        the shared agent header logic (``X-API-KEY`` preferred, else the login
        Bearer token). Returns ``{"channel": "<slack-conversation-id>"}``.
        """
        response: httpx.Response = self._agent_request(
            "POST",
            f"{self.api_url}/v1/open-conversation/",
            json={"users_uuids": users_uuids},
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
        response: httpx.Response = self._agent_request(
            "POST",
            f"{self.api_url}/v1/agent-messages/",
            json=payload,
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
        response: httpx.Response = self._agent_request(
            "GET",
            f"{self.api_url}/v1/agent-messages/",
            params=params,
        )
        if response.status_code >= 400:
            self._handle_response(response)
        data: Any = response.json()
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        if isinstance(data, list):
            return data
        return []

    def mark_agent_messages_read(
        self,
        message_ids: list[str],
    ) -> dict[str, Any]:
        """PATCH /v1/agent-messages/read/"""
        response: httpx.Response = self._agent_request(
            "PATCH",
            f"{self.api_url}/v1/agent-messages/read/",
            json={"message_ids": message_ids},
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
