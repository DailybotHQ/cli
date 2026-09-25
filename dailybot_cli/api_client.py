"""HTTP client for Dailybot CLI API endpoints."""

import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit

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

# Task attachments. The presigned (object storage) door accepts up to 25 MiB; the
# one-request multipart door is capped by the server's request ceiling (5 MiB).
ATTACHMENT_MAX_SIZE_BYTES: int = 25 * 1024 * 1024
ATTACHMENT_MULTIPART_MAX_BYTES: int = 5 * 1024 * 1024
ATTACHMENT_TRANSFER_TIMEOUT_SECS: float = LONG_TIMEOUT_SECS
# A read timeout is per read, so a storage host that drips one byte a minute is
# never cut off by it. This is the wall-clock ceiling for the whole storage hop.
ATTACHMENT_DOWNLOAD_DEADLINE_SECS: float = 300.0

# HTTP status codes that trigger the alt-credential auth retry. 401 is the
# standards-compliant "credentials rejected" answer; 403 is what many
# Django/DRF backends actually send for the same condition (including for
# "credentials not provided" when the primary credential was silently
# stripped or malformed). Retrying on both makes env.json + a stale
# session work seamlessly regardless of which convention the server uses.
_AUTH_RETRY_STATUS_CODES: frozenset[int] = frozenset({401, 403})

# The person-shaped Tasks doors have a third refusal shape: `400 actor_required`,
# meaning "this credential is an organization with nobody to be". It is the same
# condition as a 401 — the wrong *kind* of credential was presented — but it does
# not arrive with an auth status code, so the retry above would skip it. That
# matters whenever `.dailybot/env.json` supplies the key: `_prefer_api_key` then
# sends `X-API-KEY` first even though a Bearer session exists, and without this the
# CLI would tell an already-signed-in user to run `dailybot login`.
_ACTOR_REQUIRED_CODE: str = "actor_required"


def _is_auth_retryable(response: httpx.Response) -> bool:
    """True when the refusal means "wrong credential kind", whatever its status."""
    if response.status_code in _AUTH_RETRY_STATUS_CODES:
        return True
    if response.status_code != 400:
        return False
    try:
        body: Any = response.json()
    except Exception:
        return False
    return isinstance(body, dict) and body.get("code") == _ACTOR_REQUIRED_CODE


DEFAULT_PAGE_SIZE: int = 25  # server default page size for paginated list endpoints
MAX_PAGE_SIZE: int = 100  # server clamps above this; the client clamps too

MAX_RATE_LIMIT_RETRIES: int = 3  # attempts to retry a generic 429 before raising
DEFAULT_RETRY_AFTER_SECS: float = 1.0  # backoff floor when a 429 omits Retry-After
# A free-plan daily throttle is NOT transient — retrying can never succeed today.
FREE_PLAN_DAILY_LIMIT_CODE: str = "free_plan_daily_limit_exceeded"

MAX_FALLBACK_DETAIL_CHARS: int = 160  # cap for a non-JSON error body echoed to the user
MAX_SEARCH_QUERY_LENGTH: int = 256  # server rejects search queries longer than this
MAX_OWNER_USER_IDS: int = 50  # server rejects owner_user_ids lists longer than this

# --- Tasks (/v1/tasks/*) ---
TASKS_BASE_PATH: str = "/v1/tasks/"
# Every segment of a Tasks path: a key (`ENG-142`), a uuid, or a fixed word. A
# task key or uuid is interpolated into the path, and task text is untrusted, so
# a value like `X/../../boards/<uuid>/archive/?` must never reach the HTTP stack,
# which would collapse it into a different door. `%` is refused too: a server
# that decodes `%2F` before routing would re-open the same hole.
TASKS_PATH_SEGMENT_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_-]+$")
INVALID_IDENTIFIER_CODE: str = "invalid_identifier"
# An entity tag as RFC 9110 defines it: optionally weak, always quoted, visible
# ASCII only. The ETag is printed for `ETAG=$(...)` capture and sent back as
# `If-Match`, so anything else (control characters, a newline, a bidi override)
# is refused rather than printed or put in a header.
ETAG_RE: re.Pattern[str] = re.compile(r'^(W/)?"[\x21\x23-\x7e]*"$')
INVALID_ETAG_CODE: str = "invalid_etag"
DEFAULT_PORTS: dict[str, int] = {"http": 80, "https": 443}
# Server cap on a bulk payload; above it the server answers `too_many_items`.
# BLAST_RADIUS.md records this as THE volume guard for unattended destructive
# loops — the CLI adds no second ceiling of its own.
TASKS_BULK_MAX_ITEMS: int = 100
IDEMPOTENCY_KEY_HEADER: str = "Idempotency-Key"
IDEMPOTENCY_REPLAYED_HEADER: str = "Idempotency-Replayed"
# The board delta door keeps a 7-day window; an older cursor is refused forever
# with `delta_window_expired` + `full_resync_required`. Retrying is an infinite
# loop — the only correct response is a fresh snapshot.
TASKS_DELTA_MAX_WINDOW_DAYS: int = 7
# Key surfaced on a write result when the server replayed a previous identical
# call instead of performing a new one (from IDEMPOTENCY_REPLAYED_HEADER).
IDEMPOTENCY_REPLAYED_KEY: str = "_idempotency_replayed"
IDEMPOTENCY_KEY_SENT_KEY: str = "_idempotency_key"


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


def _merge_dashboard_enrichment_query(
    params: dict[str, Any],
    *,
    labels: list[str] | None = None,
    featured: bool | None = None,
    prioritize_featured: bool | None = None,
) -> dict[str, Any]:
    """Merge Labels / Featured dashboard enrichment query params."""
    if labels:
        params["labels"] = ",".join(labels)
    if featured is not None:
        params["featured"] = "true" if featured else "false"
    if prioritize_featured is not None:
        params["prioritize_featured"] = "true" if prioritize_featured else "false"
    return params


def _label_entity_collection(entity_type: str) -> str:
    """Map CLI entity type (including web 'automations') to the public API path."""
    normalized: str = entity_type.strip().lower()
    if normalized in {"automations", "workflows", "workflow"}:
        return "workflows"
    if normalized in {"forms", "form"}:
        return "forms"
    if normalized in {"checkins", "checkin", "check-ins"}:
        return "checkins"
    raise ValueError(
        f"entity type must be one of: forms, checkins, workflows (got {entity_type!r})"
    )


def as_query_datetime(value: datetime | str) -> str:
    """Render a datetime for a Tasks query string, always in the ``Z`` form.

    ``datetime.now(timezone.utc).isoformat()`` ends in ``+00:00``. In a query
    string an unencoded ``+`` decodes to a space, so the server receives
    ``...T13:13:37 00:00`` and correctly refuses it — with a message saying the
    value must be ISO-8601, about a value that is. This is the single most
    likely way a Python client breaks the delta door
    (MEASURED_ANSWERS.md §4, "The trap that is not our defect").

    A naive datetime is read as UTC. Microseconds are dropped so a cursor
    round-trips stably.

    A **string** is normalised only if it parses as ISO-8601, and passed through
    untouched otherwise. Both halves matter: the server's ``delta_cursor`` is an
    ISO-8601 timestamp and can carry ``+00:00``, so echoing it back verbatim
    would reproduce the very bug this function exists to prevent — while a cursor
    that is genuinely opaque must not be reformatted into something the server
    cannot read.
    """
    if isinstance(value, str):
        try:
            parsed: datetime = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value  # opaque token — not ours to reinterpret
        value = parsed
    moment: datetime = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fill_meta(meta: dict[str, Any] | None, result: "PaginatedResult") -> None:
    """Populate a caller-provided meta dict with pagination totals, if given."""
    if meta is not None:
        meta["count"] = result.count
        meta["next"] = result.next
        meta["previous"] = result.previous


# Exit code for "the request never reached a server, or the answer was
# unreadable". Deliberately distinct from every EXIT_* the command layer uses
# (2-7) and from the delta-window code (9): an agent branching on the exit status
# is the primary consumer, and conflating "no network" with "forbidden" would
# send it down the wrong recovery path.
EXIT_TRANSPORT_ERROR: int = 8


class TransportError(httpx.HTTPError):
    """Raised when a request never produced a readable HTTP response.

    Deliberately **not** a subclass of :class:`APIError`. An ``APIError`` is a
    *server verdict* — it has a status code and a machine-readable ``code`` a
    command can branch on. A transport failure has neither, and pretending it does
    would mean every ``except APIError`` block silently treats "the network is
    down" as "the server said no".

    It **is** an ``httpx.HTTPError``, and that is equally deliberate. The TUI and
    the interactive menu already carry ~25 ``except (APIError, httpx.HTTPError)``
    handlers that show an in-app "couldn't reach Dailybot" message; making this a
    bare ``Exception`` walked straight past all of them and killed the Textual app
    instead. Wrapping a failure must not make the failure less catchable than it
    was before.

    The ~30 ``except APIError`` handlers still do not catch it — which is correct,
    and why the root callback in ``main.py`` carries a last-resort net so nothing
    reaches the user as a traceback.

    ``idempotency_key`` carries the key the timed-out write actually sent, when
    there was one. It is the only thing that makes the retry safe, and it is
    exactly the call that cannot read it off a response body.
    """

    def __init__(self, message: str, *, idempotency_key: str | None = None) -> None:
        super().__init__(message)
        self.idempotency_key: str | None = idempotency_key


class TransportTimeout(TransportError, httpx.TimeoutException):
    """A transport failure that was specifically a timeout.

    Separate from its parent so the pre-existing ``except httpx.TimeoutException``
    handlers — which say "that took longer than expected" rather than "we could not
    reach the server" — keep firing.
    """


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


def _invalid_identifier() -> APIError:
    """The refusal for an identifier that would change which door a path reaches.

    The offending value is deliberately not echoed: it is untrusted text, and the
    error message is rendered to a terminal.
    """
    return APIError(
        400,
        "Not a valid identifier. Pass a task key such as ENG-142 or a uuid.",
        code=INVALID_IDENTIFIER_CODE,
    )


def _path_segment(value: Any) -> str:
    """One validated path segment: a key, a uuid or a slug — never `/`, `..`, `?`, `#`."""
    text: str = str(value)
    if not TASKS_PATH_SEGMENT_RE.match(text):
        raise _invalid_identifier()
    return text


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

        response: httpx.Response = self._guard_transport(
            lambda: httpx.request(method, url, **kwargs), method=method
        )

        if _is_auth_retryable(response):
            alt: dict[str, str] | None = self._alt_auth_headers()
            if alt is not None:
                kwargs["headers"] = alt
                response = self._guard_transport(
                    lambda: httpx.request(method, url, **kwargs), method=method
                )

        return response

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        extra_headers: dict[str, str] | None = None,
        content: bytes | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
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
        headers: dict[str, str] = self._headers()
        if files is not None:
            # A multipart body sets its own Content-Type (with the boundary);
            # the JSON default would make the server misread it.
            headers.pop("Content-Type", None)
        if extra_headers:
            headers.update(extra_headers)
        kwargs: dict[str, Any] = {
            "headers": headers,
            "timeout": self.timeout if timeout is None else timeout,
        }
        if params is not None:
            kwargs["params"] = params
        if json is not None:
            kwargs["json"] = json
        if content is not None:
            kwargs["content"] = content
        if files is not None:
            kwargs["files"] = files
        if data is not None:
            kwargs["data"] = data

        response: httpx.Response = self._dispatch_guarded(method, url, **kwargs)

        if _is_auth_retryable(response) and not self._is_final_person_refusal(url, response):
            alt: dict[str, str] | None = self._alt_auth_headers()
            if alt is not None:
                retry_headers: dict[str, str] = dict(alt)
                if files is not None:
                    retry_headers.pop("Content-Type", None)
                if extra_headers:
                    retry_headers.update(extra_headers)
                kwargs["headers"] = retry_headers
                response = self._dispatch_guarded(method, url, **kwargs)

        return response

    def _is_final_person_refusal(self, url: str, response: httpx.Response) -> bool:
        """A Tasks door that refused the signed-in person keeps that answer.

        On Tasks a 403 to a Bearer session means the *person* lacks the role or the
        visibility. Replaying the call with the organization API key would perform,
        as the organization, exactly what the person was refused, and attribute it
        to nobody. So the retry is kept for the other direction only: a key refused
        on a person-only door (`insufficient_scope` / `actor_required`) may still
        retry as the person, and a 401 (an expired session) still falls back.
        """
        return (
            response.status_code == 403
            and self._agent_auth_mode == "bearer"
            and urlsplit(url).path.startswith(TASKS_BASE_PATH)
        )

    def _transport_message(self, exc: Exception, *, method: str, mutates: bool = True) -> str:
        """Explain a transport failure in terms the reader can act on.

        The failure modes are kept distinct because the fixes differ: an
        unreachable host is a connection or a wrong URL, a timeout on a **write**
        may already have been applied, and a malformed URL is a configuration
        problem the user can locate.

        ``mutates`` is False for a POST that provably writes nothing — a destructive
        **preview** (``?dry_run=true``) is a POST that creates no rows and no audit
        events. Telling the operator their archive "may have been applied" when it
        provably was not sends them into recovery for a mutation that never ran.
        """
        host: str = self.api_url
        if isinstance(exc, (httpx.UnsupportedProtocol, httpx.InvalidURL)):
            return (
                f"The configured API URL is not usable: {host!r}. Check `--api-url`, "
                "`DAILYBOT_API_URL`, `.dailybot/env.json` (`dailybot env show`) or "
                "`dailybot config`."
            )
        if isinstance(exc, httpx.TimeoutException):
            if mutates and method.upper() in {"POST", "PATCH", "PUT", "DELETE"}:
                return (
                    f"The request to {host} timed out. It **may have been applied** — a "
                    "write that times out is not known to have failed, so check the "
                    "current state before retrying."
                )
            return f"The request to {host} timed out. Check your connection and retry."
        return (
            f"Could not reach Dailybot at {host}. Check your connection, or whether that "
            "is the right server (`dailybot env show`, or pass `--api-url`)."
        )

    @staticmethod
    def _transport_class(exc: Exception) -> type[TransportError]:
        """Pick the wrapper that keeps the original handler catching it."""
        return TransportTimeout if isinstance(exc, httpx.TimeoutException) else TransportError

    def _guard_transport(
        self,
        send: Callable[[], httpx.Response],
        *,
        method: str,
        mutates: bool = True,
        timeout_message: str | None = None,
    ) -> httpx.Response:
        """Run ``send`` and convert any transport failure into a ``TransportError``.

        The call-site-preserving twin of :meth:`_dispatch_guarded`: the agent and
        login endpoints call ``httpx.request`` / ``httpx.post`` directly and the
        test suite patches exactly those, so they cannot be routed through the
        per-method dispatcher. They still need the same net — without it a dead
        host made ``dailybot agent update`` exit 1 with "Unexpected error" instead
        of the documented transport exit.
        """
        try:
            return send()
        except httpx.HTTPError as exc:
            if timeout_message and isinstance(exc, httpx.TimeoutException):
                raise TransportTimeout(timeout_message) from exc
            raise self._transport_class(exc)(
                self._transport_message(exc, method=method.upper(), mutates=mutates)
            ) from exc

    def _dispatch_guarded(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """`_dispatch_http` with every transport failure converted to a CLI error.

        The raw dispatcher stays a ``@staticmethod`` with its long-standing
        per-method patchable surface, because the test suite patches
        ``httpx.get`` / ``httpx.post`` directly and asserts the routing. The
        guard lives here so the routing contract is untouched.
        """
        # A `dry_run=true` POST provably writes nothing, so its timeout must not
        # claim the operation may have been applied.
        params: Any = kwargs.get("params") or {}
        mutates: bool = not (
            isinstance(params, dict) and str(params.get("dry_run")).lower() in {"true", "1"}
        )
        try:
            return self._dispatch_http(method, url, **kwargs)
        except httpx.HTTPError as exc:
            # No retry on purpose. The bounded 429 backoff in `_send_with_retry`
            # is the only retry this client has; silently retrying a connection
            # failure would hide an outage from the caller who owns that decision,
            # and could double-post a non-idempotent write.
            raise self._transport_class(exc)(
                self._transport_message(exc, method=method.upper(), mutates=mutates)
            ) from exc

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
        try:
            return response.json()
        except Exception as exc:
            # A 2xx whose body is not JSON: a captive portal, a proxy error page,
            # an HTML 200. The error branch above already guards its own decode;
            # this path did not, so a bare JSONDecodeError escaped to the user.
            raise TransportError(
                f"The server returned an unreadable response: {_fallback_detail(response)}"
            ) from exc

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
            try:
                body: Any = response.json()
            except Exception as exc:
                # Same unreadable-2xx case `_handle_response` guards (a captive
                # portal, a proxy HTML 200). List reads bypass that helper on the
                # success path, so without this they surfaced a bare
                # JSONDecodeError and exited 1 instead of the documented 8.
                raise TransportError(
                    f"The server returned an unreadable response: {_fallback_detail(response)}"
                ) from exc
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
            current_url = self._same_api_origin(next_url) if next_url else None

        return PaginatedResult(results=collected, count=count, next=next_url, previous=previous)

    # --- Auth endpoints ---

    def request_code(self, email: str) -> dict[str, Any]:
        """POST /v1/cli/auth/request-code/"""
        response: httpx.Response = self._guard_transport(
            lambda: httpx.post(
                f"{self.api_url}/v1/cli/auth/request-code/",
                json={"email": email},
                headers=self._headers(authenticated=False),
                timeout=self.timeout,
            ),
            method="POST",
            # The generic write advice — "check the current state before retrying" —
            # is actively harmful here. Requesting a code again INVALIDATES the one
            # already sent (AGENTS.md DON'T #17), so a user who retries on a timeout
            # burns the code sitting in their inbox.
            timeout_message=(
                "The request timed out, but the code may already have been sent. "
                "Check your inbox first: asking for another code invalidates the one "
                "you have."
            ),
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
        response: httpx.Response = self._guard_transport(
            lambda: httpx.post(
                f"{self.api_url}/v1/cli/auth/verify-code/",
                json=payload,
                headers=self._headers(authenticated=False),
                timeout=self.timeout,
            ),
            method="POST",
            # A timeout here may have CONSUMED the code without returning a token.
            # "Check the state and retry" would send the user back with a spent code.
            timeout_message=(
                "The request timed out. The code may already have been used, so "
                "verifying it again can fail: run `dailybot login` to request a new one."
            ),
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
        response: httpx.Response = self._guard_transport(
            lambda: httpx.post(
                f"{self.api_url}/v1/cli/auth/logout/",
                headers=self._headers(),
                timeout=self.timeout,
            ),
            method="POST",
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
        labels: list[str] | None = None,
        featured: bool | None = None,
        prioritize_featured: bool | None = None,
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
        _merge_dashboard_enrichment_query(
            params,
            labels=labels,
            featured=featured,
            prioritize_featured=prioritize_featured,
        )
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
        labels: list[str] | None = None,
        featured: bool | None = None,
        prioritize_featured: bool | None = None,
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
        _merge_dashboard_enrichment_query(
            params,
            labels=labels,
            featured=featured,
            prioritize_featured=prioritize_featured,
        )
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
        labels: list[str] | None = None,
        featured: bool | None = None,
        prioritize_featured: bool | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/workflows/ — list workflows (plan-gated feature)."""
        params: dict[str, Any] = {}
        _merge_list_query(params, search=search, start_date=start_date, end_date=end_date)
        _merge_dashboard_enrichment_query(
            params,
            labels=labels,
            featured=featured,
            prioritize_featured=prioritize_featured,
        )
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

    # --- Organization Labels (/v1/labels/) ---

    # ------------------------------------------------------------------
    # Tasks (/v1/tasks/*)
    #
    # Contract of record: the API handoff pack under
    # .dwp/handoffs/PLAN_tasks_api_cli_enablement/analysis_results/.
    # Three rules govern this whole section:
    #   * every datetime in a query goes through `as_query_datetime` (the
    #     `+00:00` trap — MEASURED_ANSWERS.md §4);
    #   * `Idempotency-Key` is sent ONLY on the doors IDEMPOTENCY.md marks
    #     `accepted` or `required` — advertising it on an `ignored` door would
    #     promise a guarantee the server does not honour;
    #   * every door stays in the read timeout tier (docs/PERFORMANCE.md §2
    #     says a new endpoint is read-tier by default; none of these runs
    #     server-side AI processing).
    # ------------------------------------------------------------------

    def _tasks_url(self, path: str) -> str:
        """Build an absolute URL under the Tasks base path.

        Every segment is re-checked here as well as at interpolation
        (`_path_segment`): a door built without the helper still cannot be
        steered by `..`, `?`, `#` or `%`.
        """
        relative: str = path.lstrip("/")
        for segment in relative.rstrip("/").split("/"):
            if not TASKS_PATH_SEGMENT_RE.match(segment):
                raise _invalid_identifier()
        return f"{self.api_url}{TASKS_BASE_PATH}{relative}"

    def _tasks_write(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        idempotent: bool = False,
        idempotency_key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Issue a Tasks write and surface the replay flag.

        ``idempotent`` reflects the door's posture in IDEMPOTENCY.md, not the
        caller's preference: when it is False no key is sent, even if one was
        supplied, because the server ignores it there.

        A generated key is a uuid4. It must be unguessable: the idempotency slot
        is keyed on ``(organization, scope, key)``, so two different keys in the
        same organization **share a namespace** (MEASURED_ANSWERS.md §6 Q5) and a
        sequential default would collide between two agents.
        """
        extra: dict[str, str] | None = dict(headers) if headers else None
        sent_key: str | None = None
        # A `dry_run=true` call writes nothing, so it has nothing to make idempotent —
        # and returning a key for it invites the caller to reuse that key for the real
        # mutation, whose payload differs (`idempotency_key_payload_mismatch`).
        previewing: bool = bool(params) and str((params or {}).get("dry_run", "")).lower() in {
            "true",
            "1",
        }
        if idempotent and not previewing:
            sent_key = idempotency_key or str(uuid.uuid4())
            extra = {**(extra or {}), IDEMPOTENCY_KEY_HEADER: sent_key}
        try:
            response: httpx.Response = self._request(
                method, self._tasks_url(path), json=json, params=params, extra_headers=extra
            )
            result: Any = self._handle_response(response)
        except TransportError as exc:
            # Two paths reach here and NEITHER has a body to recover the key from:
            # a timeout, and an unreadable 2xx (a captive portal's HTML 200), which
            # `_handle_response` also raises as a transport failure. In both the
            # write may already have been applied, so a blind retry mints a fresh
            # uuid4 the server cannot replay — and duplicates. Guarding only the
            # request left the second path silently uncovered.
            if sent_key is not None and exc.idempotency_key is None:
                exc.idempotency_key = sent_key
            raise
        replayed: str = str(getattr(response, "headers", {}).get(IDEMPOTENCY_REPLAYED_HEADER, ""))
        if isinstance(result, dict):
            result[IDEMPOTENCY_REPLAYED_KEY] = replayed.lower() == "true"
            if sent_key is not None:
                # The generated key has to leave the client, or the safety it buys
                # is unreachable: re-running the command mints a NEW uuid4, so a
                # retry after a timeout duplicates. Surfacing it is what makes the
                # documented "a retry cannot create a second task" true.
                result[IDEMPOTENCY_KEY_SENT_KEY] = sent_key
        return result

    def _tasks_read(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Issue a Tasks read (single object or non-paginated document)."""
        return self._handle_response(self._request("GET", self._tasks_url(path), params=params))

    def _tasks_read_with_etag(self, path: str) -> tuple[Any, str | None]:
        """A Tasks read that also returns the response's `ETag` validator.

        The saved-view doors replace a whole array and demand `If-Match`; the
        validator is only available from the read, so it has to leave with it.
        """
        response: httpx.Response = self._request("GET", self._tasks_url(path))
        data: Any = self._handle_response(response)
        etag: Any = getattr(response, "headers", {}).get("ETag")
        if not etag:
            return data, None
        if not ETAG_RE.match(str(etag)):
            raise APIError(
                502,
                "The server sent an ETag that is not a valid entity tag; it was not used.",
                code=INVALID_ETAG_CODE,
            )
        return data, str(etag)

    @staticmethod
    def _checked_if_match(if_match: str) -> str:
        """An `If-Match` value, refused locally unless it is a well-formed entity tag."""
        if not ETAG_RE.match(if_match):
            raise APIError(
                400,
                'Not a valid ETag. Pass the value `views --etag` printed, e.g. "abc123".',
                code=INVALID_ETAG_CODE,
            )
        return if_match

    def _tasks_list(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        page: int | None = None,
        page_size: int | None = None,
        fetch_all: bool = False,
        limit: int | None = None,
    ) -> PaginatedResult:
        """Issue a Tasks list read through the shared pagination helper."""
        return self._paginated_get(
            self._tasks_url(path),
            params=params,
            page=page,
            page_size=page_size,
            fetch_all=fetch_all,
            limit=limit,
        )

    @staticmethod
    def _with_include(
        params: dict[str, Any] | None, include: list[str] | None
    ) -> dict[str, Any] | None:
        """Merge an ``include`` selector into a caller's query params.

        They used to compete: these methods hardcoded ``params={"include": …}``, so
        a caller forwarding the shared query flags via ``params=`` either collided
        or had its filters silently dropped.
        """
        merged: dict[str, Any] = dict(params) if params else {}
        if include:
            merged["include"] = ",".join(include)
        return merged or None

    # --- Workspace-level reads ---

    def get_tasks_pulse(self, *, include: list[str] | None = None) -> dict[str, Any]:
        """GET /v1/tasks/pulse/ — the workspace snapshot an agent reads first.

        `include` asks for the extra bands (projects, attention, activity,
        goal_progress) in the same single request.
        """
        params: dict[str, Any] | None = {"include": ",".join(include)} if include else None
        return self._tasks_read("pulse/", params=params)

    def mark_inbox_item_read(self, item_uuid: str) -> dict[str, Any]:
        """POST /v1/tasks/inbox/<uuid>/read/ — person-only; marks it AND everything older."""
        result: dict[str, Any] = self._tasks_write(
            "POST", f"inbox/{_path_segment(item_uuid)}/read/"
        )
        return result

    def mark_inbox_read_all(self) -> dict[str, Any]:
        """POST /v1/tasks/inbox/read-all/ — person-only."""
        result: dict[str, Any] = self._tasks_write("POST", "inbox/read-all/")
        return result

    def get_activity_cursor(self) -> dict[str, Any]:
        """GET /v1/tasks/me/activity-cursor/ — person-only; `last_seen_at` or null."""
        return self._tasks_read("me/activity-cursor/")

    def set_activity_cursor(self, last_seen_at: str) -> dict[str, Any]:
        """PUT /v1/tasks/me/activity-cursor/ — person-only; "I have read up to here"."""
        result: dict[str, Any] = self._tasks_write(
            "PUT", "me/activity-cursor/", json={"last_seen_at": last_seen_at}
        )
        return result

    def list_favorites(self) -> Any:
        """GET /v1/tasks/me/favorites/ — the caller's pinned boards and views (person-only)."""
        return self._tasks_read("me/favorites/")

    def add_favorite(
        self, *, target_type: str, target_uuid: str, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """POST /v1/tasks/me/favorites/ — pin a board or a view; re-pinning returns the pin."""
        result: dict[str, Any] = self._tasks_write(
            "POST",
            "me/favorites/",
            json={"target_type": target_type, "target_uuid": target_uuid},
            idempotent=True,
            idempotency_key=idempotency_key,
        )
        return result

    def delete_favorite(self, favorite_uuid: str) -> Any:
        """DELETE /v1/tasks/me/favorites/<uuid>/ — unpin; never touches the target."""
        return self._tasks_write("DELETE", f"me/favorites/{_path_segment(favorite_uuid)}/")

    def get_view(self, view_uuid: str) -> dict[str, Any]:
        """GET /v1/tasks/views/<uuid>/ — one saved view (person-only)."""
        return self._tasks_read(f"views/{_path_segment(view_uuid)}/")

    def update_view(self, view_uuid: str, **fields: Any) -> dict[str, Any]:
        """PATCH /v1/tasks/views/<uuid>/ — partial; shared views need a board manager."""
        result: dict[str, Any] = self._tasks_write(
            "PATCH",
            f"views/{_path_segment(view_uuid)}/",
            json={k: v for k, v in fields.items() if v is not None},
        )
        return result

    def delete_view(self, view_uuid: str) -> Any:
        """DELETE /v1/tasks/views/<uuid>/ — permanent."""
        return self._tasks_write("DELETE", f"views/{_path_segment(view_uuid)}/")

    def list_board_mentionables(self, board_uuid: str) -> Any:
        """GET /v1/tasks/boards/<uuid>/mentionables/ — who this viewer may @mention."""
        return self._tasks_read(f"boards/{_path_segment(board_uuid)}/mentionables/")

    def get_tasks_entitlements(self) -> dict[str, Any]:
        """GET /v1/tasks/entitlements/ — never answers 402 by contract."""
        return self._tasks_read("entitlements/")

    def search_tasks(self, query: str, **page: Any) -> PaginatedResult:
        """GET /v1/tasks/search/?q= — full-text search across the surface.

        A query over the ceiling is **refused**, not truncated. Truncating returned
        results for a query the caller never typed, with exit 0 — so they would
        conclude the text is absent from the workspace. Every other search path in
        this client already raises here.
        """
        if len(query) > MAX_SEARCH_QUERY_LENGTH:
            raise APIError(
                400,
                f"Search query is too long ({len(query)} chars, max {MAX_SEARCH_QUERY_LENGTH}).",
                code="search_query_too_long",
            )
        return self._tasks_list("search/", params={"q": query}, **page)

    def list_tasks_activity(self, **page: Any) -> PaginatedResult:
        """GET /v1/tasks/activity/ — the catch-up feed after an absence."""
        return self._tasks_list("activity/", **page)

    def list_tasks_timeline(
        self, *, date_from: str | None = None, date_to: str | None = None, **page: Any
    ) -> PaginatedResult:
        """GET /v1/tasks/timeline/ — a dated view of the workspace."""
        params: dict[str, Any] = {}
        if date_from:
            params["from"] = date_from
        if date_to:
            params["to"] = date_to
        return self._tasks_list("timeline/", params=params or None, **page)

    # --- Boards ---

    def list_boards(self, **page: Any) -> PaginatedResult:
        """GET /v1/tasks/boards/."""
        return self._tasks_list("boards/", **page)

    def list_board_tasks(
        self, board_uuid: str, *, filters: dict[str, Any] | None = None, **page: Any
    ) -> PaginatedResult:
        """GET /v1/tasks/boards/<uuid>/tasks/ — one board's tasks, paginated."""
        return self._tasks_list(
            f"boards/{_path_segment(board_uuid)}/tasks/", params=filters, **page
        )

    def list_board_states(self, board_uuid: str, *, include_archived: bool = False) -> Any:
        """GET /v1/tasks/boards/<uuid>/states/ — the board's live columns.

        Retired columns are only returned with ``include_archived``.
        """
        params: dict[str, Any] | None = {"include_archived": "true"} if include_archived else None
        return self._tasks_read(f"boards/{_path_segment(board_uuid)}/states/", params=params)

    def list_board_members(self, board_uuid: str) -> Any:
        """GET /v1/tasks/boards/<uuid>/members/ — who can see the board."""
        return self._tasks_read(f"boards/{_path_segment(board_uuid)}/members/")

    def list_board_labels(self, board_uuid: str) -> Any:
        """GET /v1/tasks/boards/<uuid>/labels/ — person-only (usage counts are per viewer)."""
        return self._tasks_read(f"boards/{_path_segment(board_uuid)}/labels/")

    def list_board_views(self, board_uuid: str) -> Any:
        """GET /v1/tasks/boards/<uuid>/views/ — saved views on the board."""
        return self._tasks_read(f"boards/{_path_segment(board_uuid)}/views/")

    def list_board_views_with_etag(self, board_uuid: str) -> tuple[Any, str | None]:
        """GET /v1/tasks/boards/<uuid>/views/ plus the `ETag` a save must send back."""
        return self._tasks_read_with_etag(f"boards/{_path_segment(board_uuid)}/views/")

    def save_board_views(self, board_uuid: str, views: list[Any], *, if_match: str) -> Any:
        """PUT /v1/tasks/boards/<uuid>/views/ — replaces the caller's WHOLE view array.

        Person-only. `If-Match` is required by the server (412 stale, 428 absent)
        because two concurrent saves would otherwise drop each other's views.
        """
        return self._tasks_write(
            "PUT",
            f"boards/{_path_segment(board_uuid)}/views/",
            json=views,
            headers={"If-Match": self._checked_if_match(if_match)},
        )

    def create_board_state(
        self, board_uuid: str, *, idempotency_key: str | None = None, **fields: Any
    ) -> Any:
        """POST /v1/tasks/boards/<uuid>/states/ — `position` inserts; accepts a key."""
        payload: dict[str, Any] = {k: v for k, v in fields.items() if v is not None}
        return self._tasks_write(
            "POST",
            f"boards/{_path_segment(board_uuid)}/states/",
            json=payload,
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def update_board_state(self, board_uuid: str, state_uuid: str, **fields: Any) -> Any:
        """PATCH …/states/<uuid>/ — name, color and position only; no key accepted."""
        payload: dict[str, Any] = {k: v for k, v in fields.items() if v is not None}
        return self._tasks_write(
            "PATCH",
            f"boards/{_path_segment(board_uuid)}/states/{_path_segment(state_uuid)}/",
            json=payload,
        )

    def archive_board_state(
        self,
        board_uuid: str,
        state_uuid: str,
        *,
        migrate_to: str | None = None,
        dry_run: bool = False,
    ) -> Any:
        """POST …/states/<uuid>/archive/ — retire a column; `migrate_to` moves its cards."""
        return self._tasks_write(
            "POST",
            f"boards/{_path_segment(board_uuid)}/states/{_path_segment(state_uuid)}/archive/",
            json={"migrate_to": migrate_to} if migrate_to else None,
            params={"dry_run": "true"} if dry_run else None,
        )

    def restore_board_state(self, board_uuid: str, state_uuid: str) -> Any:
        """POST …/states/<uuid>/restore/ — the column returns after the live ones."""
        return self._tasks_write(
            "POST",
            f"boards/{_path_segment(board_uuid)}/states/{_path_segment(state_uuid)}/restore/",
        )

    def reorder_board_states(self, board_uuid: str, order: list[str]) -> Any:
        """POST …/states/reorder/ — `order` must list every live column exactly once."""
        return self._tasks_write(
            "POST", f"boards/{_path_segment(board_uuid)}/states/reorder/", json={"order": order}
        )

    def add_board_member(
        self, board_uuid: str, user_uuid: str, *, idempotency_key: str | None = None
    ) -> Any:
        """POST …/members/ — person-only (`tasks:admin`); 200 when already a member."""
        return self._tasks_write(
            "POST",
            f"boards/{_path_segment(board_uuid)}/members/",
            json={"user_uuid": user_uuid},
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def remove_board_member(self, board_uuid: str, user_uuid: str) -> Any:
        """DELETE …/members/<user>/ — person-only; the last member of a private board stays."""
        return self._tasks_write(
            "DELETE", f"boards/{_path_segment(board_uuid)}/members/{_path_segment(user_uuid)}/"
        )

    def create_board_label(self, board_uuid: str, *, name: str, **fields: Any) -> Any:
        """POST …/labels/ — person-only; creates an organization label from the board."""
        payload: dict[str, Any] = {
            "name": name,
            **{k: v for k, v in fields.items() if v is not None},
        }
        return self._tasks_write(
            "POST", f"boards/{_path_segment(board_uuid)}/labels/", json=payload
        )

    def get_board(self, board_uuid: str) -> dict[str, Any]:
        """GET /v1/tasks/boards/<uuid>/."""
        return self._tasks_read(f"boards/{_path_segment(board_uuid)}/")

    def get_board_snapshot(self, board_uuid: str) -> dict[str, Any]:
        """GET /v1/tasks/boards/<uuid>/board/ — the dense cold-context door.

        Carries ``delta_cursor``, which is the only place a caller can obtain a
        cursor for :meth:`get_board_delta`; the delta door's own 400 does not
        say where to get one.
        """
        return self._tasks_read(f"boards/{_path_segment(board_uuid)}/board/")

    def get_board_delta(self, board_uuid: str, *, updated_since: datetime | str) -> dict[str, Any]:
        """GET /v1/tasks/boards/<uuid>/delta/ — the poll-loop door.

        Refuses three different things (MEASURED_ANSWERS.md §4): a missing
        cursor, a cursor older than the 7-day window
        (``delta_window_expired`` + ``full_resync_required``), and a cursor it
        cannot parse. Only the second is recoverable, and only by re-snapshotting.
        """
        return self._tasks_read(
            f"boards/{_path_segment(board_uuid)}/delta/",
            params={"updated_since": as_query_datetime(updated_since)},
        )

    # --- Tasks ---

    def list_tasks(self, *, filters: dict[str, Any] | None = None, **page: Any) -> PaginatedResult:
        """GET /v1/tasks/tasks/ — strict about parameters; only declared ones."""
        return self._tasks_list("tasks/", params=filters, **page)

    def get_task(self, task_uuid: str) -> dict[str, Any]:
        """GET /v1/tasks/tasks/<uuid>/ — the most frequent call of all."""
        return self._tasks_read(f"tasks/{_path_segment(task_uuid)}/")

    def create_task(
        self,
        *,
        title: str,
        board: str | None = None,
        idempotency_key: str | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """POST /v1/tasks/tasks/ — always this path. Accepts an idempotency key.

        The board-scoped door exists on the server; this client does not use it.
        `board` travels in the payload, so a caller looking for a path variant here
        will not find one.
        """
        payload: dict[str, Any] = {
            "title": title,
            **{k: v for k, v in fields.items() if v is not None},
        }
        if board:
            payload["board"] = board
        return self._tasks_write(
            "POST", "tasks/", json=payload, idempotent=True, idempotency_key=idempotency_key
        )

    def update_task(
        self, task_uuid: str, *, idempotency_key: str | None = None, **fields: Any
    ) -> dict[str, Any]:
        """PATCH /v1/tasks/tasks/<uuid>/ — absolute fields; accepts a key."""
        payload: dict[str, Any] = {k: v for k, v in fields.items() if v is not None}
        return self._tasks_write(
            "PATCH",
            f"tasks/{_path_segment(task_uuid)}/",
            json=payload,
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def move_task_to_board(
        self, task_uuid: str, *, board: str, state: str | None = None
    ) -> dict[str, Any]:
        """POST /v1/tasks/tasks/<uuid>/move-board/ — cross-board; no key accepted.

        Without `state` the server picks the column with the same category on the
        target board.
        """
        payload: dict[str, Any] = {"board": board}
        if state:
            payload["state"] = state
        result: dict[str, Any] = self._tasks_write(
            "POST", f"tasks/{_path_segment(task_uuid)}/move-board/", json=payload
        )
        return result

    def move_task(
        self, task_uuid: str, *, idempotency_key: str | None = None, **fields: Any
    ) -> dict[str, Any]:
        """POST /v1/tasks/tasks/<uuid>/move/ — accepts a key."""
        return self._tasks_write(
            "POST",
            f"tasks/{_path_segment(task_uuid)}/move/",
            json={k: v for k, v in fields.items() if v is not None},
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def archive_task(
        self, task_uuid: str, *, dry_run: bool = False, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """POST /v1/tasks/tasks/<uuid>/archive/ — reversible; accepts a key.

        With ``dry_run`` the server previews the consequence and writes no rows
        and no audit events (BLAST_RADIUS.md).
        """
        return self._tasks_write(
            "POST",
            f"tasks/{_path_segment(task_uuid)}/archive/",
            params={"dry_run": "true"} if dry_run else None,
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def restore_task(self, task_uuid: str, *, idempotency_key: str | None = None) -> dict[str, Any]:
        """POST /v1/tasks/tasks/<uuid>/restore/ — accepts a key."""
        return self._tasks_write(
            "POST",
            f"tasks/{_path_segment(task_uuid)}/restore/",
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def subscribe_task(self, task_uuid: str) -> dict[str, Any]:
        """POST /v1/tasks/tasks/<uuid>/subscription/ — person-only; no key accepted."""
        return self._tasks_write(
            "POST", f"tasks/{_path_segment(task_uuid)}/subscription/", idempotent=False
        )

    def bulk_tasks(
        self,
        *,
        operation: str,
        items: list[dict[str, Any]],
        board: str | None = None,
        dry_run: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/tasks/tasks/bulk/ — the ONE door that REQUIRES a key.

        Without the header the server answers ``400 idempotency_key_required``, so
        the real call always sends one. ``dry_run`` asks the server to run the batch
        and roll it back: no key is sent, and nothing is written. `create`
        needs the target ``board`` at the top of the body.
        """
        payload: dict[str, Any] = {"operation": operation, "items": items}
        if board is not None:
            payload["board"] = board
        result: dict[str, Any] = self._tasks_write(
            "POST",
            "tasks/bulk/",
            json=payload,
            params={"dry_run": "true"} if dry_run else None,
            idempotent=True,
            idempotency_key=idempotency_key,
        )
        return result

    # --- Collaboration ---

    def comment_on_task(
        self, task_uuid: str, *, body: str, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """POST /v1/tasks/tasks/<uuid>/comments/ — accepts a key."""
        return self._tasks_write(
            "POST",
            f"tasks/{_path_segment(task_uuid)}/comments/",
            json={"body": body},
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def list_task_comments(
        self, task_uuid: str, *, params: dict[str, Any] | None = None, **page: Any
    ) -> PaginatedResult:
        """GET /v1/tasks/tasks/<uuid>/comments/."""
        return self._tasks_list(
            f"tasks/{_path_segment(task_uuid)}/comments/", params=params, **page
        )

    def relate_tasks(
        self, task_uuid: str, *, other: str, relation: str, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """POST /v1/tasks/tasks/<uuid>/relations/ — accepts a key."""
        return self._tasks_write(
            "POST",
            f"tasks/{_path_segment(task_uuid)}/relations/",
            json={"relation_type": relation, "target_task": other},
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def batch_task_labels(
        self, task_uuid: str, *, mode: str, labels: list[str], idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """POST /v1/tasks/tasks/<uuid>/labels/batch/ — accepts a key."""
        return self._tasks_write(
            "POST",
            f"tasks/{_path_segment(task_uuid)}/labels/batch/",
            json={"mode": mode, "labels": labels},
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def add_task_participant(
        self,
        task_uuid: str,
        *,
        user_uuid: str,
        role: str | None = None,
        is_muted: bool | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/tasks/tasks/<uuid>/participants/ — person-only; accepts a key.

        The same door sets `role` (participant or watcher) and `is_muted`: posting
        yourself with `is_muted` is how a mute is recorded, and the row is kept.
        Posting someone already on the card answers 200 with their row.
        """
        payload: dict[str, Any] = {"user_uuid": user_uuid}
        if role is not None:
            payload["role"] = role
        if is_muted is not None:
            payload["is_muted"] = is_muted
        result: dict[str, Any] = self._tasks_write(
            "POST",
            f"tasks/{_path_segment(task_uuid)}/participants/",
            json=payload,
            idempotent=True,
            idempotency_key=idempotency_key,
        )
        return result

    def list_task_participants(self, task_uuid: str) -> Any:
        """GET /v1/tasks/tasks/<uuid>/participants/ — who is on the card, and watchers."""
        return self._tasks_read(f"tasks/{_path_segment(task_uuid)}/participants/")

    def remove_task_participant(self, task_uuid: str, user_uuid: str) -> Any:
        """DELETE …/participants/<user>/ — person-only. Leaving is not muting."""
        return self._tasks_write(
            "DELETE", f"tasks/{_path_segment(task_uuid)}/participants/{_path_segment(user_uuid)}/"
        )

    def unsubscribe_task(self, task_uuid: str) -> Any:
        """DELETE /v1/tasks/tasks/<uuid>/subscription/ — person-only; stop watching."""
        return self._tasks_write("DELETE", f"tasks/{_path_segment(task_uuid)}/subscription/")

    # --- Attachments ---

    def _is_api_origin(self, url: str) -> bool:
        """True only when `url` has exactly the configured API's scheme, host and port.

        A prefix or suffix comparison would let `api.example.com.evil.example`
        through; comparing the parsed origin does not.
        """
        return self._origin(url) == self._origin(self.api_url)

    @staticmethod
    def _origin(url: str) -> tuple[str, str | None, int | None]:
        """Scheme, host and port, with the scheme's default port filled in.

        `https://api.example.com` and `https://api.example.com:443` are one origin;
        comparing the raw `.port` (None vs 443) would call them different.
        """
        parts = urlsplit(url)
        return (parts.scheme, parts.hostname, parts.port or DEFAULT_PORTS.get(parts.scheme))

    def _same_api_origin(self, url: str) -> str:
        """A pagination link, pinned to the configured API before credentials follow it.

        `next` is server data. Following it verbatim would hand the Bearer token or
        API key to whatever host it names, and a proxy that rewrites it (to
        `http://`, or to an internal host name) would break `--all`. Only its path
        and query are kept; the scheme, host and port are always the API's own.
        """
        target = urlsplit(self._absolute(url))
        api = urlsplit(self.api_url)
        return target._replace(scheme=api.scheme, netloc=api.netloc).geturl()

    def _absolute(self, url: str) -> str:
        """Resolve a relative target against the API origin."""
        return urljoin(self.api_url.rstrip("/") + "/", url)

    def _may_send_to_foreign(self, url: str) -> bool:
        """A foreign target must be https, unless the API itself is plain http (local dev)."""
        return urlsplit(url).scheme == "https" or urlsplit(self.api_url).scheme == "http"

    def presign_attachment(
        self, task_uuid: str, *, filename: str, content_type: str, size: int
    ) -> dict[str, Any]:
        """POST …/attachments/presign/ — reserve an attachment and get an upload target."""
        result: dict[str, Any] = self._tasks_write(
            "POST",
            f"tasks/{_path_segment(task_uuid)}/attachments/presign/",
            json={"filename": filename, "content_type": content_type, "size": size},
        )
        return result

    def upload_attachment_bytes(self, presign: dict[str, Any], data: bytes) -> Any:
        """Send the bytes to the presign's target. Credentials never leave the API origin.

        * Same origin (the `…/content/` fallback, or a relative URL): an ordinary
          authenticated request, with the presign's headers on top.
        * Any other host (object storage): a bare request carrying ONLY the
          presign's headers — no `Authorization`, no `X-API-KEY` — that never
          follows a redirect. A 3xx is refused rather than re-sent anywhere.
        """
        url: str = self._absolute(str(presign.get("upload_url") or ""))
        method: str = str(presign.get("method") or "PUT").upper()
        headers: dict[str, str] = {
            str(k): str(v) for k, v in (presign.get("headers") or {}).items()
        }
        if self._is_api_origin(url):
            return self._handle_response(
                self._request(
                    method,
                    url,
                    content=data,
                    extra_headers=headers,
                    timeout=ATTACHMENT_TRANSFER_TIMEOUT_SECS,
                )
            )
        if not self._may_send_to_foreign(url):
            # Not the caller's input and not retryable: the server handed back a
            # target this client will not send a file to. 502 keeps it off the
            # "bad input" (2) and "back off" (6) exits.
            raise APIError(
                502,
                "The upload target is not https, so the file was not sent.",
                code="attachment_upload_target_refused",
            )
        try:
            response: httpx.Response = httpx.request(
                method,
                url,
                content=data,
                headers=headers,
                timeout=ATTACHMENT_TRANSFER_TIMEOUT_SECS,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise TransportError(f"Could not upload the file to storage: {exc}") from exc
        if 300 <= response.status_code < 400:
            raise APIError(
                response.status_code,
                "The storage target answered with a redirect; it was not followed.",
                code="attachment_upload_redirected",
            )
        if response.status_code >= 400:
            raise APIError(
                response.status_code,
                f"Storage refused the upload (HTTP {response.status_code}).",
                code="attachment_upload_failed",
            )
        return {}

    def confirm_attachment(self, task_uuid: str, attachment_uuid: str) -> dict[str, Any]:
        """POST …/attachments/<uuid>/confirm/ — mark the uploaded attachment ready."""
        result: dict[str, Any] = self._tasks_write(
            "POST",
            f"tasks/{_path_segment(task_uuid)}/attachments/{_path_segment(attachment_uuid)}/confirm/",
        )
        return result

    # --- Attachments: one set of doors per parent ---------------------------
    # A task, a comment, a project and a goal each own an `attachments/`
    # collection with the same row shape. `parent` is the validated relative
    # path of the owner (`tasks/ENG-1`, `tasks/ENG-1/comments/<uuid>`,
    # `projects/<uuid>`, `goals/<uuid>`); every segment goes through
    # `_path_segment` before it gets here.

    def _upload_attachment_to(
        self,
        parent: str,
        *,
        filename: str,
        content_type: str,
        data: bytes,
        caption: str | None = None,
    ) -> dict[str, Any]:
        """POST <parent>/attachments/ as multipart: one request, capped by the server at 5 MiB."""
        return self._handle_response(
            self._request(
                "POST",
                self._tasks_url(f"{parent}/attachments/"),
                files={"file": (filename, data, content_type)},
                data={"caption": caption} if caption else None,
                timeout=ATTACHMENT_TRANSFER_TIMEOUT_SECS,
            )
        )

    def _list_attachments_of(self, parent: str) -> Any:
        """GET <parent>/attachments/."""
        return self._tasks_read(f"{parent}/attachments/")

    def _delete_attachment_of(self, parent: str, attachment_uuid: str) -> Any:
        """DELETE <parent>/attachments/<uuid>/."""
        return self._tasks_write(
            "DELETE", f"{parent}/attachments/{_path_segment(attachment_uuid)}/"
        )

    def _download_attachment_of(self, parent: str, attachment_uuid: str) -> bytes:
        """GET <parent>/attachments/<uuid>/content/: the bytes.

        The API streams the file itself. A 3xx to storage is still handled
        defensively: followed ONCE, without credentials, and no further.
        """
        url: str = self._tasks_url(
            f"{parent}/attachments/{_path_segment(attachment_uuid)}/content/"
        )
        headers: dict[str, str] = self._headers()
        outcome: bytes | str | None = self._stream_from_api(
            url, headers, can_retry=bool(self.api_key and self.token)
        )
        if outcome is None:
            # Wrong credential kind: one retry with the other, like `_request`.
            alt: dict[str, str] | None = self._alt_auth_headers()
            outcome = self._stream_from_api(url, alt or headers, can_retry=False)
        if isinstance(outcome, str):
            # A 3xx: the API handed off to storage.
            location: str = self._absolute(outcome)
            if self._is_api_origin(location) or not self._may_send_to_foreign(location):
                raise APIError(
                    302,
                    "The download redirect pointed somewhere it should not; not followed.",
                    code="attachment_download_redirected",
                )
            return self._download_from_storage(location)
        return outcome or b""

    def _stream_from_api(
        self, url: str, headers: dict[str, str], *, can_retry: bool
    ) -> bytes | str | None:
        """One streamed GET to the API under the attachment byte cap.

        Returns the bytes, a redirect `Location`, or None when the credential kind
        was refused and the caller may retry once with the other one. The body is
        counted as it arrives: `Content-Length` alone is not trusted to bound memory.
        """
        try:
            with httpx.stream(
                "GET",
                url,
                headers=headers,
                timeout=ATTACHMENT_TRANSFER_TIMEOUT_SECS,
                follow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    return str(response.headers.get("Location") or "")
                if response.status_code >= 400:
                    response.read()
                    if (
                        can_retry
                        and _is_auth_retryable(response)
                        and not self._is_final_person_refusal(url, response)
                    ):
                        return None
                    self._handle_response(response)
                received: list[bytes] = []
                total: int = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > ATTACHMENT_MAX_SIZE_BYTES:
                        raise APIError(
                            413,
                            "The attachment is larger than this CLI downloads; "
                            "nothing was written.",
                            code="attachment_too_large",
                        )
                    received.append(chunk)
                return b"".join(received)
        except httpx.HTTPError as exc:
            if isinstance(exc, TransportError):
                raise
            raise self._transport_class(exc)(
                self._transport_message(exc, method="GET", mutates=False)
            ) from exc

    @staticmethod
    def _task_parent(task_uuid: str) -> str:
        return f"tasks/{_path_segment(task_uuid)}"

    @staticmethod
    def _comment_parent(task_uuid: str, comment_uuid: str) -> str:
        return f"tasks/{_path_segment(task_uuid)}/comments/{_path_segment(comment_uuid)}"

    @staticmethod
    def _project_parent(project_uuid: str) -> str:
        return f"projects/{_path_segment(project_uuid)}"

    @staticmethod
    def _goal_parent(goal_uuid: str) -> str:
        return f"goals/{_path_segment(goal_uuid)}"

    # Task
    def upload_attachment_multipart(
        self,
        task_uuid: str,
        *,
        filename: str,
        content_type: str,
        data: bytes,
        caption: str | None = None,
    ) -> dict[str, Any]:
        """POST …/attachments/ as multipart — one request, ≤5 MiB, the door that stores a caption."""
        return self._upload_attachment_to(
            self._task_parent(task_uuid),
            filename=filename,
            content_type=content_type,
            data=data,
            caption=caption,
        )

    def list_task_attachments(self, task_uuid: str) -> Any:
        """GET /v1/tasks/tasks/<uuid>/attachments/."""
        return self._list_attachments_of(self._task_parent(task_uuid))

    def delete_task_attachment(self, task_uuid: str, attachment_uuid: str) -> Any:
        """DELETE …/attachments/<uuid>/ — also removes the stored object when unshared."""
        return self._delete_attachment_of(self._task_parent(task_uuid), attachment_uuid)

    def download_attachment(self, task_uuid: str, attachment_uuid: str) -> bytes:
        """GET …/attachments/<uuid>/content/ — the bytes of a task attachment."""
        return self._download_attachment_of(self._task_parent(task_uuid), attachment_uuid)

    # Comment (POST: the comment's author only; DELETE: uploader, author or an org admin)
    def upload_comment_attachment(
        self,
        task_uuid: str,
        comment_uuid: str,
        *,
        filename: str,
        content_type: str,
        data: bytes,
        caption: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/tasks/tasks/<t>/comments/<c>/attachments/ — multipart, ≤5 MiB."""
        return self._upload_attachment_to(
            self._comment_parent(task_uuid, comment_uuid),
            filename=filename,
            content_type=content_type,
            data=data,
            caption=caption,
        )

    def list_comment_attachments(self, task_uuid: str, comment_uuid: str) -> Any:
        """GET /v1/tasks/tasks/<t>/comments/<c>/attachments/."""
        return self._list_attachments_of(self._comment_parent(task_uuid, comment_uuid))

    def delete_comment_attachment(
        self, task_uuid: str, comment_uuid: str, attachment_uuid: str
    ) -> Any:
        """DELETE /v1/tasks/tasks/<t>/comments/<c>/attachments/<a>/."""
        return self._delete_attachment_of(
            self._comment_parent(task_uuid, comment_uuid), attachment_uuid
        )

    def download_comment_attachment(
        self, task_uuid: str, comment_uuid: str, attachment_uuid: str
    ) -> bytes:
        """GET /v1/tasks/tasks/<t>/comments/<c>/attachments/<a>/content/."""
        return self._download_attachment_of(
            self._comment_parent(task_uuid, comment_uuid), attachment_uuid
        )

    # Project (POST / DELETE: tasks:admin, a signed-in person; reads: anyone who can see it)
    def upload_project_attachment(
        self,
        project_uuid: str,
        *,
        filename: str,
        content_type: str,
        data: bytes,
        caption: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/tasks/projects/<p>/attachments/ — multipart, ≤5 MiB, tasks:admin."""
        return self._upload_attachment_to(
            self._project_parent(project_uuid),
            filename=filename,
            content_type=content_type,
            data=data,
            caption=caption,
        )

    def list_project_attachments(self, project_uuid: str) -> Any:
        """GET /v1/tasks/projects/<p>/attachments/."""
        return self._list_attachments_of(self._project_parent(project_uuid))

    def delete_project_attachment(self, project_uuid: str, attachment_uuid: str) -> Any:
        """DELETE /v1/tasks/projects/<p>/attachments/<a>/ — tasks:admin."""
        return self._delete_attachment_of(self._project_parent(project_uuid), attachment_uuid)

    def download_project_attachment(self, project_uuid: str, attachment_uuid: str) -> bytes:
        """GET /v1/tasks/projects/<p>/attachments/<a>/content/."""
        return self._download_attachment_of(self._project_parent(project_uuid), attachment_uuid)

    # Goal (POST / DELETE: tasks:admin, a signed-in person; reads: anyone who can see it)
    def upload_goal_attachment(
        self,
        goal_uuid: str,
        *,
        filename: str,
        content_type: str,
        data: bytes,
        caption: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/tasks/goals/<g>/attachments/ — multipart, ≤5 MiB, tasks:admin."""
        return self._upload_attachment_to(
            self._goal_parent(goal_uuid),
            filename=filename,
            content_type=content_type,
            data=data,
            caption=caption,
        )

    def list_goal_attachments(self, goal_uuid: str) -> Any:
        """GET /v1/tasks/goals/<g>/attachments/."""
        return self._list_attachments_of(self._goal_parent(goal_uuid))

    def delete_goal_attachment(self, goal_uuid: str, attachment_uuid: str) -> Any:
        """DELETE /v1/tasks/goals/<g>/attachments/<a>/ — tasks:admin."""
        return self._delete_attachment_of(self._goal_parent(goal_uuid), attachment_uuid)

    def download_goal_attachment(self, goal_uuid: str, attachment_uuid: str) -> bytes:
        """GET /v1/tasks/goals/<g>/attachments/<a>/content/."""
        return self._download_attachment_of(self._goal_parent(goal_uuid), attachment_uuid)

    @staticmethod
    def _download_from_storage(location: str) -> bytes:
        """The one credential-less hop to storage, streamed under a hard byte cap.

        Storage is not trusted the way the API is. Buffering the whole body before
        checking its size would let a gzip bomb or an endless chunked body exhaust
        memory, so the cap is enforced on the bytes as they arrive, the body is
        requested uncompressed, and the whole hop has a wall-clock deadline.
        """
        started: float = time.monotonic()
        received: list[bytes] = []
        total: int = 0
        try:
            with httpx.stream(
                "GET",
                location,
                headers={"Accept-Encoding": "identity"},
                timeout=ATTACHMENT_TRANSFER_TIMEOUT_SECS,
                follow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise APIError(
                        response.status_code,
                        "Storage answered with a second redirect; it was not followed.",
                        code="attachment_download_redirected",
                    )
                if response.status_code >= 400:
                    # Storage, not Dailybot, refused: a 401 here says nothing about the
                    # session, so it must not be reported as "run dailybot login".
                    raise APIError(
                        response.status_code,
                        f"Storage refused the download (HTTP {response.status_code}).",
                        code="attachment_download_failed",
                    )
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > ATTACHMENT_MAX_SIZE_BYTES:
                        raise APIError(
                            413,
                            "The attachment is larger than this CLI downloads; "
                            "nothing was written.",
                            code="attachment_too_large",
                        )
                    if time.monotonic() - started > ATTACHMENT_DOWNLOAD_DEADLINE_SECS:
                        raise TransportError(
                            "Storage took too long to send the file; nothing was written."
                        )
                    received.append(chunk)
        except httpx.HTTPError as exc:
            if isinstance(exc, TransportError):
                raise
            raise TransportError(f"Could not download the file from storage: {exc}") from exc
        return b"".join(received)

    def list_task_children(self, task_uuid: str) -> Any:
        """GET /v1/tasks/tasks/<uuid>/children/ — the task's direct sub-tasks."""
        return self._tasks_read(f"tasks/{_path_segment(task_uuid)}/children/")

    def list_task_events(self, task_uuid: str) -> Any:
        """GET /v1/tasks/tasks/<uuid>/events/ — the task's raw event history."""
        return self._tasks_read(f"tasks/{_path_segment(task_uuid)}/events/")

    def list_task_activity(
        self, task_uuid: str, *, params: dict[str, Any] | None = None, **page: Any
    ) -> PaginatedResult:
        """GET /v1/tasks/tasks/<uuid>/activity/ — one task's activity feed (R3c).

        Same envelope as the workspace feed; declares `updated_since` and `type`.
        """
        return self._tasks_list(
            f"tasks/{_path_segment(task_uuid)}/activity/", params=params, **page
        )

    def duplicate_task(
        self,
        task_uuid: str,
        *,
        include: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """POST /v1/tasks/tasks/<uuid>/duplicate/ — a copy in the same column; accepts a key.

        With no `include` the server copies title, description and labels. A replay
        with the same key returns the same copy rather than making a second one.
        """
        return self._tasks_write(
            "POST",
            f"tasks/{_path_segment(task_uuid)}/duplicate/",
            json={"include": include} if include else {},
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def list_task_relations(self, task_uuid: str) -> Any:
        """GET /v1/tasks/tasks/<uuid>/relations/ — links to other tasks, with direction."""
        return self._tasks_read(f"tasks/{_path_segment(task_uuid)}/relations/")

    def delete_task_relation(self, task_uuid: str, relation_uuid: str) -> Any:
        """DELETE …/relations/<uuid>/ — unlink two tasks; no key accepted."""
        return self._tasks_write(
            "DELETE", f"tasks/{_path_segment(task_uuid)}/relations/{_path_segment(relation_uuid)}/"
        )

    def update_task_comment(self, task_uuid: str, comment_uuid: str, *, body: str) -> Any:
        """PATCH …/comments/<uuid>/ — edit; `edited_at` is set. No key accepted."""
        return self._tasks_write(
            "PATCH",
            f"tasks/{_path_segment(task_uuid)}/comments/{_path_segment(comment_uuid)}/",
            json={"body": body},
        )

    def delete_task_comment(self, task_uuid: str, comment_uuid: str) -> Any:
        """DELETE …/comments/<uuid>/ — a soft delete: the row survives, the body is blanked."""
        return self._tasks_write(
            "DELETE", f"tasks/{_path_segment(task_uuid)}/comments/{_path_segment(comment_uuid)}/"
        )

    # --- Projects, goals, milestones ---

    def list_projects(
        self,
        *,
        include: list[str] | None = None,
        params: dict[str, Any] | None = None,
        **page: Any,
    ) -> PaginatedResult:
        """GET /v1/tasks/projects/ — roll-ups only when `include` asks for them."""
        return self._tasks_list("projects/", params=self._with_include(params, include), **page)

    def get_project(self, project_uuid: str, *, include: list[str] | None = None) -> dict[str, Any]:
        """GET /v1/tasks/projects/<uuid>/."""
        return self._tasks_read(
            f"projects/{_path_segment(project_uuid)}/", params=self._with_include(None, include)
        )

    def list_project_updates(self, project_uuid: str | None = None, **page: Any) -> PaginatedResult:
        """GET the project-update feed: the batched digest, or one project's updates."""
        path: str = (
            f"projects/{_path_segment(project_uuid)}/updates/"
            if project_uuid
            else "projects/updates/"
        )
        return self._tasks_list(path, **page)

    def post_project_update(
        self,
        project_uuid: str,
        *,
        body: str,
        health: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/tasks/projects/<uuid>/updates/ — accepts an Idempotency-Key.

        The loop-closing command: it is how the team sees what an agent did.
        `health` records the author's claim that day; it does not change the project.
        """
        payload: dict[str, Any] = {"body": body}
        if health is not None:
            payload["health"] = health
        result: dict[str, Any] = self._tasks_write(
            "POST",
            f"projects/{_path_segment(project_uuid)}/updates/",
            json=payload,
            idempotent=True,
            idempotency_key=idempotency_key,
        )
        return result

    def update_project(
        self, project_uuid: str, *, idempotency_key: str | None = None, **fields: Any
    ) -> dict[str, Any]:
        """PATCH /v1/tasks/projects/<uuid>/ — partial; `tasks:admin`; accepts a key."""
        result: dict[str, Any] = self._tasks_write(
            "PATCH",
            f"projects/{_path_segment(project_uuid)}/",
            json={k: v for k, v in fields.items() if v is not None},
            idempotent=True,
            idempotency_key=idempotency_key,
        )
        return result

    def restore_project(
        self, project_uuid: str, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """POST …/restore/ — boards and tasks that cascaded on archive stay archived."""
        result: dict[str, Any] = self._tasks_write(
            "POST",
            f"projects/{_path_segment(project_uuid)}/restore/",
            idempotent=True,
            idempotency_key=idempotency_key,
        )
        return result

    def list_project_members(self, project_uuid: str) -> Any:
        """GET /v1/tasks/projects/<uuid>/members/ — person-only."""
        return self._tasks_read(f"projects/{_path_segment(project_uuid)}/members/")

    def add_project_member(
        self, project_uuid: str, *, user_uuid: str | None = None, team_uuid: str | None = None
    ) -> Any:
        """POST …/members/ — person-only; a person OR a whole team (resolves live)."""
        payload: dict[str, Any] = (
            {"user_uuid": user_uuid} if user_uuid else {"team_uuid": team_uuid}
        )
        return self._tasks_write(
            "POST", f"projects/{_path_segment(project_uuid)}/members/", json=payload
        )

    def remove_project_member(self, project_uuid: str, user_uuid: str) -> Any:
        """DELETE …/members/<user>/ — person-only."""
        return self._tasks_write(
            "DELETE", f"projects/{_path_segment(project_uuid)}/members/{_path_segment(user_uuid)}/"
        )

    def list_project_views_with_etag(self, project_uuid: str) -> tuple[Any, str | None]:
        """GET /v1/tasks/projects/<uuid>/views/ plus the `ETag` a save must send back."""
        return self._tasks_read_with_etag(f"projects/{_path_segment(project_uuid)}/views/")

    def save_project_views(self, project_uuid: str, views: list[Any], *, if_match: str) -> Any:
        """PUT …/views/ — replaces the caller's whole view array; `If-Match` required."""
        return self._tasks_write(
            "PUT",
            f"projects/{_path_segment(project_uuid)}/views/",
            json=views,
            headers={"If-Match": self._checked_if_match(if_match)},
        )

    def create_milestone(self, project_uuid: str, *, name: str, date: str, **fields: Any) -> Any:
        """POST /v1/tasks/projects/<uuid>/milestones/ — a dated commitment; no key."""
        payload: dict[str, Any] = {
            "name": name,
            "date": date,
            **{k: v for k, v in fields.items() if v is not None},
        }
        return self._tasks_write(
            "POST", f"projects/{_path_segment(project_uuid)}/milestones/", json=payload
        )

    def update_milestone(self, project_uuid: str, milestone_uuid: str, **fields: Any) -> Any:
        """PATCH …/milestones/<uuid>/ — move or rename."""
        return self._tasks_write(
            "PATCH",
            f"projects/{_path_segment(project_uuid)}/milestones/{_path_segment(milestone_uuid)}/",
            json={k: v for k, v in fields.items() if v is not None},
        )

    def delete_milestone(self, project_uuid: str, milestone_uuid: str) -> Any:
        """DELETE …/milestones/<uuid>/ — retires (archives); tasks keep pointing at it."""
        return self._tasks_write(
            "DELETE",
            f"projects/{_path_segment(project_uuid)}/milestones/{_path_segment(milestone_uuid)}/",
        )

    def update_goal(self, goal_uuid: str, **fields: Any) -> dict[str, Any]:
        """PATCH /v1/tasks/goals/<uuid>/ — including the declared `status`; no key."""
        result: dict[str, Any] = self._tasks_write(
            "PATCH",
            f"goals/{_path_segment(goal_uuid)}/",
            json={k: v for k, v in fields.items() if v is not None},
        )
        return result

    def restore_goal(self, goal_uuid: str) -> dict[str, Any]:
        """POST …/restore/ — 409 `goal_name_conflict` when the name was reused meanwhile."""
        result: dict[str, Any] = self._tasks_write(
            "POST", f"goals/{_path_segment(goal_uuid)}/restore/"
        )
        return result

    def link_goal_project(self, goal_uuid: str, project_uuid: str) -> dict[str, Any]:
        """POST /v1/tasks/goals/<uuid>/projects/ — the project now counts toward the goal."""
        result: dict[str, Any] = self._tasks_write(
            "POST", f"goals/{_path_segment(goal_uuid)}/projects/", json={"project": project_uuid}
        )
        return result

    def unlink_goal_project(self, goal_uuid: str, project_uuid: str) -> Any:
        """DELETE …/projects/<uuid>/ — the project stops counting toward the goal."""
        return self._tasks_write(
            "DELETE", f"goals/{_path_segment(goal_uuid)}/projects/{_path_segment(project_uuid)}/"
        )

    def list_goals(
        self,
        *,
        include: list[str] | None = None,
        params: dict[str, Any] | None = None,
        **page: Any,
    ) -> PaginatedResult:
        """GET /v1/tasks/goals/ — roll-ups are ABSENT unless requested (AD-01)."""
        return self._tasks_list("goals/", params=self._with_include(params, include), **page)

    def get_goal(self, goal_uuid: str, *, include: list[str] | None = None) -> dict[str, Any]:
        """GET /v1/tasks/goals/<uuid>/."""
        return self._tasks_read(
            f"goals/{_path_segment(goal_uuid)}/", params=self._with_include(None, include)
        )

    def list_milestones(
        self, project_uuid: str | None = None, *, params: dict[str, Any] | None = None, **page: Any
    ) -> PaginatedResult:
        """GET the milestone family, org-wide or scoped to one project."""
        path: str = (
            f"projects/{_path_segment(project_uuid)}/milestones/" if project_uuid else "milestones/"
        )
        return self._tasks_list(path, params=params, **page)

    def complete_milestone(
        self,
        project_uuid: str,
        milestone_uuid: str,
        *,
        dry_run: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """POST .../milestones/<uuid>/complete/ — accepts a key; `?dry_run=true` previews.

        Completing a milestone does NOT close its open tasks.
        """
        result: dict[str, Any] = self._tasks_write(
            "POST",
            f"projects/{_path_segment(project_uuid)}/milestones/{_path_segment(milestone_uuid)}/complete/",
            params={"dry_run": "true"} if dry_run else None,
            idempotent=True,
            idempotency_key=idempotency_key,
        )
        return result

    def reopen_milestone(
        self, project_uuid: str, milestone_uuid: str, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """POST .../milestones/<uuid>/reopen/ — the reverse verb; accepts a key."""
        result: dict[str, Any] = self._tasks_write(
            "POST",
            f"projects/{_path_segment(project_uuid)}/milestones/{_path_segment(milestone_uuid)}/reopen/",
            idempotent=True,
            idempotency_key=idempotency_key,
        )
        return result

    # --- Container writes (board / project / goal) ---
    #
    # These need `tasks:admin`, which an organization API key can NEVER hold: the
    # validator refuses to store it and the door refuses it independently. The
    # plan's live probe measured an ADMIN_ORG *owner* refused identically, so the
    # CLI must blame the credential kind rather than the user's role.

    def create_board(
        self, *, name: str, idempotency_key: str | None = None, **fields: Any
    ) -> dict[str, Any]:
        """POST /v1/tasks/boards/ — accepts a key header; needs tasks:admin."""
        payload: dict[str, Any] = {
            "name": name,
            **{k: v for k, v in fields.items() if v is not None},
        }
        return self._tasks_write(
            "POST", "boards/", json=payload, idempotent=True, idempotency_key=idempotency_key
        )

    def update_board(
        self, board_uuid: str, *, idempotency_key: str | None = None, **fields: Any
    ) -> dict[str, Any]:
        """PATCH /v1/tasks/boards/<uuid>/ — partial update; accepts a key.

        Renaming `key` retires the old one, which stays reserved forever.
        """
        payload: dict[str, Any] = {k: v for k, v in fields.items() if v is not None}
        result: dict[str, Any] = self._tasks_write(
            "PATCH",
            f"boards/{_path_segment(board_uuid)}/",
            json=payload,
            idempotent=True,
            idempotency_key=idempotency_key,
        )
        return result

    def archive_board(
        self, board_uuid: str, *, dry_run: bool = False, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """POST /v1/tasks/boards/<uuid>/archive/ — cascades to live tasks."""
        return self._tasks_write(
            "POST",
            f"boards/{_path_segment(board_uuid)}/archive/",
            params={"dry_run": "true"} if dry_run else None,
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def restore_board(
        self, board_uuid: str, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """POST /v1/tasks/boards/<uuid>/restore/ — cascaded tasks stay archived."""
        return self._tasks_write(
            "POST",
            f"boards/{_path_segment(board_uuid)}/restore/",
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def create_project(
        self, *, name: str, idempotency_key: str | None = None, **fields: Any
    ) -> dict[str, Any]:
        """POST /v1/tasks/projects/ — accepts a key header; needs tasks:admin."""
        payload: dict[str, Any] = {
            "name": name,
            **{k: v for k, v in fields.items() if v is not None},
        }
        return self._tasks_write(
            "POST", "projects/", json=payload, idempotent=True, idempotency_key=idempotency_key
        )

    def archive_project(
        self, project_uuid: str, *, dry_run: bool = False, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """POST /v1/tasks/projects/<uuid>/archive/."""
        return self._tasks_write(
            "POST",
            f"projects/{_path_segment(project_uuid)}/archive/",
            params={"dry_run": "true"} if dry_run else None,
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def create_goal(
        self, *, name: str, idempotency_key: str | None = None, **fields: Any
    ) -> dict[str, Any]:
        """POST /v1/tasks/goals/ — accepts a key header; needs tasks:admin."""
        payload: dict[str, Any] = {
            "name": name,
            **{k: v for k, v in fields.items() if v is not None},
        }
        return self._tasks_write(
            "POST", "goals/", json=payload, idempotent=True, idempotency_key=idempotency_key
        )

    def archive_goal(
        self, goal_uuid: str, *, dry_run: bool = False, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """POST /v1/tasks/goals/<uuid>/archive/ — projects are not cascaded."""
        return self._tasks_write(
            "POST",
            f"goals/{_path_segment(goal_uuid)}/archive/",
            params={"dry_run": "true"} if dry_run else None,
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    # --- Person-shaped doors (a bare API key has no answer here) ---

    def list_my_tasks(self, **page: Any) -> PaginatedResult:
        """GET /v1/tasks/me/tasks/ — needs a signed-in person.

        Takes ``**page`` only, like every other list door. The previous signature
        declared ``filters=`` **and** ``**page``, so a caller passing ``params=``
        — which every other list door accepts — collided with the explicit
        ``params=filters`` and raised ``TypeError`` on every single invocation.
        """
        return self._tasks_list("me/tasks/", **page)

    def get_my_task_counts(self) -> dict[str, Any]:
        """GET /v1/tasks/me/tasks/counts/ — needs a signed-in person."""
        return self._tasks_read("me/tasks/counts/")

    def list_tasks_inbox(self, **page: Any) -> PaginatedResult:
        """GET /v1/tasks/inbox/ — needs a signed-in person."""
        return self._tasks_list("inbox/", **page)

    def get_tasks_inbox_unread_count(self) -> dict[str, Any]:
        """GET /v1/tasks/inbox/unread-count/ — needs a signed-in person."""
        return self._tasks_read("inbox/unread-count/")

    def get_labels_entitlement(self) -> dict[str, Any]:
        """GET /v1/labels/entitlement/ — org Labels feature flags for the caller."""
        response: httpx.Response = self._request("GET", f"{self.api_url}/v1/labels/entitlement/")
        return self._handle_response(response)

    def list_labels(
        self,
        *,
        search: str | None = None,
        is_archived: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /v1/labels/ — paginated org Labels (limit/offset)."""
        params: dict[str, Any] = {
            "limit": max(1, min(limit, 100)),
            "offset": max(0, offset),
            "is_archived": is_archived,
        }
        if search:
            params["search"] = search
        response: httpx.Response = self._request("GET", f"{self.api_url}/v1/labels/", params=params)
        return self._handle_response(response)

    def get_label(self, label_uuid: str) -> dict[str, Any]:
        """GET /v1/labels/<uuid>/ — one organization Label."""
        response: httpx.Response = self._request("GET", f"{self.api_url}/v1/labels/{label_uuid}/")
        return self._handle_response(response)

    def create_label(
        self,
        *,
        name: str,
        color: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/labels/ — create an organization Label."""
        body: dict[str, Any] = {"name": name}
        if color is not None:
            body["color"] = color
        if description is not None:
            body["description"] = description
        response: httpx.Response = self._request("POST", f"{self.api_url}/v1/labels/", json=body)
        return self._handle_response(response)

    def update_label(self, label_uuid: str, body: dict[str, Any]) -> dict[str, Any]:
        """PATCH /v1/labels/<uuid>/ — update an organization Label."""
        response: httpx.Response = self._request(
            "PATCH", f"{self.api_url}/v1/labels/{label_uuid}/", json=body
        )
        return self._handle_response(response)

    def delete_label(self, label_uuid: str) -> None:
        """DELETE /v1/labels/<uuid>/ — hard-delete (elevated only)."""
        response: httpx.Response = self._request(
            "DELETE", f"{self.api_url}/v1/labels/{label_uuid}/"
        )
        if response.status_code == 204:
            return
        self._handle_response(response)

    def archive_label(self, label_uuid: str) -> dict[str, Any]:
        """POST /v1/labels/<uuid>/archive/ — archive a Label."""
        response: httpx.Response = self._request(
            "POST", f"{self.api_url}/v1/labels/{label_uuid}/archive/"
        )
        return self._handle_response(response)

    def assign_entity_labels(
        self,
        entity_type: str,
        entity_uuid: str,
        label_uuids: list[str],
    ) -> dict[str, Any]:
        """POST /v1/{forms|checkins|workflows}/{uuid}/labels/ — replace-set Labels."""
        collection: str = _label_entity_collection(entity_type)
        response: httpx.Response = self._request(
            "POST",
            f"{self.api_url}/v1/{collection}/{entity_uuid}/labels/",
            json={"label_uuids": label_uuids},
        )
        return self._handle_response(response)

    def batch_entity_labels(
        self,
        *,
        entity_type: str,
        entity_uuids: list[str],
        label_uuids: list[str],
        mode: str,
    ) -> dict[str, Any]:
        """POST /v1/{forms|checkins|workflows}/labels/batch/ — add/remove/replace."""
        collection: str = _label_entity_collection(entity_type)
        response: httpx.Response = self._request(
            "POST",
            f"{self.api_url}/v1/{collection}/labels/batch/",
            json={
                "entity_uuids": entity_uuids,
                "label_uuids": label_uuids,
                "mode": mode,
            },
        )
        return self._handle_response(response)

    # --- Private Featured stars (/v1/me/featured/) ---

    def list_featured(self, *, entity_type: str) -> dict[str, Any]:
        """GET /v1/me/featured/?entity_type= — list Featured entity UUIDs for the caller."""
        response: httpx.Response = self._request(
            "GET",
            f"{self.api_url}/v1/me/featured/",
            params={"entity_type": entity_type},
        )
        return self._handle_response(response)

    def set_featured(
        self,
        entity_type: str,
        entity_uuid: str,
        *,
        featured: bool,
    ) -> dict[str, Any]:
        """PUT /v1/me/featured/{entity_type}/{uuid}/ — toggle Featured for one entity."""
        response: httpx.Response = self._request(
            "PUT",
            f"{self.api_url}/v1/me/featured/{entity_type}/{entity_uuid}/",
            json={"featured": featured},
        )
        return self._handle_response(response)

    def batch_featured(
        self,
        *,
        entity_type: str,
        entity_uuids: list[str],
        featured: bool,
    ) -> dict[str, Any]:
        """POST /v1/me/featured/batch/ — batch feature/unfeature entities."""
        response: httpx.Response = self._request(
            "POST",
            f"{self.api_url}/v1/me/featured/batch/",
            json={
                "entity_type": entity_type,
                "entity_uuids": entity_uuids,
                "featured": featured,
            },
        )
        return self._handle_response(response)

    # --- Agent registration endpoints ---

    def get_registration_challenge(self) -> dict[str, Any]:
        """GET /v1/agent/register/challenge/ — no auth required."""
        response: httpx.Response = self._guard_transport(
            lambda: httpx.get(
                f"{self.api_url}/v1/agent/register/challenge/",
                headers=self._headers(authenticated=False),
                timeout=self.timeout,
            ),
            method="GET",
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
        response: httpx.Response = self._guard_transport(
            lambda: httpx.post(
                f"{self.api_url}/v1/agent/register/",
                json=payload,
                headers=self._headers(authenticated=False),
                timeout=self.timeout,
            ),
            method="POST",
        )
        return self._handle_response(response)
