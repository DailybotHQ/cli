"""The recorded wire fixtures match the checkpoint-1 frozen wire values.

A fixture that drifts from the frozen record fails here, before any test
built on it can pass against a wrong body.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.wire_fixture_loader import FIXTURES_DIR, fixture_body, load_fixture

USER_CODE_PATTERN: re.Pattern[str] = re.compile(
    r"^[BCDFGHJKLMNPQRSTVWXZ]{4}-[BCDFGHJKLMNPQRSTVWXZ]{4}$"
)
UUID_PATTERN: re.Pattern[str] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
TOKEN_ERROR_CODES: tuple[str, ...] = (
    "authorization_pending",
    "slow_down",
    "access_denied",
    "expired_token",
    "invalid_grant",
    "invalid_client",
)
CHAT_PLATFORM_SUMMARY_KEYS: tuple[str, ...] = (
    "id",
    "platform",
    "display_name",
    "organization_external_id",
    "is_primary",
    "status",
    "capabilities",
)
CHAT_PLATFORMS: set[str] = {"dailybot", "slack", "msteams", "discord", "hangouts"}
TOKEN_BODY_KEYS: set[str] = {
    "token_type",
    "access",
    "expires_at",
    "refresh",
    "refresh_expires_at",
    "user",
    "organization",
}


def _all_fixtures() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("*.json"))


class TestEveryFixture:
    def test_the_folder_is_not_empty(self) -> None:
        assert len(_all_fixtures()) >= 30

    @pytest.mark.parametrize("path", _all_fixtures(), ids=lambda p: p.stem)
    def test_the_recorded_shape(self, path: Path) -> None:
        data: dict[str, Any] = json.loads(path.read_text())
        assert set(data) == {"door", "status", "headers", "body"}
        assert isinstance(data["status"], int)
        assert isinstance(data["body"], dict)

    @pytest.mark.parametrize("path", _all_fixtures(), ids=lambda p: p.stem)
    def test_no_real_identifiers(self, path: Path) -> None:
        text: str = path.read_text()
        for uuid in re.findall(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text
        ):
            assert uuid.startswith("00000000-0000-4000-8000-"), uuid
        for email in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
            assert email.endswith("@example.com"), email
        assert "dailybot.com" not in text


class TestDeviceStart:
    def test_the_start_body(self) -> None:
        body: dict[str, Any] = fixture_body("device_start_200")
        assert len(body["device_code"]) == 43
        assert USER_CODE_PATTERN.match(body["user_code"])
        assert body["verification_uri"].endswith("/auth/device")
        assert body["verification_uri_complete"].endswith(f"?user_code={body['user_code']}")
        assert body["expires_in"] == 600
        assert body["interval"] == 5

    @pytest.mark.parametrize(
        "name,status",
        [
            ("device_start_not_found_404", 404),
            ("device_start_method_not_allowed_405", 405),
        ],
    )
    def test_an_old_server(self, name: str, status: int) -> None:
        assert load_fixture(name)["status"] == status


class TestDeviceToken:
    @pytest.mark.parametrize("code", TOKEN_ERROR_CODES)
    def test_every_state_is_a_400_with_error_equal_to_code(self, code: str) -> None:
        recorded: dict[str, Any] = load_fixture(f"device_token_{code}_400")
        assert recorded["status"] == 400
        assert recorded["body"]["error"] == recorded["body"]["code"] == code

    def test_slow_down_carries_the_new_interval(self) -> None:
        assert fixture_body("device_token_slow_down_400")["interval"] > 5

    @pytest.mark.parametrize("name", ["device_token_success_200", "refresh_success_200"])
    def test_the_token_success_body(self, name: str) -> None:
        body: dict[str, Any] = fixture_body(name)
        assert set(body) >= TOKEN_BODY_KEYS
        assert body["token_type"] == "Bearer"
        assert body["access"].startswith("dbc_at_")
        assert body["refresh"].startswith("dbc_rt_")
        assert set(body["user"]) == {"uuid", "email", "full_name"}
        org: dict[str, Any] = body["organization"]
        assert {"id", "uuid", "name", "platform", "plan"} <= set(org)
        assert set(org["plan"]) == {"tier", "effective_tier", "is_trial"}


class TestSessionCodes:
    @pytest.mark.parametrize("code", ["session_revoked", "refresh_token_expired", "user_disabled"])
    def test_refresh_failures(self, code: str) -> None:
        recorded: dict[str, Any] = load_fixture(f"refresh_{code}_401")
        assert recorded["status"] == 401
        assert recorded["body"]["code"] == code

    @pytest.mark.parametrize(
        "code", ["access_token_expired", "session_revoked", "user_disabled", "invalid_credentials"]
    )
    def test_bearer_failures(self, code: str) -> None:
        recorded: dict[str, Any] = load_fixture(f"bearer_{code}_401")
        assert recorded["status"] == 401
        assert recorded["body"]["code"] == code

    def test_the_503_carries_retry_after_inside_the_frozen_range(self) -> None:
        recorded: dict[str, Any] = load_fixture("auth_backend_unavailable_503")
        assert recorded["status"] == 503
        assert recorded["body"]["code"] == "auth_backend_unavailable"
        assert 1 <= int(recorded["headers"]["Retry-After"]) <= 5

    def test_logout_keeps_todays_bytes(self) -> None:
        assert fixture_body("logout_200") == {"detail": "Successfully logged out."}


class TestDeprecation:
    @pytest.mark.parametrize(
        "name",
        [
            "request_code_deprecation_200",
            "verify_code_deprecation_200",
            "verify_code_deprecation_400",
        ],
    )
    def test_a_field_never_an_error(self, name: str) -> None:
        recorded: dict[str, Any] = load_fixture(name)
        deprecation: dict[str, Any] = recorded["body"]["deprecation"]
        assert set(deprecation) == {"code", "min_version", "sunset", "detail"}
        assert deprecation["code"] == "cli_auth_deprecated"
        assert deprecation["sunset"] == "2027-03-31"
        assert "code" not in {k for k in recorded["body"] if k != "deprecation"}
        assert recorded["headers"]["Deprecation"] == "true"


class TestStandalone:
    def test_legacy_entries_keep_exactly_three_keys(self) -> None:
        orgs: list[dict[str, Any]] = fixture_body("verify_code_org_selection_200")["organizations"]
        legacy: list[dict[str, Any]] = [o for o in orgs if not o.get("standalone")]
        native: list[dict[str, Any]] = [o for o in orgs if o.get("standalone")]
        assert legacy and all(set(o) == {"id", "name", "uuid"} for o in legacy)
        assert native and all(
            o["standalone"] is True and o["platform"] == "dailybot" for o in native
        )

    def test_a_native_org_serves_channels_and_plan(self) -> None:
        body: dict[str, Any] = fixture_body("organization_native_200")
        assert body["platform"] == "dailybot"
        assert body["has_external_chat_platform"] is False
        assert body["chat_platforms"][0] == body["primary_chat_platform"]
        assert UUID_PATTERN.match(body["primary_chat_platform"]["id"])
        assert set(body["plan"]) == {"tier", "effective_tier", "is_trial"}

    def test_the_plan_field_can_be_absent(self) -> None:
        assert "plan" not in fixture_body("organization_chat_platforms_no_plan_200")
        legacy: dict[str, Any] = fixture_body("organization_legacy_200")
        assert not {
            "plan",
            "chat_platforms",
            "primary_chat_platform",
            "has_external_chat_platform",
        } & set(legacy)

    @pytest.mark.parametrize(
        "name", ["organization_native_200", "organization_chat_platforms_no_plan_200"]
    )
    def test_every_platform_summary_is_the_exact_allowlist_in_order(self, name: str) -> None:
        body: dict[str, Any] = fixture_body(name)
        for summary in [body["primary_chat_platform"], *body["chat_platforms"]]:
            assert list(summary) == list(CHAT_PLATFORM_SUMMARY_KEYS)
            assert summary["platform"] in CHAT_PLATFORMS
            assert summary["status"] in {"connected", "needs_reauth", "disabled"}
            assert set(summary["capabilities"]) == {"directory", "reporting", "direct_messages"}
            if summary["platform"] == "dailybot":
                assert summary["organization_external_id"] is None

    @pytest.mark.parametrize(
        "name,status,code",
        [
            ("send_message_platform_not_connected_400", 400, "platform_not_connected"),
            ("channel_reference_ambiguous_409", 409, "channel_reference_ambiguous"),
            ("channel_reference_unknown_400", 400, "channel_reference_unknown"),
        ],
    )
    def test_channel_codes(self, name: str, status: int, code: str) -> None:
        recorded: dict[str, Any] = load_fixture(name)
        assert recorded["status"] == status
        assert recorded["body"]["code"] == code
