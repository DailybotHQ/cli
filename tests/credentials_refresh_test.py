"""Refresh on `401 access_token_expired` (PLAN_002 T-refresh-on-401, frozen rule L36).

The client refreshes a device-flow pair once and replays the request once. Only
that code refreshes; other 401s, 403s and legacy sessions keep today's behaviour.
HTTP is mocked at the call site with the recorded fixtures.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from dailybot_cli.api_client import APIError, DailyBotClient, TransportError
from dailybot_cli.config import load_credentials, save_credentials
from tests.wire_fixture_loader import fixture_body, fixture_response

API: str = "https://api.example.com"
OLD_ACCESS: str = "dbc_at_old-access"
OLD_REFRESH: str = "dbc_rt_old-refresh"
NEW: dict[str, Any] = fixture_body("refresh_success_200")


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DAILYBOT_API_KEY", "DAILYBOT_CLI_TOKEN", "DAILYBOT_API_URL"):
        monkeypatch.delenv(name, raising=False)


def _save_pair(access: str = OLD_ACCESS, refresh: str = OLD_REFRESH) -> None:
    save_credentials(
        token=access,
        email="me@example.com",
        organization="My Team",
        organization_uuid="org-1",
        api_url=API,
        refresh=refresh,
        expires_at="2030-01-01T00:00:00Z",
        refresh_expires_at="2030-04-01T00:00:00Z",
    )


def _ok(body: dict[str, Any] | None = None) -> MagicMock:
    response: MagicMock = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.json.return_value = body if body is not None else {"ok": True}
    return response


def _plain(status: int, body: dict[str, Any]) -> MagicMock:
    response: MagicMock = MagicMock()
    response.status_code = status
    response.headers = {}
    response.json.return_value = body
    response.text = json.dumps(body)
    return response


def _bearer(call: Any) -> str | None:
    return call.kwargs["headers"].get("Authorization")


class TestRefreshThenReplay:
    def test_a_user_request_refreshes_once_and_replays_once(
        self, _isolated_environment: Path
    ) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API)
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                side_effect=[fixture_response("bearer_access_token_expired_401"), _ok()],
            ) as get,
            patch(
                "dailybot_cli.api_client.httpx.post",
                return_value=fixture_response("refresh_success_200"),
            ) as post,
        ):
            assert client.get_status() == {"ok": True}
        assert post.call_count == 1
        assert post.call_args.args[0] == f"{API}/v1/cli/auth/refresh/"
        assert post.call_args.kwargs["json"] == {"refresh": OLD_REFRESH}
        assert [_bearer(c) for c in get.call_args_list] == [
            f"Bearer {OLD_ACCESS}",
            f"Bearer {NEW['access']}",
        ]
        creds: dict[str, Any] | None = load_credentials()
        assert creds is not None
        assert creds["token"] == NEW["access"]
        assert creds["refresh"] == NEW["refresh"]
        assert creds["expires_at"] == NEW["expires_at"]
        assert creds["email"] == "me@example.com"
        mode: int = (_isolated_environment / "credentials.json").stat().st_mode & 0o777
        assert mode == 0o600

    def test_an_agent_request_refreshes_too(self) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API)
        with (
            patch(
                "dailybot_cli.api_client.httpx.request",
                side_effect=[fixture_response("bearer_access_token_expired_401"), _ok()],
            ) as request,
            patch(
                "dailybot_cli.api_client.httpx.post",
                return_value=fixture_response("refresh_success_200"),
            ),
        ):
            client.get_agent_health(agent_name="a")
        assert _bearer(request.call_args_list[1]) == f"Bearer {NEW['access']}"

    def test_a_second_expiry_after_the_replay_does_not_loop(self) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API)
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                side_effect=[
                    fixture_response("bearer_access_token_expired_401"),
                    fixture_response("bearer_access_token_expired_401"),
                ],
            ) as get,
            patch(
                "dailybot_cli.api_client.httpx.post",
                return_value=fixture_response("refresh_success_200"),
            ) as post,
            pytest.raises(APIError),
        ):
            client.get_status()
        assert post.call_count == 1
        assert get.call_count == 2


class TestNoRefresh:
    @pytest.mark.parametrize("code", ["session_revoked", "user_disabled", "invalid_credentials"])
    def test_other_401_codes_never_refresh(self, code: str) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API)
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                return_value=fixture_response(f"bearer_{code}_401"),
            ),
            patch("dailybot_cli.api_client.httpx.post") as post,
            pytest.raises(APIError) as caught,
        ):
            client.get_status()
        post.assert_not_called()
        assert caught.value.status_code == 401

    def test_a_403_never_refreshes(self) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API)
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                return_value=_plain(403, {"detail": "no", "code": "access_token_expired"}),
            ),
            patch("dailybot_cli.api_client.httpx.post") as post,
            pytest.raises(APIError),
        ):
            client.get_status()
        post.assert_not_called()

    def test_a_legacy_session_is_never_refreshed(self) -> None:
        save_credentials(
            token="legacy-test-token",
            email="me@example.com",
            organization="O",
            organization_uuid="org-1",
            api_url=API,
        )
        client: DailyBotClient = DailyBotClient(api_url=API)
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                return_value=fixture_response("bearer_access_token_expired_401"),
            ),
            patch("dailybot_cli.api_client.httpx.post") as post,
            pytest.raises(APIError),
        ):
            client.get_status()
        post.assert_not_called()

    def test_an_explicit_env_token_is_never_refreshed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _save_pair()
        monkeypatch.setenv("DAILYBOT_CLI_TOKEN", "dbc_at_from-env")
        client: DailyBotClient = DailyBotClient(api_url=API)
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                return_value=fixture_response("bearer_access_token_expired_401"),
            ),
            patch("dailybot_cli.api_client.httpx.post") as post,
            pytest.raises(APIError),
        ):
            client.get_status()
        post.assert_not_called()

    def test_a_pair_from_another_host_is_never_refreshed(self) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url="http://localhost:8000", token=OLD_ACCESS)
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                return_value=fixture_response("bearer_access_token_expired_401"),
            ),
            patch("dailybot_cli.api_client.httpx.post") as post,
            pytest.raises(APIError),
        ):
            client.get_status()
        post.assert_not_called()


class TestRefreshFailures:
    @pytest.mark.parametrize("code", ["refresh_token_expired", "user_disabled"])
    def test_a_refused_refresh_keeps_todays_fallback(self, code: str) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API, api_key="test-key")
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                side_effect=[fixture_response("bearer_access_token_expired_401"), _ok()],
            ) as get,
            patch(
                "dailybot_cli.api_client.httpx.post",
                return_value=fixture_response(f"refresh_{code}_401"),
            ),
        ):
            assert client.get_status() == {"ok": True}
        assert get.call_args_list[1].kwargs["headers"].get("X-API-KEY") == "test-key"
        creds: dict[str, Any] | None = load_credentials()
        assert creds is not None and creds["token"] == OLD_ACCESS

    def test_a_transport_failure_never_falls_back_or_changes_credentials(self) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API, api_key="test-key")
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                return_value=fixture_response("bearer_access_token_expired_401"),
            ) as get,
            patch("dailybot_cli.api_client.httpx.post", side_effect=httpx.ConnectError("offline")),
            pytest.raises(TransportError),
        ):
            client.get_status()
        assert get.call_count == 1
        creds: dict[str, Any] | None = load_credentials()
        assert creds is not None and creds["refresh"] == OLD_REFRESH

    def test_a_503_on_refresh_never_falls_back(self) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API, api_key="test-key")
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                return_value=fixture_response("bearer_access_token_expired_401"),
            ) as get,
            patch(
                "dailybot_cli.api_client.httpx.post",
                return_value=fixture_response("auth_backend_unavailable_503"),
            ),
            pytest.raises(APIError) as caught,
        ):
            client.get_status()
        assert caught.value.status_code == 503
        assert get.call_count == 1


class TestTwoProcesses:
    def test_session_revoked_rereads_the_file_once(self) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API)
        sent: list[dict[str, Any]] = []

        def refresh_door(url: str, **kwargs: Any) -> MagicMock:
            sent.append(kwargs["json"])
            if len(sent) == 1:
                # Another CLI process won the race and rotated the file meanwhile.
                _save_pair(access="dbc_at_winner", refresh="dbc_rt_winner")
                return fixture_response("refresh_session_revoked_401")
            return fixture_response("refresh_success_200")

        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                side_effect=[fixture_response("bearer_access_token_expired_401"), _ok()],
            ),
            patch("dailybot_cli.api_client.httpx.post", side_effect=refresh_door),
        ):
            assert client.get_status() == {"ok": True}
        assert sent == [{"refresh": OLD_REFRESH}, {"refresh": "dbc_rt_winner"}]

    def test_session_revoked_with_an_unchanged_file_stops(self) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API)
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                return_value=fixture_response("bearer_access_token_expired_401"),
            ),
            patch(
                "dailybot_cli.api_client.httpx.post",
                return_value=fixture_response("refresh_session_revoked_401"),
            ) as post,
            pytest.raises(APIError),
        ):
            client.get_status()
        assert post.call_count == 1

    def test_a_pair_already_rotated_by_another_process_is_adopted(self) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API)
        _save_pair(access="dbc_at_winner", refresh="dbc_rt_winner")
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                side_effect=[fixture_response("bearer_access_token_expired_401"), _ok()],
            ) as get,
            patch("dailybot_cli.api_client.httpx.post") as post,
        ):
            assert client.get_status() == {"ok": True}
        post.assert_not_called()
        assert _bearer(get.call_args_list[1]) == "Bearer dbc_at_winner"


def test_tokens_never_reach_an_error_message() -> None:
    _save_pair()
    client: DailyBotClient = DailyBotClient(api_url=API)
    with (
        patch(
            "dailybot_cli.api_client.httpx.get",
            return_value=fixture_response("bearer_access_token_expired_401"),
        ),
        patch(
            "dailybot_cli.api_client.httpx.post",
            return_value=fixture_response("refresh_refresh_token_expired_401"),
        ),
        pytest.raises(APIError) as caught,
    ):
        client.get_status()
    for secret in (OLD_ACCESS, OLD_REFRESH):
        assert secret not in str(caught.value)
        assert secret not in caught.value.detail


class TestReviewFixes:
    """AI review round 1 on PR 145 (fp=077b35cf, fp=402bf40b)."""

    @pytest.mark.parametrize("field", ["access", "refresh"])
    def test_an_empty_token_in_the_refresh_answer_is_rejected(
        self, field: str, _isolated_environment: Path
    ) -> None:
        _save_pair()
        broken: MagicMock = fixture_response("refresh_success_200")
        body: dict[str, Any] = dict(broken.json.return_value)
        body[field] = ""
        broken.json.return_value = body
        client: DailyBotClient = DailyBotClient(api_url=API)
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                return_value=fixture_response("bearer_access_token_expired_401"),
            ) as get,
            patch("dailybot_cli.api_client.httpx.post", return_value=broken),
            pytest.raises(APIError),
        ):
            client.get_status()
        assert get.call_count == 1  # no replay with a broken pair
        creds: dict[str, Any] | None = load_credentials()
        assert creds is not None
        assert creds["token"] == OLD_ACCESS and creds["refresh"] == OLD_REFRESH

    def test_a_pair_that_cannot_be_persisted_is_not_used(self) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API)
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                return_value=fixture_response("bearer_access_token_expired_401"),
            ) as get,
            patch(
                "dailybot_cli.api_client.httpx.post",
                return_value=fixture_response("refresh_success_200"),
            ),
            patch("dailybot_cli.api_client.update_token_pair", return_value=False),
            pytest.raises(APIError),
        ):
            client.get_status()
        assert get.call_count == 1
        assert client.token == OLD_ACCESS


class TestRefreshAfterTheAlternateCredential:
    """AI review round 1 (unthreaded warnings at api_client.py:680 and :764).

    A repo key preferred on the login's own host is refused, the client falls back to
    the Bearer session, and that access token has expired: the pair refreshes once and
    the request is replayed with the new Bearer.
    """

    @staticmethod
    def _client() -> DailyBotClient:
        _save_pair()
        return DailyBotClient(api_url=API, api_key="test-key", prefer_api_key=True)

    def test_the_user_path(self) -> None:
        client: DailyBotClient = self._client()
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                side_effect=[
                    _plain(401, {"detail": "Invalid key."}),
                    fixture_response("bearer_access_token_expired_401"),
                    _ok(),
                ],
            ) as get,
            patch(
                "dailybot_cli.api_client.httpx.post",
                return_value=fixture_response("refresh_success_200"),
            ) as post,
        ):
            assert client.get_status() == {"ok": True}
        assert post.call_count == 1
        sent: list[dict[str, str]] = [c.kwargs["headers"] for c in get.call_args_list]
        assert sent[0].get("X-API-KEY") == "test-key"
        assert sent[1].get("Authorization") == f"Bearer {OLD_ACCESS}"
        assert sent[2].get("Authorization") == f"Bearer {NEW['access']}"
        assert "X-API-KEY" not in sent[2]

    def test_the_agent_path(self) -> None:
        client: DailyBotClient = self._client()
        with (
            patch(
                "dailybot_cli.api_client.httpx.request",
                side_effect=[
                    _plain(401, {"detail": "Invalid key."}),
                    fixture_response("bearer_access_token_expired_401"),
                    _ok(),
                ],
            ) as request,
            patch(
                "dailybot_cli.api_client.httpx.post",
                return_value=fixture_response("refresh_success_200"),
            ),
        ):
            client.get_agent_health(agent_name="a")
        replay: dict[str, str] = request.call_args_list[2].kwargs["headers"]
        assert replay.get("Authorization") == f"Bearer {NEW['access']}"
        assert "X-API-KEY" not in replay

    def test_never_more_than_one_refresh_per_request(self) -> None:
        _save_pair()
        client: DailyBotClient = DailyBotClient(api_url=API, api_key="test-key")
        with (
            patch(
                "dailybot_cli.api_client.httpx.get",
                side_effect=[
                    fixture_response("bearer_access_token_expired_401"),
                    fixture_response("bearer_access_token_expired_401"),
                    _plain(401, {"detail": "Invalid key."}),
                ],
            ),
            patch(
                "dailybot_cli.api_client.httpx.post",
                return_value=fixture_response("refresh_success_200"),
            ) as post,
            pytest.raises(APIError),
        ):
            client.get_status()
        assert post.call_count == 1
