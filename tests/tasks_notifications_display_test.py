"""Renderers for the notification catalog, preferences, routes, reports, runs, briefing and report documents."""

from typing import Any, ClassVar

import pytest

from dailybot_cli.api_client import PaginatedResult
from dailybot_cli.display import (
    console,
    print_briefing,
    print_my_notifications,
    print_notification_catalog,
    print_notification_routes,
    print_report_document,
    print_report_runs,
    print_reports,
    print_route_deliveries,
    print_send_test_preview,
)

CHANNEL: dict[str, str] = {"external_id": "C0000000A", "name": "eng", "type": "channel"}
USER: dict[str, Any] = {"uuid": "00000000-0000-0000-0000-0000000000c1", "name": "Ana Ruiz"}


@pytest.fixture(autouse=True)
def eighty_columns() -> Any:
    previous: int | None = console._width
    console.width = 80
    try:
        yield
    finally:
        console._width = previous


def _flat(capsys: pytest.CaptureFixture[str]) -> str:
    return " ".join(capsys.readouterr().out.split())


def _page(rows: list[dict[str, Any]], **extra: Any) -> PaginatedResult:
    return PaginatedResult(results=rows, count=len(rows), next=None, previous=None, extra=extra)


CATALOG: dict[str, Any] = {
    "groups": [
        {"key": "assignments", "title": "Assignments and mentions"},
        {"key": "tasks", "title": "Tasks"},
    ],
    "kinds": [
        {
            "key": "tasks_assigned",
            "scope": "personal",
            "group": "assignments",
            "title": "Assigned to me",
            "description": "Someone makes you the owner.",
            "supports": ["chat", "email"],
            "default": {"chat": True, "email": False},
            "immediate": True,
        },
        {
            "key": "task.completed",
            "scope": "org",
            "group": "tasks",
            "title": "Card completed",
            "description": "A card is completed.",
            "supports": ["chat"],
            "default": {"chat": False, "email": False},
            "immediate": False,
        },
    ],
}


class TestCatalog:
    def test_groups_kinds_scope_and_defaults_are_shown(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_notification_catalog(CATALOG)
        out: str = _flat(capsys)
        for text in (
            "Assignments and mentions",
            "tasks_assigned",
            "task.completed",
            "personal",
            "org",
            "Assigned to me",
        ):
            assert text in out

    def test_an_empty_catalog_says_so(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_notification_catalog({"groups": [], "kinds": []})
        assert "no notification kinds" in _flat(capsys).lower()


class TestMyNotifications:
    DATA: ClassVar[dict[str, Any]] = {
        "items": [
            {
                "kind": "tasks_assigned",
                "title": "Assigned to me",
                "supports": ["chat", "email"],
                "default": {"chat": True, "email": False},
                "stored": False,
                "chat": True,
                "email": False,
            },
            {
                "kind": "tasks_reactions",
                "title": "Reactions to what I wrote",
                "supports": ["chat", "email"],
                "default": {"chat": False, "email": False},
                "stored": True,
                "chat": True,
                "email": False,
            },
        ],
        "destination": {"type": "dm", "channel": None},
        "paused_until": None,
    }

    def test_the_matrix_shows_effective_values_and_whether_they_are_stored(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_my_notifications(self.DATA)
        out: str = _flat(capsys)
        assert "tasks_assigned" in out and "tasks_reactions" in out
        assert "default" in out and "set" in out

    def test_the_destination_is_named(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_my_notifications(self.DATA)
        assert "DM" in _flat(capsys)
        print_my_notifications(
            {**self.DATA, "destination": {"type": "channel", "channel": CHANNEL}}
        )
        out: str = _flat(capsys)
        assert "eng" in out and "C0000000A" in out

    def test_a_pause_is_reported_when_present(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_my_notifications({**self.DATA, "paused_until": "2026-12-01T00:00:00Z"})
        assert "paused until" in _flat(capsys).lower()


class TestRoutesAndDeliveries:
    ROUTE: ClassVar[dict[str, Any]] = {
        "uuid": "00000000-0000-0000-0000-0000000000a1",
        "name": "Completions",
        "enabled": True,
        "channel": CHANNEL,
        "kinds": ["task.completed", "project.health_changed"],
        "scope": {"type": "all", "uuids": []},
    }

    def test_routes_table_shows_channel_kinds_scope_and_the_whole_uuid(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_notification_routes(_page([self.ROUTE], viewer={"can_manage": True}))
        out: str = _flat(capsys)
        assert "Completions" in out and "eng" in out and "C0000000A" in out
        assert "task.completed" in out and "project.health_changed" in out
        assert "00000000-0000-0000-0000-0000000000a1" in out
        assert "…" not in out

    def test_a_member_is_told_only_admins_change_routes(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_notification_routes(_page([self.ROUTE], viewer={"can_manage": False}))
        assert "admin" in _flat(capsys).lower()

    def test_no_routes(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_notification_routes(_page([], viewer={"can_manage": True}))
        assert "no notification routes" in _flat(capsys).lower()

    def test_a_route_name_is_data_not_markup(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_notification_routes(
            _page([{**self.ROUTE, "name": "[bold red]x[/]"}], viewer={"can_manage": True})
        )
        assert "[bold red]x[/]" in _flat(capsys)
        print_notification_routes(
            _page([{**self.ROUTE, "name": "[/dim][red]x"}], viewer={"can_manage": True})
        )  # no MarkupError

    def test_deliveries(self, capsys: pytest.CaptureFixture[str]) -> None:
        rows: list[dict[str, Any]] = [
            {
                "uuid": "d1",
                "kind": "task.completed",
                "status": "sent",
                "error": None,
                "created_at": "2026-09-30T10:00:00Z",
            },
            {
                "uuid": "d2",
                "kind": "task.completed",
                "status": "failed",
                "error": "platform_not_connected",
                "created_at": "2026-09-30T10:05:00Z",
            },
        ]
        print_route_deliveries(_page(rows))
        out: str = _flat(capsys)
        assert "sent" in out and "failed" in out and "platform_not_connected" in out

    def test_no_deliveries(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_route_deliveries(_page([]))
        assert "no deliveries" in _flat(capsys).lower()


class TestReports:
    REPORT: ClassVar[dict[str, Any]] = {
        "uuid": "00000000-0000-0000-0000-0000000000b1",
        "name": "Week End",
        "kind": "week_end",
        "enabled": True,
        "weekdays": [5],
        "time": "09:00",
        "timezone": "America/Bogota",
        "channel": CHANNEL,
        "email_recipients": [USER],
        "scope": {"type": "all", "uuids": []},
        "last_run": None,
    }

    def test_the_table_shows_the_schedule_in_command_line_terms(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_reports(_page([self.REPORT], viewer={"can_manage": True}))
        out: str = _flat(capsys)
        assert (
            "Week End" in out
            and "week_end" in out
            and "fri" in out
            and "09:00" in out
            and "America/Bogota" in out
        )
        assert "00000000-0000-0000-0000-0000000000b1" in out

    def test_a_report_without_a_channel_shows_its_recipients(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_reports(_page([{**self.REPORT, "channel": None}], viewer={"can_manage": True}))
        out: str = _flat(capsys)
        assert "Ana Ruiz" in out

    def test_runs(self, capsys: pytest.CaptureFixture[str]) -> None:
        rows: list[dict[str, Any]] = [
            {
                "uuid": "r1",
                "period_key": "2026-W40",
                "status": "sent",
                "error": None,
                "channel_message_id": "bm-1",
                "email_count": 1,
                "is_test": True,
                "scheduled_for": "2026-09-30T10:38:30Z",
                "sent_at": "2026-09-30T10:38:31Z",
            }
        ]
        print_report_runs(_page(rows))
        out: str = _flat(capsys)
        assert "2026-W40" in out and "sent" in out and "test" in out

    def test_no_reports_and_no_runs(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_reports(_page([], viewer={"can_manage": True}))
        assert "no scheduled reports" in _flat(capsys).lower()
        print_report_runs(_page([]))
        assert "no runs" in _flat(capsys).lower()


DOCUMENT: dict[str, Any] = {
    "kind": "week_end",
    "locale": "en",
    "header": {
        "title": "Week in review",
        "period_key": "2026-W40",
        "period_label": "Week of Sep 28 to Oct 04, 2026",
        "scope": {"type": "all", "uuids": []},
    },
    "sections": [
        {
            "key": "completed_week",
            "title": "Completed this week",
            "count": 1,
            "empty": False,
            "items": [
                {
                    "type": "task",
                    "uuid": "t1",
                    "key": "ENG-4",
                    "title": "Rotate the API keys",
                    "url": "https://x.test/ENG-4",
                    "badges": [],
                    "due_date": "2026-09-30",
                    "state": "Done",
                    "category": "done",
                }
            ],
        },
        {
            "key": "slipped_week",
            "title": "Slipped",
            "count": 14,
            "empty": False,
            "items": [
                {
                    "type": "task",
                    "uuid": f"t{i}",
                    "key": f"ENG-{i}",
                    "title": f"Late {i}",
                    "url": "",
                    "badges": ["overdue"],
                    "owner": USER,
                    "due_date": "2026-09-28",
                    "state": "To do",
                    "category": "todo",
                }
                for i in range(10, 20)
            ],
        },
        {
            "key": "projects",
            "title": "Projects at risk",
            "count": 1,
            "empty": False,
            "items": [
                {
                    "type": "project",
                    "uuid": "p1",
                    "title": "Platform",
                    "url": "",
                    "badges": ["at_risk"],
                    "owner": USER,
                    "health": "at_risk",
                }
            ],
        },
        {
            "key": "milestones",
            "title": "Milestones",
            "count": 1,
            "empty": False,
            "items": [
                {
                    "type": "milestone",
                    "uuid": "m1",
                    "title": "Public beta (Platform)",
                    "url": "",
                    "badges": [],
                    "due_date": "2026-10-04",
                }
            ],
        },
        {
            "key": "goals",
            "title": "Goals",
            "count": 1,
            "empty": False,
            "items": [
                {
                    "type": "goal",
                    "uuid": "g1",
                    "title": "Ship v2",
                    "url": "",
                    "badges": ["on_track"],
                }
            ],
        },
        {
            "key": "load_by_owner",
            "title": "Open work by owner",
            "count": 1,
            "empty": False,
            "items": [
                {
                    "type": "text",
                    "uuid": "u1",
                    "title": "Ana Ruiz — 4 open",
                    "url": "",
                    "badges": [],
                }
            ],
        },
        {"key": "blocked", "title": "Blocked", "count": 0, "empty": True, "items": []},
    ],
    "empty": False,
}


class TestReportDocument:
    def test_header_sections_and_every_item_type(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_report_document(DOCUMENT)
        out: str = _flat(capsys)
        for text in (
            "Week in review",
            "Week of Sep 28",
            "Completed this week",
            "ENG-4",
            "Rotate the API keys",
            "2026-09-30",
            "Platform",
            "at_risk",
            "Public beta (Platform)",
            "2026-10-04",
            "Ship v2",
            "on_track",
            "Ana Ruiz — 4 open",
            "overdue",
        ):
            assert text in out

    def test_more_is_the_count_minus_the_items_shown(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_report_document(DOCUMENT)
        assert "+4 more" in _flat(capsys)

    def test_a_saturated_count_is_shown_as_a_floor(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        doc: dict[str, Any] = {**DOCUMENT, "sections": [{**DOCUMENT["sections"][1], "count": 200}]}
        print_report_document(doc)
        assert "200+" in _flat(capsys)

    def test_empty_sections_are_said_plainly(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_report_document(DOCUMENT)
        out: str = _flat(capsys)
        assert "Blocked" in out and "none" in out.lower()

    def test_a_wholly_empty_document_says_there_is_nothing_to_report(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_report_document(
            {
                **DOCUMENT,
                "sections": [
                    {"key": "a", "title": "Overdue", "count": 0, "empty": True, "items": []}
                ],
                "empty": True,
            }
        )
        assert "nothing to report" in _flat(capsys).lower()

    def test_a_narrative_comes_first(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_report_document({**DOCUMENT, "narrative": "A quiet week with one slip."})
        out: str = " ".join(capsys.readouterr().out.split())
        assert out.index("A quiet week") < out.index("Completed this week")

    def test_item_text_is_data_not_markup(self, capsys: pytest.CaptureFixture[str]) -> None:
        doc: dict[str, Any] = {
            **DOCUMENT,
            "header": {**DOCUMENT["header"], "title": "[/dim][bold red]x"},
            "sections": [
                {
                    "key": "a",
                    "title": "[/]S",
                    "count": 1,
                    "empty": False,
                    "items": [
                        {
                            "type": "task",
                            "uuid": "t",
                            "key": "K-1",
                            "title": "[/dim][red]boom",
                            "url": "",
                            "badges": ["[/]"],
                        }
                    ],
                }
            ],
        }
        print_report_document(doc)  # must not raise a MarkupError
        assert "K-1" in _flat(capsys)

    def test_missing_keys_do_not_crash(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_report_document({"sections": [{"title": "Only a title", "items": [{"title": "x"}]}]})
        assert "Only a title" in _flat(capsys)


class TestBriefingAndPreview:
    BRIEFING: ClassVar[dict[str, Any]] = {
        "enabled": True,
        "weekdays": [1, 2, 3, 4, 5],
        "time": "08:30",
        "timezone": "UTC",
        "timezone_is_default": True,
        "chat": True,
        "email": False,
        "skip_when_empty": True,
        "effective": False,
        "last_sent_at": None,
    }

    def test_the_briefing_shows_schedule_and_delivery(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_briefing(self.BRIEFING)
        out: str = _flat(capsys)
        assert "mon,tue,wed,thu,fri" in out and "08:30" in out and "UTC" in out
        assert "DM" in out and "email" in out.lower()

    def test_a_default_timezone_is_labelled(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_briefing(self.BRIEFING)
        assert "default" in _flat(capsys).lower()

    def test_not_effective_is_explained(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_briefing(self.BRIEFING)
        assert "not" in _flat(capsys).lower()

    def test_a_route_dry_run_preview_shows_channel_and_text(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_send_test_preview(
            {
                "dry_run": True,
                "channel": CHANNEL,
                "text": "Dailybot Tasks test message",
                "sent": False,
            }
        )
        out: str = _flat(capsys)
        assert (
            "eng" in out
            and "C0000000A" in out
            and "Dailybot Tasks test message" in out
            and "nothing was sent" in out.lower()
        )

    def test_a_report_dry_run_preview_renders_the_document_and_recipients(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        print_send_test_preview(
            {
                "dry_run": True,
                "document": DOCUMENT,
                "channel": CHANNEL,
                "email_recipients": [USER],
                "sent": False,
            }
        )
        out: str = _flat(capsys)
        assert "Week in review" in out and "Ana Ruiz" in out and "eng" in out
