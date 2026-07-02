import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from dailybot_cli.tui.app import DailybotChatApp
from dailybot_cli.tui.intents import KudosIntent, TerminalCheckinIntent


def test_kudos_flow_uses_numbered_user_selection() -> None:
    client: MagicMock = MagicMock()
    client.list_users.return_value = [
        {"uuid": "self-uuid", "full_name": "Me"},
        {"uuid": "peer-uuid", "full_name": "Andres Prieto"},
    ]
    client.list_teams.return_value = []
    client.auth_status.return_value = {"user": {"uuid": "self-uuid"}}
    app = DailybotChatApp(client)
    _stub_output(app)

    asyncio.run(
        app._start_kudos_flow(
            KudosIntent(receiver_query="Andres", message="this amazing new feature")
        )
    )
    asyncio.run(app._select_kudos_user("1"))
    asyncio.run(app._set_kudos_value(""))
    asyncio.run(app._confirm_kudos("1"))

    client.give_kudos.assert_called_once_with(
        content="this amazing new feature",
        user_uuid_receivers=["peer-uuid"],
        team_uuid_receivers=None,
        company_value=None,
    )


def test_checkins_flow_submits_answers_after_numbered_selection() -> None:
    client: MagicMock = MagicMock()
    client.get_status.return_value = {
        "pending_checkins": [
            {
                "followup_uuid": "followup-uuid",
                "followup_name": "Daily Standup",
                "template_questions": [
                    {
                        "uuid": "q1",
                        "question": (
                            "Previous plan ({previous_response_date}): "
                            "{previous_response_#2}"
                        ),
                    },
                    {"uuid": "q2", "question": "Blocked?", "question_type": "boolean"},
                ],
            }
        ]
    }
    client.get_checkin.return_value = {
        "id": "followup-uuid",
        "name": "Daily Standup",
        "template": "template-uuid",
    }
    client.get_template.return_value = {
        "questions": {
            "fields": [
                {
                    "uuid": "q1",
                    "question": "Previous plan (Jun 30): Continue with the CLI",
                },
                {"uuid": "q2", "question": "Blocked?", "question_type": "boolean"},
            ]
        }
    }
    app = DailybotChatApp(client)
    _stub_output(app)

    asyncio.run(app._start_checkins_flow())
    asyncio.run(app._select_checkin("1"))
    asyncio.run(app._answer_checkin_question("Built the CLI flow"))
    asyncio.run(app._answer_checkin_question("2"))

    client.complete_checkin.assert_called_once_with(
        "followup-uuid",
        [
            {"uuid": "q1", "index": 0, "response": "Built the CLI flow"},
            {"uuid": "q2", "index": 1, "response": False},
        ],
        1,
    )
    question_prompt: str = app._write_dailybot.call_args_list[1].args[0]
    assert "Continue with the CLI" in question_prompt
    assert "{previous_response" not in question_prompt


def test_checkin_edit_flow_keeps_and_replaces_answers() -> None:
    client: MagicMock = MagicMock()
    client.list_checkins.return_value = [{"id": "followup-uuid", "name": "Daily Standup"}]
    client.list_checkin_responses.return_value = [
        {
            "uuid": "daily-uuid",
            "responses": [
                {"question": "What did you do?", "response": {"value": "Old work"}},
                {"question": "Blocked?", "response": True},
            ],
        }
    ]
    client.get_checkin.return_value = {
        "id": "followup-uuid",
        "name": "Daily Standup",
        "template": "template-uuid",
    }
    client.get_template.return_value = {
        "questions": {
            "fields": [
                {"uuid": "q1", "question": "What did you do?"},
                {"uuid": "q2", "question": "Blocked?", "question_type": "boolean"},
            ]
        }
    }
    app = DailybotChatApp(client)
    _stub_output(app)

    asyncio.run(app._handle_terminal_checkin_intent(TerminalCheckinIntent(action="edit")))
    asyncio.run(app._select_checkin_to_edit("1"))
    asyncio.run(app._answer_checkin_edit_question(""))
    asyncio.run(app._answer_checkin_edit_question("2"))

    question_prompt: str = app._write_dailybot.call_args_list[1].args[0]
    assert "Current answer: Old work" in question_prompt
    assert "Current answer: {}" not in question_prompt
    client.update_checkin_response.assert_called_once_with(
        "followup-uuid",
        [
            {"uuid": "q1", "index": 0, "response": {"value": "Old work"}},
            {"uuid": "q2", "index": 1, "response": False},
        ],
        1,
    )


def test_form_submit_flow_collects_answers() -> None:
    client: MagicMock = MagicMock()
    client.list_forms.return_value = [
        {
            "id": "form-uuid",
            "name": "Code Release",
            "questions": [{"uuid": "q1", "question": "What shipped?"}],
        }
    ]
    app = DailybotChatApp(client)
    _stub_output(app)

    asyncio.run(app._start_forms_flow("submit"))
    asyncio.run(app._select_form_action("1"))
    asyncio.run(app._answer_form_submit_question("Interactive CLI"))

    client.submit_form_response.assert_called_once_with(
        "form-uuid",
        {"q1": "Interactive CLI"},
    )


def test_form_update_flow_keeps_existing_answers() -> None:
    client: MagicMock = MagicMock()
    form: dict[str, object] = {
        "id": "form-uuid",
        "name": "Code Release",
        "questions": [{"uuid": "q1", "question": "What shipped?"}],
    }
    response: dict[str, object] = {
        "id": "response-uuid",
        "content": {"q1": {"value": "Old summary"}},
    }
    app = DailybotChatApp(client)
    _stub_output(app)

    asyncio.run(app._start_form_update_flow(form, response))
    asyncio.run(app._answer_form_update_question(""))

    client.update_form_response.assert_called_once_with(
        "form-uuid",
        "response-uuid",
        {"q1": {"value": "Old summary"}},
    )


def test_form_transition_flow_uses_allowed_transition() -> None:
    client: MagicMock = MagicMock()
    form: dict[str, object] = {"id": "form-uuid", "name": "Code Release"}
    response: dict[str, object] = {
        "id": "response-uuid",
        "allowed_transitions": [{"to_state": "qa", "label": "QA"}],
    }
    app = DailybotChatApp(client)
    _stub_output(app)

    app._start_form_transition_flow(form, response)
    asyncio.run(app._select_form_transition("1"))
    asyncio.run(app._set_form_transition_note("Ready for QA"))

    client.transition_form_response.assert_called_once_with(
        "form-uuid",
        "response-uuid",
        "qa",
        "Ready for QA",
    )


def test_form_delete_flow_confirms_before_delete() -> None:
    client: MagicMock = MagicMock()
    form: dict[str, object] = {"id": "form-uuid", "name": "Code Release"}
    response: dict[str, object] = {"id": "response-uuid"}
    app = DailybotChatApp(client)
    _stub_output(app)

    app._start_form_delete_flow(form, response)
    asyncio.run(app._confirm_form_delete("1"))

    client.delete_form_response.assert_called_once_with("form-uuid", "response-uuid")


def test_checkin_reset_flow_confirms_before_delete() -> None:
    client: MagicMock = MagicMock()
    app = DailybotChatApp(client)
    _stub_output(app)
    app.pending_flow = {
        "type": "checkin_reset_confirm",
        "candidate": {"checkin": {"id": "followup-uuid", "name": "Daily Standup"}},
    }

    asyncio.run(app._confirm_checkin_reset("1"))

    client.delete_checkin_response.assert_called_once_with(
        "followup-uuid",
        response_date=date.today().isoformat(),
    )


def test_mood_flow_tracks_score() -> None:
    client: MagicMock = MagicMock()
    app = DailybotChatApp(client)
    _stub_output(app)

    asyncio.run(app._start_mood_flow())
    asyncio.run(app._select_mood("5"))

    client.track_mood.assert_called_once_with(5)


def test_structured_terminal_action_launches_native_flow() -> None:
    client: MagicMock = MagicMock()
    app = DailybotChatApp(client)
    _stub_output(app)
    app._start_kudos_menu = AsyncMock()  # type: ignore[method-assign]

    asyncio.run(app._handle_chat_actions([{"type": "terminal_flow", "flow": "kudos"}]))
    asyncio.run(app._confirm_terminal_action("1"))

    app._start_kudos_menu.assert_called_once()


def test_slash_tab_completion_cycles_matching_commands() -> None:
    client: MagicMock = MagicMock()
    app = DailybotChatApp(client)

    completed = app._command_completion("/fo", 3)

    assert completed is not None
    assert completed[0] == "/forms"
    prompt = _FakePrompt(value=completed[0], cursor_position=completed[1])
    app._cycle_completion(prompt)  # type: ignore[arg-type]
    assert prompt.value == "/form submit"


def test_slash_shift_tab_completion_cycles_backwards() -> None:
    client: MagicMock = MagicMock()
    app = DailybotChatApp(client)

    completed = app._command_completion("/fo", 3)

    assert completed is not None
    prompt = _FakePrompt(value=completed[0], cursor_position=completed[1])
    app._cycle_completion(prompt, reverse=True)  # type: ignore[arg-type]
    assert prompt.value == "/form delete"


def test_slash_shift_tab_completion_starts_from_last_match() -> None:
    client: MagicMock = MagicMock()
    app = DailybotChatApp(client)

    completed = app._command_completion("/fo", 3, reverse=True)

    assert completed is not None
    assert completed[0] == "/form delete"


def test_mention_tab_completion_supports_users_and_teams() -> None:
    client: MagicMock = MagicMock()
    app = DailybotChatApp(client)

    user_completed = app._mention_completion(
        "kudos @an",
        len("kudos @an"),
        ["@Andres Prieto", "@Engineering team"],
    )
    team_completed = app._mention_completion(
        "kudos @eng",
        len("kudos @eng"),
        ["@Andres Prieto", "@Engineering team"],
    )

    assert user_completed is not None
    assert user_completed[0] == "kudos @Andres Prieto"
    assert team_completed is not None
    assert team_completed[0] == "kudos @Engineering team"


def test_mention_tab_completion_cycles_matches() -> None:
    client: MagicMock = MagicMock()
    app = DailybotChatApp(client)

    completed = app._mention_completion(
        "kudos @and",
        len("kudos @and"),
        ["@Andres Prieto", "@Andrea Dailybot"],
    )

    assert completed is not None
    prompt = _FakePrompt(value=completed[0], cursor_position=completed[1])
    app._cycle_completion(prompt)  # type: ignore[arg-type]
    assert prompt.value == "kudos @Andrea Dailybot"


def test_mention_shift_tab_completion_cycles_backwards() -> None:
    client: MagicMock = MagicMock()
    app = DailybotChatApp(client)

    completed = app._mention_completion(
        "kudos @and",
        len("kudos @and"),
        ["@Andres Prieto", "@Andrea Dailybot"],
    )

    assert completed is not None
    prompt = _FakePrompt(value=completed[0], cursor_position=completed[1])
    app._cycle_completion(prompt, reverse=True)  # type: ignore[arg-type]
    assert prompt.value == "kudos @Andrea Dailybot"


def _stub_output(app: DailybotChatApp) -> None:
    app._write_dailybot = MagicMock()  # type: ignore[method-assign]
    app._write_error = MagicMock()  # type: ignore[method-assign]
    app._set_loading = MagicMock()  # type: ignore[method-assign]
    app._set_prompt_hint = MagicMock()  # type: ignore[method-assign]


class _FakePrompt:
    def __init__(self, *, value: str, cursor_position: int) -> None:
        self.value = value
        self.cursor_position = cursor_position
