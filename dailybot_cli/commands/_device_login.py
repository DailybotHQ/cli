"""Browser sign-in for `dailybot login` (RFC 8628 device flow, PLAN_002).

Start a device authorization, show the link and code, poll the token door at the
server's interval, and save the access/refresh pair. The values are frozen at
checkpoint 1 (DEVICE_FLOW_WIRE): a 404 or 405 on the start door means the server
predates the flow, and the caller falls back to the email code.
"""

import time
from typing import Any

from dailybot_cli.api_client import APIError, DailyBotClient, TransportError
from dailybot_cli.config import save_credentials, save_org_plan
from dailybot_cli.display import (
    console,
    print_device_login_instructions,
    print_error,
    print_success,
)

# Hand-off T31: the browser flow stays opt-in (`--device`) until the API doors are
# live. Flipping this makes a bare `dailybot login` start it, keeping the fallback.
DEVICE_LOGIN_IS_DEFAULT: bool = False

DEFAULT_POLL_INTERVAL_SECS: int = 5
SLOW_DOWN_INCREMENT_SECS: int = 5
MAX_POLL_INTERVAL_SECS: int = 30
DEFAULT_EXPIRES_IN_SECS: int = 600
OLD_SERVER_STATUS_CODES: frozenset[int] = frozenset({404, 405})

CODE_AUTHORIZATION_PENDING: str = "authorization_pending"
CODE_SLOW_DOWN: str = "slow_down"
HTTP_TOO_MANY_REQUESTS: int = 429


class DeviceFlowUnsupported(Exception):
    """The server answered 404/405 on the start door: use the email code instead."""


def login_command() -> str:
    """The command that starts a browser sign-in, as the user should type it."""
    return "dailybot login" if DEVICE_LOGIN_IS_DEFAULT else "dailybot login --device"


def _terminal_message(code: str | None) -> str | None:
    """The message for a poll answer that ends the sign-in, or ``None`` to keep polling."""
    restart: str = f"Run `{login_command()}` to start again."
    messages: dict[str, str] = {
        "access_denied": "The sign-in was denied in the browser.",
        "expired_token": f"The sign-in code expired before it was approved. {restart}",
        "invalid_grant": f"This sign-in request is no longer valid. {restart}",
        "invalid_client": "The server refused this sign-in request. Update the Dailybot CLI "
        "(`dailybot upgrade`) and try again.",
    }
    return messages.get(code or "")


def next_interval(current: int, server_interval: Any) -> int:
    """The polling interval after a ``slow_down``: the server's value, else +5, capped at 30."""
    proposed: int = (
        server_interval
        if isinstance(server_interval, int)
        and not isinstance(server_interval, bool)
        and server_interval > current
        else current + SLOW_DOWN_INCREMENT_SECS
    )
    return min(proposed, MAX_POLL_INTERVAL_SECS)


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default


def _poll_until_approved(client: DailyBotClient, start: dict[str, Any]) -> dict[str, Any]:
    """Poll the token door until it answers the pair, or raise ``SystemExit(1)``."""
    device_code: str = str(start.get("device_code") or "")
    interval: int = min(
        _positive_int(start.get("interval"), DEFAULT_POLL_INTERVAL_SECS), MAX_POLL_INTERVAL_SECS
    )
    expires_in: int = _positive_int(start.get("expires_in"), DEFAULT_EXPIRES_IN_SECS)
    deadline: float = time.monotonic() + expires_in
    with console.status("Waiting for you to approve the sign-in in the browser..."):
        while True:
            if time.monotonic() + interval > deadline:
                break
            time.sleep(interval)
            try:
                return client.poll_device_token(device_code)
            except TransportError:
                continue  # Polling is idempotent until approval: a blip is not an answer.
            except APIError as error:
                if error.code == CODE_AUTHORIZATION_PENDING:
                    continue
                if error.code == CODE_SLOW_DOWN:
                    interval = next_interval(interval, error.extra.get("interval"))
                    continue
                if error.status_code == HTTP_TOO_MANY_REQUESTS:
                    interval = next_interval(interval, None)
                    continue
                message: str | None = _terminal_message(error.code)
                print_error(message or error.detail)
                raise SystemExit(1) from None
    print_error(_terminal_message("expired_token") or "The sign-in code expired.")
    raise SystemExit(1)


def _save_pair(client: DailyBotClient, token: dict[str, Any]) -> tuple[str, str]:
    """Save the pair, the org and its effective tier; return (email, org name)."""
    access: Any = token.get("access")
    refresh: Any = token.get("refresh")
    if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
        print_error("Authentication failed: no token received.")
        raise SystemExit(1)
    user: Any = token.get("user")
    org: Any = token.get("organization")
    user = user if isinstance(user, dict) else {}
    org = org if isinstance(org, dict) else {}
    email: str = str(user.get("email") or "")
    org_name: str = str(org.get("name") or "")
    org_uuid: str = str(org.get("uuid") or "")
    save_credentials(
        token=access,
        email=email,
        organization=org_name,
        organization_uuid=org_uuid,
        api_url=client.api_url,
        refresh=refresh,
        expires_at=token.get("expires_at"),
        refresh_expires_at=token.get("refresh_expires_at"),
    )
    plan: Any = org.get("plan")
    tier: Any = None
    if isinstance(plan, dict):
        tier = plan.get("effective_tier") or plan.get("tier")
    if isinstance(tier, str) and tier and org_uuid:
        save_org_plan(org_uuid, tier)
    return email, org_name


def device_login(client: DailyBotClient) -> None:
    """Run the browser sign-in end to end.

    Raises :class:`DeviceFlowUnsupported` on a 404/405 start (an older server), and
    ``SystemExit(1)`` on any other refusal. Nothing is written until the pair arrives,
    so an interrupted sign-in leaves the stored session untouched.
    """
    try:
        with console.status("Starting the sign-in..."):
            start: dict[str, Any] = client.start_device_authorization()
    except APIError as error:
        if error.status_code in OLD_SERVER_STATUS_CODES:
            raise DeviceFlowUnsupported from error
        print_error(_terminal_message(error.code) or error.detail)
        raise SystemExit(1) from None

    print_device_login_instructions(
        verification_uri=str(start.get("verification_uri") or ""),
        user_code=str(start.get("user_code") or ""),
        verification_uri_complete=start.get("verification_uri_complete"),
    )
    token: dict[str, Any] = _poll_until_approved(client, start)
    email, org_name = _save_pair(client, token)
    print_success(f"Logged in as {email} ({org_name})")
