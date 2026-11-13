"""The cached plan tier follows `plan.effective_tier` (PLAN_002 T-effective-tier, L37, L43).

The CLI re-reads `/v1/organization/` only on a cached-free hit or a paywall code,
never for a paid or unknown tier. When `plan` is absent (PUBLIC_V1_ORG_PLAN_FIELD
off) the cached tier is kept. A failed refresh never blocks.
"""

import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner, Result

from dailybot_cli.api_client import APIError
from dailybot_cli.commands import public_api_helpers
from dailybot_cli.commands.public_api_helpers import (
    TIER_REFRESH_MIN_INTERVAL_SECS,
    enforce_plan_access,
    exit_for_api_error,
)
from dailybot_cli.config import get_org_plan, save_credentials, save_org_plan
from dailybot_cli.main import cli
from tests.wire_fixture_loader import fixture_body

API: str = "https://api.example.com"
GET: str = "dailybot_cli.api_client.httpx.get"
NATIVE: dict[str, Any] = fixture_body("organization_native_200")
ORG_UUID: str = NATIVE["uuid"]


@pytest.fixture(autouse=True)
def _session(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DAILYBOT_API_KEY", "DAILYBOT_CLI_TOKEN", "DAILYBOT_API_URL"):
        monkeypatch.delenv(name, raising=False)
    save_credentials(
        token="test-token",
        email="me@example.com",
        organization="My Team",
        organization_uuid=ORG_UUID,
        api_url=API,
    )


def _org(effective: str | None, uuid: str = ORG_UUID) -> MagicMock:
    body: dict[str, Any] = copy.deepcopy(NATIVE)
    body["uuid"] = uuid
    if effective is None:
        body.pop("plan")
    else:
        body["plan"] = {
            "tier": "free",
            "effective_tier": effective,
            "is_trial": effective != "free",
        }
    response: MagicMock = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.json.return_value = body
    return response


class TestCachedFreeHit:
    def test_a_trial_proceeds_after_one_organization_read(self) -> None:
        save_org_plan(ORG_UUID, "free")
        with patch(GET, return_value=_org("startup")) as get:
            enforce_plan_access("form_list")
        assert get.call_count == 1
        assert get.call_args.args[0] == f"{API}/v1/organization/"
        assert get_org_plan(ORG_UUID) == "startup"

    def test_a_still_free_org_is_blocked(self) -> None:
        save_org_plan(ORG_UUID, "free")
        with patch(GET, return_value=_org("free")), pytest.raises(SystemExit) as caught:
            enforce_plan_access("form_list")
        assert caught.value.code == public_api_helpers.EXIT_PERMISSION_DENIED

    def test_an_absent_plan_keeps_the_cached_tier(self) -> None:
        save_org_plan(ORG_UUID, "free")
        with patch(GET, return_value=_org(None)), pytest.raises(SystemExit):
            enforce_plan_access("form_list")
        assert get_org_plan(ORG_UUID) == "free"

    @pytest.mark.parametrize(
        "failure",
        [httpx.ConnectError("offline"), None],
        ids=["transport", "server-error"],
    )
    def test_a_failed_refresh_never_blocks(self, failure: Exception | None) -> None:
        save_org_plan(ORG_UUID, "free")
        error_response: MagicMock = MagicMock()
        error_response.status_code = 500
        error_response.headers = {}
        error_response.json.return_value = {"detail": "boom"}
        with (
            patch(GET, side_effect=failure) if failure else patch(GET, return_value=error_response)
        ):
            enforce_plan_access("form_list")
        assert get_org_plan(ORG_UUID) == "free"

    def test_another_orgs_payload_is_never_cached(self) -> None:
        save_org_plan(ORG_UUID, "free")
        other: str = "00000000-0000-4000-8000-000000000099"
        with patch(GET, return_value=_org("business", uuid=other)), pytest.raises(SystemExit):
            enforce_plan_access("form_list")
        assert get_org_plan(ORG_UUID) == "free"
        assert get_org_plan(other) is None

    def test_a_recent_refresh_is_not_repeated(self) -> None:
        save_org_plan(ORG_UUID, "free")
        with patch(GET, return_value=_org("free")) as get:
            for _ in range(3):
                with pytest.raises(SystemExit):
                    enforce_plan_access("form_list")
        assert get.call_count == 1

    def test_the_throttle_expires(self, monkeypatch: pytest.MonkeyPatch) -> None:
        save_org_plan(ORG_UUID, "free")
        clock: list[float] = [1000.0]
        monkeypatch.setattr(public_api_helpers.time, "time", lambda: clock[0])
        with patch(GET, return_value=_org("free")) as get:
            with pytest.raises(SystemExit):
                enforce_plan_access("form_list")
            clock[0] += TIER_REFRESH_MIN_INTERVAL_SECS + 1
            with pytest.raises(SystemExit):
                enforce_plan_access("form_list")
        assert get.call_count == 2


class TestZeroExtraCalls:
    @pytest.mark.parametrize("tier", ["startup", "business", None])
    def test_paid_or_unknown_tiers_never_call(self, tier: str | None) -> None:
        if tier:
            save_org_plan(ORG_UUID, tier)
        with patch(GET) as get:
            enforce_plan_access("form_list")
        get.assert_not_called()

    def test_allowlisted_actions_never_call(self) -> None:
        save_org_plan(ORG_UUID, "free")
        with patch(GET) as get:
            enforce_plan_access("me")
        get.assert_not_called()


class TestPaywallCode:
    def test_a_paywall_answer_rewrites_the_cache(self) -> None:
        save_org_plan(ORG_UUID, "startup")
        with patch(GET, return_value=_org("free")) as get, pytest.raises(SystemExit):
            exit_for_api_error(
                APIError(403, "Upgrade.", code="plan_upgrade_required"), json_mode=False
            )
        assert get.call_count == 1
        assert get_org_plan(ORG_UUID) == "free"

    def test_other_codes_never_refresh(self) -> None:
        with patch(GET) as get, pytest.raises(SystemExit):
            exit_for_api_error(APIError(403, "No.", code="forbidden"), json_mode=False)
        get.assert_not_called()


def test_dailybot_org_writes_the_effective_tier(_isolated_environment: Path) -> None:
    with patch(GET, return_value=_org("startup")):
        result: Result = CliRunner().invoke(cli, ["org", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["uuid"] == ORG_UUID
    assert get_org_plan(ORG_UUID) == "startup"


def test_an_older_cli_still_reads_the_cache(_isolated_environment: Path) -> None:
    save_org_plan(ORG_UUID, "free")
    with patch(GET, return_value=_org("startup")):
        enforce_plan_access("form_list")
    data: dict[str, Any] = json.loads((_isolated_environment / "plan_cache.json").read_text())
    assert data[ORG_UUID] == "startup"
