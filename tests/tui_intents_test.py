from dailybot_cli.tui.intents import (
    is_checkins_intent,
    matching_teams,
    matching_users,
    parse_kudos_intent,
    parse_terminal_action_intent,
    parse_terminal_checkin_intent,
)


def test_checkins_plain_text_routes_to_native_flow() -> None:
    assert is_checkins_intent("checkins")
    assert is_checkins_intent("show my check-ins")
    assert is_checkins_intent("what checkins do I have pending?")


def test_parse_kudos_intent_with_message() -> None:
    intent = parse_kudos_intent("give kudos to Andres for this amazing new feature")

    assert intent is not None
    assert intent.receiver_query == "Andres"
    assert intent.message == "this amazing new feature"
    assert intent.receiver_kind == "auto"


def test_parse_kudos_intent_without_message() -> None:
    intent = parse_kudos_intent("send kudos to Jane Doe")

    assert intent is not None
    assert intent.receiver_query == "Jane Doe"
    assert intent.message == ""


def test_parse_kudos_intent_detects_team_receiver() -> None:
    intent = parse_kudos_intent("give kudos to Engineering team for shipping")

    assert intent is not None
    assert intent.receiver_query == "Engineering"
    assert intent.receiver_kind == "team"


def test_matching_users_filters_by_name_and_email() -> None:
    users = [
        {"uuid": "1", "full_name": "Andres Prieto", "email": "andres@example.com"},
        {"uuid": "2", "full_name": "Jane Doe", "email": "jane@example.com"},
    ]

    assert matching_users(users, "andres") == [users[0]]
    assert matching_users(users, "jane@example.com") == [users[1]]


def test_matching_teams_filters_by_name() -> None:
    teams = [
        {"uuid": "1", "name": "Engineering"},
        {"uuid": "2", "name": "Customer Success"},
    ]

    assert matching_teams(teams, "engineer") == [teams[0]]


def test_parse_terminal_checkin_intent_accepts_slash_aliases() -> None:
    assert parse_terminal_checkin_intent("/checkin").action == "complete"
    assert parse_terminal_checkin_intent("/checkin list").action == "complete"
    assert parse_terminal_checkin_intent("/checkin complete").action == "complete"
    assert parse_terminal_checkin_intent("/checkin edit").action == "edit"
    assert parse_terminal_checkin_intent("/checkin reset").action == "reset"


def test_parse_terminal_action_intent_routes_common_actions() -> None:
    assert parse_terminal_action_intent("forms").action == "forms"
    assert parse_terminal_action_intent("submit form").action == "form_submit"
    assert parse_terminal_action_intent("list users").action == "users"
    assert parse_terminal_action_intent("show teams").action == "teams"
    assert parse_terminal_action_intent("open dashboard").action == "dashboard"
    assert parse_terminal_action_intent("track mood").action == "mood"
