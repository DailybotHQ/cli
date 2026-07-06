"""Tests for forms & check-ins authoring helpers and display renderers."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from dailybot_cli import display
from dailybot_cli.commands.authoring_helpers import (
    MAX_QUESTIONS,
    AuthoringError,
    build_checkin_config,
    build_form_audience,
    build_form_config,
    build_question,
    build_question_edit_fields,
    build_question_logic,
    build_variations,
    build_workflow,
    parse_options,
    parse_participants,
    parse_questions_file,
    parse_schedule,
    parse_workflow_states,
    require_short_question,
    require_short_questions,
    resolve_form_config,
    resolve_question_extras,
    validate_command,
    validate_logic,
    validate_short_question,
)


class TestBuildQuestion:
    def test_text_question(self) -> None:
        result: dict[str, Any] = build_question("text", "What went well?")
        assert result == {
            "question_type": "text",
            "question": "What went well?",
            "required": True,
            "is_blocker": False,
        }

    def test_multiple_choice_with_options(self) -> None:
        result: dict[str, Any] = build_question(
            "multiple_choice", "Rating?", options=["A", "B"], required=False
        )
        assert result["options"] == ["A", "B"]
        assert result["required"] is False

    def test_invalid_type_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_question("rating", "How many stars?")

    def test_multiple_choice_without_options_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_question("multiple_choice", "Rating?")

    def test_boolean_with_options_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_question("boolean", "Blockers?", options=["Yes", "No"])

    def test_blank_text_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_question("text", "   ")

    def test_type_is_normalized(self) -> None:
        assert build_question("TEXT", "Q?")["question_type"] == "text"

    def test_is_blocker_defaults_false(self) -> None:
        assert build_question("boolean", "Blocked?")["is_blocker"] is False

    def test_is_blocker_flag_forwarded(self) -> None:
        assert build_question("boolean", "Blocked?", is_blocker=True)["is_blocker"] is True


class TestBuildQuestionEditFields:
    def test_empty_when_nothing_provided(self) -> None:
        assert build_question_edit_fields(None, None, None, None) == {}

    def test_blocker_toggle_forwarded(self) -> None:
        assert build_question_edit_fields(None, None, None, None, is_blocker=True) == {
            "is_blocker": True
        }

    def test_blocker_none_omitted(self) -> None:
        assert "is_blocker" not in build_question_edit_fields("Q?", None, None, None, None)


class TestQuestionExtras:
    def test_short_question_trimmed(self) -> None:
        assert validate_short_question("  Yesterday  ") == "Yesterday"

    def test_short_question_empty_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            validate_short_question("   ")

    def test_short_question_too_long_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            validate_short_question("x" * 513)

    def test_variations_built(self) -> None:
        assert build_variations(("What happened?", " What went well? ")) == [
            "What happened?",
            "What went well?",
        ]

    def test_variations_empty_tuple_is_none(self) -> None:
        assert build_variations(()) is None

    def test_variations_whitespace_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_variations(("ok", "   "))

    def test_variations_over_limit_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_variations(tuple(f"v{i}" for i in range(11)))

    def test_inline_jump_logic_built(self) -> None:
        logic = build_question_logic(jump_if_equals="Yes", jump_to=3)
        assert logic == {
            "rules": {
                "rules_if": [
                    {
                        "conditions": [
                            {
                                "operator": "is_equal_to",
                                "comparison_value": "Yes",
                                "logic_connector": "and",
                            }
                        ],
                        "then": {"action": "jump_to", "target": 3},
                    }
                ],
                "rules_else": {"action": "jump_to", "target": -1},
            }
        }

    def test_inline_boolean_value_coerced(self) -> None:
        logic = build_question_logic(jump_if_equals="true", jump_to=2)
        assert logic is not None
        cond = logic["rules"]["rules_if"][0]["conditions"][0]
        assert cond["comparison_value"] is True

    def test_inline_else_jump_to_forwarded(self) -> None:
        logic = build_question_logic(jump_if_equals="x", jump_to=3, else_jump_to=2)
        assert logic is not None
        assert logic["rules"]["rules_else"] == {"action": "jump_to", "target": 2}

    def test_else_jump_to_alone_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_question_logic(else_jump_to=2)

    def test_logic_missing_rules_else_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            validate_logic(
                {
                    "rules": {
                        "rules_if": [
                            {
                                "conditions": [
                                    {"operator": "is_equal_to", "comparison_value": "Yes"}
                                ],
                                "then": {"action": "jump_to", "target": 2},
                            }
                        ]
                    }
                }
            )

    def test_extended_numeric_operator_accepted(self) -> None:
        logic = {
            "rules": {
                "rules_if": [
                    {
                        "conditions": [{"operator": "greater_than", "comparison_value": 5}],
                        "then": {"action": "jump_to", "target": 3},
                    }
                ],
                "rules_else": {"action": "jump_to", "target": -1},
            }
        }
        assert validate_logic(logic) is logic

    def test_jump_to_without_value_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_question_logic(jump_to=3)

    def test_jump_if_without_target_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_question_logic(jump_if_equals="Yes")

    def test_no_logic_is_none(self) -> None:
        assert build_question_logic() is None

    def test_validate_logic_accepts_trigger_action(self) -> None:
        logic = {
            "rules": {
                "rules_if": [
                    {
                        "conditions": [{"operator": "contains", "comparison_value": "bug"}],
                        "then": {"action": "trigger_form", "target": "form-uuid"},
                    }
                ],
                "rules_else": {"action": "jump_to", "target": -1},
            }
        }
        assert validate_logic(logic) is logic

    def test_validate_logic_bad_operator_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            validate_logic(
                {
                    "rules": {
                        "rules_if": [
                            {
                                "conditions": [{"operator": "gt", "comparison_value": "5"}],
                                "then": {"action": "jump_to", "target": 1},
                            }
                        ]
                    }
                }
            )

    def test_validate_logic_jump_needs_int_target(self) -> None:
        with pytest.raises(AuthoringError):
            validate_logic(
                {
                    "rules": {
                        "rules_if": [
                            {
                                "conditions": [
                                    {"operator": "is_equal_to", "comparison_value": "Yes"}
                                ],
                                "then": {"action": "jump_to", "target": "nope"},
                            }
                        ]
                    }
                }
            )

    def test_validate_logic_requires_rules(self) -> None:
        with pytest.raises(AuthoringError):
            validate_logic({"foo": "bar"})

    def test_resolve_extras_merges_all(self) -> None:
        extras = resolve_question_extras(
            short_question="Yesterday",
            variations_raw=("What did you do?",),
            jump_if_equals="No",
            jump_to=-1,
        )
        assert extras["short_question"] == "Yesterday"
        assert extras["variations"] == ["What did you do?"]
        assert extras["logic"]["rules"]["rules_if"][0]["then"]["target"] == -1

    def test_resolve_extras_empty(self) -> None:
        assert resolve_question_extras() == {}

    def test_build_question_carries_extras(self) -> None:
        payload = build_question(
            "text",
            "What did you do?",
            short_question="Yesterday",
            variations=["What happened?"],
        )
        assert payload["short_question"] == "Yesterday"
        assert payload["variations"] == ["What happened?"]

    def test_require_short_question_ok_when_provided(self) -> None:
        require_short_question("Title", False)  # no raise

    def test_require_short_question_ok_when_ai_optin(self) -> None:
        require_short_question(None, True)  # no raise

    def test_require_short_question_raises_when_missing(self) -> None:
        with pytest.raises(AuthoringError):
            require_short_question(None, False)

    def test_require_short_questions_names_missing(self) -> None:
        questions = [
            {"question": "a", "short_question": "A"},
            {"question": "b"},  # missing
            {"question": "c"},  # missing
        ]
        with pytest.raises(AuthoringError, match="#2, #3"):
            require_short_questions(questions, False)

    def test_require_short_questions_skipped_with_ai(self) -> None:
        require_short_questions([{"question": "b"}], True)  # no raise


class TestParseOptions:
    def test_splits_and_trims(self) -> None:
        assert parse_options("a, b ,c") == ["a", "b", "c"]

    def test_none_passthrough(self) -> None:
        assert parse_options(None) is None

    def test_empty_becomes_none(self) -> None:
        assert parse_options(" , ") is None


class TestParseQuestionsFile:
    def test_valid_file(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "questions.json"
        path.write_text(
            json.dumps(
                [
                    {"question_type": "text", "question": "What went well?"},
                    {"type": "multiple_choice", "label": "Rating?", "options": ["A", "B"]},
                ]
            )
        )
        result: list[dict[str, Any]] = parse_questions_file(str(path))
        assert len(result) == 2
        assert result[1]["question_type"] == "multiple_choice"
        assert result[1]["question"] == "Rating?"

    def test_is_blocker_read_from_file(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "questions.json"
        path.write_text(json.dumps([{"type": "boolean", "label": "Blocked?", "is_blocker": True}]))
        result: list[dict[str, Any]] = parse_questions_file(str(path))
        assert result[0]["is_blocker"] is True

    def test_extras_read_from_file(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "questions.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "question_type": "text",
                        "question": "What did you do?",
                        "short_question": "Yesterday",
                        "variations": ["What happened?", "What went well?"],
                        "logic": {
                            "rules": {
                                "rules_if": [
                                    {
                                        "conditions": [
                                            {"operator": "contains", "comparison_value": "bug"}
                                        ],
                                        "then": {"action": "jump_to", "target": 2},
                                    }
                                ],
                                "rules_else": {"action": "jump_to", "target": -1},
                            }
                        },
                    }
                ]
            )
        )
        result: list[dict[str, Any]] = parse_questions_file(str(path))
        assert result[0]["short_question"] == "Yesterday"
        assert result[0]["variations"] == ["What happened?", "What went well?"]
        assert result[0]["logic"]["rules"]["rules_if"][0]["then"]["target"] == 2

    def test_bad_logic_in_file_rejected(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "questions.json"
        path.write_text(json.dumps([{"type": "text", "label": "Q?", "logic": {"no": "rules"}}]))
        with pytest.raises(AuthoringError):
            parse_questions_file(str(path))

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(AuthoringError):
            parse_questions_file(str(tmp_path / "nope.json"))

    def test_non_array_rejected(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "q.json"
        path.write_text(json.dumps({"not": "a list"}))
        with pytest.raises(AuthoringError):
            parse_questions_file(str(path))

    def test_invalid_json_rejected(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "q.json"
        path.write_text("{not json")
        with pytest.raises(AuthoringError):
            parse_questions_file(str(path))

    def test_limit_exceeded_rejected(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "q.json"
        path.write_text(
            json.dumps(
                [{"question_type": "text", "question": f"Q{i}"} for i in range(MAX_QUESTIONS + 1)]
            )
        )
        with pytest.raises(AuthoringError):
            parse_questions_file(str(path))


class TestParseSchedule:
    def test_from_flags(self) -> None:
        result: dict[str, Any] | None = parse_schedule(
            days="1,2,3,4,5", time="09:00", timezone="UTC"
        )
        assert result == {"days": [1, 2, 3, 4, 5], "time": "09:00", "timezone": "UTC"}

    def test_none_when_empty(self) -> None:
        assert parse_schedule() is None

    def test_bad_day_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            parse_schedule(days="1,9")

    def test_non_integer_day_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            parse_schedule(days="mon,tue")

    def test_bad_time_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            parse_schedule(time="9am")

    def test_from_file(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "sched.json"
        path.write_text(json.dumps({"days": [0], "time": "10:30", "timezone": "UTC"}))
        result: dict[str, Any] | None = parse_schedule(schedule_file=str(path))
        assert result == {"days": [0], "time": "10:30", "timezone": "UTC"}

    def test_file_with_bad_day_rejected(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "sched.json"
        path.write_text(json.dumps({"days": [7]}))
        with pytest.raises(AuthoringError):
            parse_schedule(schedule_file=str(path))


class TestBuildCheckinConfig:
    def test_empty_when_nothing_passed(self) -> None:
        assert build_checkin_config() == {}

    def test_only_provided_fields_included(self) -> None:
        cfg = build_checkin_config(reminders_max_count=3, reminders_frequency_time=30)
        assert cfg == {"reminders_max_count": 3, "reminders_frequency_time": 30}

    def test_toggles_forwarded(self) -> None:
        cfg = build_checkin_config(allow_past_responses=False, is_anonymous=True)
        assert cfg == {"allow_past_responses": False, "is_anonymous": True}

    def test_frequency_and_privacy_normalized(self) -> None:
        cfg = build_checkin_config(frequency_type="WEEKLY", privacy="everyone")
        assert cfg["frequency_type"] == "weekly"
        assert cfg["privacy"] == "everyone"

    def test_invalid_frequency_rejected(self) -> None:
        # frequency_type is weekly-only now; monthly/custom moved to
        # frequency_advanced, so both are rejected here.
        with pytest.raises(AuthoringError):
            build_checkin_config(frequency_type="yearly")
        with pytest.raises(AuthoringError):
            build_checkin_config(frequency_type="monthly")

    def test_reminder_count_out_of_range_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_checkin_config(reminders_max_count=9)

    def test_reminder_interval_out_of_range_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_checkin_config(reminders_frequency_time=120)

    def test_invalid_privacy_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_checkin_config(privacy="nobody")

    def test_bad_start_date_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_checkin_config(start_on="07/05/2026")

    def test_short_intro_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_checkin_config(custom_template_intro="hi")

    def test_reminder_tone_normalized(self) -> None:
        cfg = build_checkin_config(reminder_tone="STANDARD")
        assert cfg == {"reminder_tone": "standard"}

    def test_invalid_reminder_tone_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_checkin_config(reminder_tone="chirpy")

    def test_ai_fields_forwarded(self) -> None:
        cfg = build_checkin_config(
            is_smart_checkin=True, is_intelligence_enabled=True, max_clarifying_questions=2
        )
        assert cfg == {
            "is_smart_checkin": True,
            "is_intelligence_enabled": True,
            "max_clarifying_questions": 2,
        }

    def test_max_clarifying_out_of_range_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_checkin_config(max_clarifying_questions=9)

    def test_advanced_frequency_and_cron_forwarded(self) -> None:
        cfg = build_checkin_config(frequency_advanced="custom", frequency_cron="0 9 * * 1,3,5")
        assert cfg == {"frequency_advanced": "custom", "frequency_cron": "0 9 * * 1,3,5"}

    def test_invalid_frequency_advanced_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_checkin_config(frequency_advanced="hourly")

    def test_malformed_cron_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_checkin_config(frequency_cron="0 9 * *")  # only 4 fields


class TestBuildFormConfig:
    def test_empty_when_nothing_passed(self) -> None:
        assert build_form_config() == {}

    def test_toggles_forwarded(self) -> None:
        cfg = build_form_config(is_active=False, is_anonymous=True, use_for_approval=True)
        assert cfg == {"is_active": False, "is_anonymous": True, "use_for_approval": True}

    def test_command_sets_enabled(self) -> None:
        cfg = build_form_config(command="Release")
        assert cfg == {"command": "release", "command_enabled": True}

    def test_no_command_disables(self) -> None:
        assert build_form_config(command_enabled=False) == {"command_enabled": False}

    def test_invalid_command_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_form_config(command="Bad Command!")


class TestFormWorkflowAndAudience:
    def test_parse_states(self) -> None:
        assert parse_workflow_states(("Draft:#ccc", "Done:#2ecc71")) == [
            {"label": "Draft", "color": "#ccc"},
            {"label": "Done", "color": "#2ecc71"},
        ]

    def test_state_missing_color_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            parse_workflow_states(("Draft",))

    def test_state_bad_color_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            parse_workflow_states(("Draft:blue",))

    def test_state_empty_label_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            parse_workflow_states((":#ccc",))

    def test_too_many_states_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            parse_workflow_states(tuple(f"S{i}:#cccccc" for i in range(21)))

    def test_build_workflow_enabled(self) -> None:
        assert build_workflow(("Draft:#ccc",), False) == {
            "enabled": True,
            "states": [{"label": "Draft", "color": "#ccc"}],
        }

    def test_build_workflow_disabled(self) -> None:
        assert build_workflow((), True) == {"enabled": False}

    def test_build_workflow_none(self) -> None:
        assert build_workflow((), False) is None

    def test_build_workflow_conflict_rejected(self) -> None:
        with pytest.raises(AuthoringError):
            build_workflow(("Draft:#ccc",), True)

    def test_audience_simple_mode(self) -> None:
        client: MagicMock = MagicMock()
        assert build_form_audience("everyone", (), (), client, "can-edit") == {"mode": "everyone"}

    def test_audience_restricted_resolves(self) -> None:
        client: MagicMock = MagicMock()
        client.list_teams.return_value = [{"uuid": "t-1", "name": "Eng"}]
        result = build_form_audience(None, (), ("Eng",), client, "can-see")
        assert result == {"mode": "restricted", "team_uuids": ["t-1"]}

    def test_audience_restricted_without_who_rejected(self) -> None:
        client: MagicMock = MagicMock()
        with pytest.raises(AuthoringError):
            build_form_audience("restricted", (), (), client, "can-edit")

    def test_audience_none(self) -> None:
        client: MagicMock = MagicMock()
        assert build_form_audience(None, (), (), client, "can-edit") is None

    def test_validate_command_normalizes(self) -> None:
        assert validate_command("Release") == "release"

    def test_resolve_form_config_full(self) -> None:
        client: MagicMock = MagicMock()
        client.list_teams.return_value = [{"uuid": "t-1", "name": "Eng"}]
        cfg = resolve_form_config(
            client,
            is_anonymous=True,
            states=("Draft:#ccc",),
            can_edit="owner_and_admins",
            change_states_teams=("Eng",),
            command="release",
        )
        assert cfg["is_anonymous"] is True
        assert cfg["workflow"] == {"enabled": True, "states": [{"label": "Draft", "color": "#ccc"}]}
        assert cfg["who_can_edit"] == {"mode": "owner_and_admins"}
        assert cfg["who_can_change_states"] == {"mode": "restricted", "team_uuids": ["t-1"]}
        assert cfg["command"] == "release"

    def test_resolve_form_config_command_conflict(self) -> None:
        client: MagicMock = MagicMock()
        with pytest.raises(AuthoringError):
            resolve_form_config(client, command="release", no_command=True)


class TestParseParticipants:
    def test_resolves_users_and_teams(self) -> None:
        client: MagicMock = MagicMock()
        client.list_users.return_value = [{"uuid": "u-1", "full_name": "Jane Doe"}]
        client.list_teams.return_value = [{"uuid": "t-1", "name": "My Team"}]

        result: dict[str, Any] = parse_participants(("Jane Doe",), ("My Team",), client)
        assert result == {"user_uuids": ["u-1"], "team_uuids": ["t-1"]}

    def test_empty_groups_omitted(self) -> None:
        client: MagicMock = MagicMock()
        assert parse_participants((), (), client) == {}
        client.list_users.assert_not_called()

    def test_unknown_user_raises_authoring_error(self) -> None:
        # The resolver raises ValueError; parse_participants must translate it to a
        # friendly AuthoringError instead of leaking an uncaught traceback.
        client: MagicMock = MagicMock()
        client.list_users.return_value = [{"uuid": "u-1", "full_name": "Jane Doe"}]
        with pytest.raises(AuthoringError):
            parse_participants(("nobody@example.com",), (), client)


class TestAuthoringDisplay:
    def test_report_channels_table(self) -> None:
        with display.console.capture() as capture:
            display.print_report_channels(
                [{"uuid": "c-1", "name": "#engineering", "platform": "slack"}]
            )
        output: str = capture.get()
        assert "engineering" in output
        assert "slack" in output

    def test_report_channels_empty(self) -> None:
        with display.console.capture() as capture:
            display.print_report_channels([])
        assert "No report channels" in capture.get()

    def test_form_created(self) -> None:
        with display.console.capture() as capture:
            display.print_form_created(
                {
                    "id": "f-1",
                    "name": "Retro",
                    "questions": [{"uuid": "q1", "question": "Well?", "question_type": "text"}],
                }
            )
        output: str = capture.get()
        assert "Retro" in output
        assert "Well?" in output

    def test_checkin_created(self) -> None:
        with display.console.capture() as capture:
            display.print_checkin_created(
                {
                    "id": "fu-1",
                    "name": "Standup",
                    "schedule": {"days": [1, 2], "time": "09:00", "timezone": "UTC"},
                    "questions": [],
                }
            )
        output: str = capture.get()
        assert "Standup" in output
        assert "09:00" in output

    def test_questions_table_empty(self) -> None:
        with display.console.capture() as capture:
            display.print_questions_table([])
        assert "No questions" in capture.get()

    def test_questions_table_renders_choices_and_blocker(self) -> None:
        with display.console.capture() as capture:
            display.print_questions_table(
                [
                    {
                        "uuid": "q1",
                        "index": 0,
                        "question": "Mood?",
                        "question_type": "multiple_choice",
                        "required": True,
                        "is_blocker": False,
                        "choices": [
                            {"label": "Great", "value": "great"},
                            {"label": "Rough", "value": "rough"},
                        ],
                    },
                    {
                        "uuid": "q2",
                        "index": 1,
                        "question": "Blocked?",
                        "question_type": "boolean",
                        "required": True,
                        "is_blocker": True,
                        "choices": [],
                    },
                ]
            )
        output: str = capture.get()
        assert "Great" in output  # {label,value} choice rendered by label
        assert "Rough" in output

    def test_questions_table_renders_extras(self) -> None:
        with display.console.capture() as capture:
            display.print_questions_table(
                [
                    {
                        "uuid": "q1",
                        "index": 0,
                        "question": "What did you do yesterday?",
                        "question_type": "text",
                        "required": True,
                        "is_blocker": False,
                        "choices": [],
                        "short_question": "Yesterday",
                        "variations": ["What happened?", "What went well?"],
                        "logic": {"rules": {"rules_if": [{"conditions": [], "then": {}}]}},
                    }
                ]
            )
        output: str = capture.get()
        assert "report title: Yesterday" in output
        assert "2 variation(s)" in output
        assert "conditional logic" in output
        assert "Blocker" in output  # blocker column header present

    def test_form_updated_title(self) -> None:
        with display.console.capture() as capture:
            display.print_form_created({"id": "f-1", "name": "Retro"}, updated=True)
        assert "Form Updated" in capture.get()

    def test_checkin_detail_renders_participants(self) -> None:
        with display.console.capture() as capture:
            display.print_checkin_detail(
                {
                    "id": "fu-1",
                    "name": "Standup",
                    "is_archived": False,
                    "schedule": {"days": [1], "time": "09:00", "timezone": "UTC"},
                    "participants": {
                        "users": [{"uuid": "u1", "name": "Jane Doe"}],
                        "teams": [{"uuid": "t1", "name": "Engineering"}],
                    },
                    "report_channels": [
                        {
                            "id": "C1",
                            "name": "general",
                            "platform": "slack",
                            "type": "channel",
                            "reporting_enabled": True,
                        }
                    ],
                    "questions": [
                        {
                            "uuid": "q1",
                            "index": 0,
                            "question": "Done?",
                            "question_type": "text",
                            "required": True,
                            "is_blocker": False,
                            "choices": [],
                        }
                    ],
                }
            )
        output: str = capture.get()
        assert "Jane Doe" in output
        assert "Engineering" in output
        assert "Done?" in output
        assert "#general" in output  # channel resolved to its name (Finding 3)

    def test_checkin_detail_renders_config_summary(self) -> None:
        with display.console.capture() as capture:
            display.print_checkin_detail(
                {
                    "id": "fu-1",
                    "name": "Standup",
                    "frequency_type": "weekly",
                    "frequency": 1,
                    "reminders_max_count": 3,
                    "reminders_frequency_time": 30,
                    "allow_past_responses": False,
                    "privacy": "everyone",
                    "questions": [],
                }
            )
        output: str = capture.get()
        assert "Frequency: weekly" in output
        assert "Reminders: 3" in output
        assert "no past reports" in output
        assert "Privacy: everyone" in output

    def test_checkin_detail_renders_ai_and_advanced_summary(self) -> None:
        with display.console.capture() as capture:
            display.print_checkin_detail(
                {
                    "id": "fu-1",
                    "name": "Standup",
                    "frequency_type": "weekly",
                    "frequency_advanced": "custom",
                    "frequency_cron": "0 9 * * 1,3,5",
                    "reminders_max_count": 2,
                    "reminder_tone": "persuasive",
                    "is_smart_checkin": True,
                    "is_intelligence_enabled": True,
                    "max_clarifying_questions": 2,
                    "questions": [],
                }
            )
        output: str = capture.get()
        assert "Advanced: custom" in output
        assert "0 9 * * 1,3,5" in output
        assert "persuasive tone" in output
        assert "AI: smart, intelligence, 2 clarifying Qs" in output

    def test_attached_channel_falls_back_to_id_when_unnamed(self) -> None:
        with display.console.capture() as capture:
            display.print_checkin_detail(
                {
                    "id": "fu-1",
                    "name": "Standup",
                    "report_channels": [{"id": "C_LEGACY", "type": "channel"}],
                    "questions": [],
                }
            )
        # Legacy entries with no name fall back to the raw channel id.
        assert "C_LEGACY" in capture.get()

    def test_forms_table_shows_archived_status(self) -> None:
        with display.console.capture() as capture:
            display.print_forms_table(
                [
                    {"id": "f-1", "name": "Active Form", "questions": []},
                    {"id": "f-2", "name": "Old Form", "questions": [], "is_archived": True},
                ]
            )
        output: str = capture.get()
        assert "archived" in output

    def test_form_detail_renders_full_config(self) -> None:
        with display.console.capture() as capture:
            display.print_form_detail(
                {
                    "id": "f-1",
                    "name": "Release Flow",
                    "is_anonymous": True,
                    "allow_public_responses": True,
                    "require_email_and_name": True,
                    "command_enabled": True,
                    "command": "release",
                    "who_can_edit": {"mode": "owner_and_admins"},
                    "who_can_see_responses": {"mode": "restricted", "team_uuids": ["t-1"]},
                    "workflow": {
                        "enabled": True,
                        "states": [
                            {"key": "draft", "label": "Draft", "color": "#ccc", "order": 0},
                            {"key": "done", "label": "Done", "color": "#2ecc71", "order": 1},
                        ],
                    },
                    "questions": [],
                }
            )
        output: str = capture.get()
        assert "@dailybot release" in output
        assert "anonymous" in output and "public" in output
        assert "owner_and_admins" in output
        assert "restricted" in output
        assert "Draft" in output and "Done" in output
