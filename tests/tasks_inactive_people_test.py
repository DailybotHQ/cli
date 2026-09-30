"""Inactive people in Dailybot Plan: readable refusal, marker on output, no inactive picks."""

import json
from typing import Any, ClassVar

import pytest

from dailybot_cli.api_client import APIError, PaginatedResult
from dailybot_cli.commands.public_api_helpers import (
    ERROR_CODE_MESSAGES,
    TASKS_ERROR_CODES,
    exit_for_tasks_error,
    resolve_user_by_name_or_uuid,
)
from dailybot_cli.display import (
    console,
    print_report_document,
    print_report_runs,
    print_route_deliveries,
    print_task_briefing,
    print_task_detail,
    print_tasks_rows,
    print_tasks_table,
    print_users_table,
)

U1: str = "00000000-0000-0000-0000-0000000000a1"
U2: str = "00000000-0000-0000-0000-0000000000a2"
GONE: dict[str, Any] = {"uuid": U1, "name": "Ana Ruiz", "is_active": False}
HERE: dict[str, Any] = {"uuid": U2, "name": "Bo Chen", "is_active": True}


@pytest.fixture(autouse=True)
def wide() -> Any:
    previous: int | None = console._width
    console.width = 120
    try:
        yield
    finally:
        console._width = previous


def _flat(capsys: pytest.CaptureFixture[str]) -> str:
    return " ".join(capsys.readouterr().out.split())


class TestRefusal:
    def test_the_code_has_a_message(self) -> None:
        assert "user_inactive" in TASKS_ERROR_CODES
        assert "inactive" in ERROR_CODE_MESSAGES["user_inactive"].lower()

    @pytest.mark.parametrize(
        ("parameter", "flag"),
        [
            ("owner", "--owner"),
            ("lead", "--lead"),
            ("user", "--user"),
            ("email_recipients", "--email-to"),
        ],
    )
    def test_the_message_names_the_flag_and_the_people(
        self, capsys: pytest.CaptureFixture[str], parameter: str, flag: str
    ) -> None:
        exc: APIError = APIError(
            400,
            "That person is inactive in this organization and cannot be given new work.",
            code="user_inactive",
            extra={"parameter": parameter, "uuids": [U1]},
        )
        with pytest.raises(SystemExit):
            exit_for_tasks_error(exc, False)
        err: str = " ".join(capsys.readouterr().err.split())
        assert flag in err and U1 in err and "inactive" in err

    def test_the_json_envelope_keeps_the_extra(self, capsys: pytest.CaptureFixture[str]) -> None:
        exc: APIError = APIError(
            400, "x", code="user_inactive", extra={"parameter": "lead", "uuids": [U1]}
        )
        with pytest.raises(SystemExit):
            exit_for_tasks_error(exc, True)
        envelope: dict[str, Any] = json.loads(capsys.readouterr().out)
        assert envelope["code"] == "user_inactive"
        assert envelope["extra"]["uuids"] == [U1]


class TestResolver:
    USERS: ClassVar[list[dict[str, Any]]] = [
        {"uuid": U1, "full_name": "Ana Ruiz", "email": "ana@example.com", "is_active": False},
        {"uuid": U2, "full_name": "Bo Chen", "email": "bo@example.com", "is_active": True},
    ]

    def test_an_inactive_only_name_match_is_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match=r"Ana Ruiz is inactive in this organization"):
            resolve_user_by_name_or_uuid(self.USERS, "Ana")

    def test_an_inactive_email_match_is_refused(self) -> None:
        with pytest.raises(ValueError, match="inactive"):
            resolve_user_by_name_or_uuid(self.USERS, "ana@example.com")

    def test_an_active_namesake_wins_over_an_inactive_one(self) -> None:
        users: list[dict[str, Any]] = [
            {"uuid": U1, "full_name": "Sam Lee", "is_active": False},
            {"uuid": U2, "full_name": "Sam Lee", "is_active": True},
        ]
        assert resolve_user_by_name_or_uuid(users, "Sam Lee") == (U2, "Sam Lee")

    def test_a_partial_match_ignores_the_inactive(self) -> None:
        users: list[dict[str, Any]] = [
            {"uuid": U1, "full_name": "Sam Lee", "is_active": False},
            {"uuid": U2, "full_name": "Sam Park", "is_active": True},
        ]
        assert resolve_user_by_name_or_uuid(users, "Sam")[0] == U2

    def test_an_explicit_uuid_is_left_to_the_server(self) -> None:
        assert resolve_user_by_name_or_uuid(self.USERS, U1)[0] == U1

    def test_rows_without_the_flag_count_as_active(self) -> None:
        assert resolve_user_by_name_or_uuid([{"uuid": U2, "full_name": "Bo Chen"}], "Bo")[0] == U2


class TestMarker:
    def test_the_task_table_marks_an_inactive_owner(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_tasks_table(
            [
                {"key": "ENG-1", "title": "t", "owner": GONE},
                {"key": "ENG-2", "title": "t", "owner": HERE},
            ]
        )
        out: str = _flat(capsys)
        assert '"Ana Ruiz" (inactive)' in out
        assert '"Bo Chen" (inactive)' not in out

    def test_the_task_detail_marks_an_inactive_owner(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_task_detail({"key": "ENG-1", "title": "t", "owner": GONE})
        assert '"Ana Ruiz" (inactive)' in _flat(capsys)

    def test_generic_rows_mark_an_inactive_lead(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_tasks_rows(
            "Projects",
            [{"lead": GONE}, {"lead": HERE}],
            [("Lead", "lead.name", False)],
            empty="none",
        )
        out: str = _flat(capsys)
        assert '"Ana Ruiz" (inactive)' in out and '"Bo Chen" (inactive)' not in out

    def test_members_are_marked_through_the_nested_user(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_tasks_rows(
            "Members",
            [{"role": "editor", "user": GONE}],
            [("Name", "user.name", False)],
            empty="none",
        )
        assert '"Ana Ruiz" (inactive)' in _flat(capsys)

    def test_the_briefing_marks_participants(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_task_briefing(
            {
                "task": {"key": "ENG-1", "title": "t"},
                "participants": [{"user": GONE, "role": "collaborator"}],
            }
        )
        assert '"Ana Ruiz" (inactive)' in _flat(capsys)

    def test_the_users_table_marks_inactive_people(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_users_table(
            [
                {"uuid": U1, "full_name": "Ana Ruiz", "is_active": False},
                {"uuid": U2, "full_name": "Bo Chen"},
            ]
        )
        out: str = _flat(capsys)
        assert "Ana Ruiz (inactive)" in out and "Bo Chen (inactive)" not in out

    def test_the_field_survives_in_json_untouched(self) -> None:
        assert json.loads(json.dumps({"owner": GONE}))["owner"]["is_active"] is False


class TestReports:
    def test_item_badges_and_an_inactive_owner_render(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_report_document(
            {
                "sections": [
                    {
                        "title": "Overdue",
                        "count": 1,
                        "items": [
                            {
                                "type": "task",
                                "title": "Ship it",
                                "owner": GONE,
                                "badges": ["owner_inactive"],
                            }
                        ],
                    }
                ]
            }
        )
        out: str = _flat(capsys)
        assert "owner_inactive" in out and '"Ana Ruiz" (inactive)' in out

    def test_a_skipped_run_explains_itself(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_report_runs(
            PaginatedResult(
                results=[
                    {"period_key": "2026-W40", "status": "skipped", "error": "recipient_inactive"}
                ],
                count=1,
            )
        )
        out: str = _flat(capsys)
        assert "skipped" in out and "no active recipient" in out.lower()

    def test_a_skipped_delivery_explains_itself(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_route_deliveries(
            PaginatedResult(
                results=[
                    {"created_at": "2026-09-30", "status": "skipped", "error": "recipient_inactive"}
                ],
                count=1,
            )
        )
        assert "no active recipient" in _flat(capsys).lower()
