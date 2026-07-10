"""Tests for error-code dispatch in exit_for_api_error (Task 2)."""

import json
from typing import Any

import pytest

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import (
    EXIT_NOT_AUTHENTICATED,
    EXIT_PERMISSION_DENIED,
    EXIT_RATE_LIMITED,
    EXIT_USAGE_ERROR,
    exit_for_api_error,
)


def _run_json(exc: APIError, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    with pytest.raises(SystemExit) as excinfo:
        exit_for_api_error(exc, json_mode=True)
    payload: dict[str, Any] = json.loads(capsys.readouterr().out)
    payload["_exit"] = excinfo.value.code
    return payload


def test_plan_upgrade_required_includes_upgrade_url(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exc = APIError(
        403,
        "Session expired.",
        code="plan_upgrade_required",
        extra={"upgrade_url": "https://app.example.com/upgrade"},
    )
    out = _run_json(exc, capsys)
    assert out["code"] == "plan_upgrade_required"
    assert "Upgrade at: https://app.example.com/upgrade" in out["error"]
    assert out["_exit"] == EXIT_PERMISSION_DENIED


def test_insufficient_role_shows_required_and_current(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exc = APIError(
        403,
        "forbidden",
        code="insufficient_role",
        extra={"required_role": "admin", "current_role": "member"},
    )
    out = _run_json(exc, capsys)
    assert "Required role: admin." in out["error"]
    assert "Your role: member." in out["error"]


def test_plan_free_api_keys_forbidden_suggests_login(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exc = APIError(403, "forbidden", code="plan_free_api_keys_forbidden")
    out = _run_json(exc, capsys)
    assert "dailybot login" in out["error"]


def test_free_plan_daily_limit_message_on_429(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exc = APIError(
        429,
        "too many",
        code="free_plan_daily_limit_exceeded",
        retry_after=3600.0,
    )
    out = _run_json(exc, capsys)
    assert "free-plan limit" in out["error"]
    assert out["_exit"] == EXIT_RATE_LIMITED


def test_invalid_date_range_shows_format_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exc = APIError(400, "bad date", code="invalid_date_range")
    out = _run_json(exc, capsys)
    assert "YYYY-MM-DD" in out["error"]
    assert out["_exit"] == EXIT_USAGE_ERROR


def test_search_query_too_long_message(capsys: pytest.CaptureFixture[str]) -> None:
    exc = APIError(400, "too long", code="search_query_too_long")
    out = _run_json(exc, capsys)
    assert "256" in out["error"]


def test_unknown_code_falls_back_to_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exc = APIError(401, "Session expired.", code=None)
    out = _run_json(exc, capsys)
    assert out["_exit"] == EXIT_NOT_AUTHENTICATED


def test_message_goes_to_stderr_in_human_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exc = APIError(403, "forbidden", code="plan_free_api_keys_forbidden")
    with pytest.raises(SystemExit):
        exit_for_api_error(exc, json_mode=False)
    captured = capsys.readouterr()
    assert captured.out == ""  # nothing on stdout
    assert "login" in captured.err.lower()  # message on stderr
