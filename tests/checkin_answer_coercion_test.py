"""A check-in answer must be sent in the type its question declares.

The API rejects `{"response": "false"}` for a boolean question with
`["response is not valid"]`, so every check-in carrying a boolean (or numeric)
question was impossible to complete from the CLI while answers were strings.
"""

from typing import Any

import pytest

from dailybot_cli.commands.user_scoped_actions import build_checkin_responses

BOOL_Q: dict[str, Any] = {"uuid": "q-bool", "question_type": "boolean"}
TEXT_Q: dict[str, Any] = {"uuid": "q-text", "question_type": "text"}
NUM_Q: dict[str, Any] = {"uuid": "q-num", "question_type": "numeric"}


def _response(question: dict[str, Any], answer: Any) -> Any:
    return build_checkin_responses([question], [answer])[0]["response"]


@pytest.mark.parametrize("raw", ["false", "False", "FALSE", "no", "n", "0"])
def test_boolean_falsey_strings_become_false(raw: str) -> None:
    assert _response(BOOL_Q, raw) is False


@pytest.mark.parametrize("raw", ["true", "True", "TRUE", "yes", "y", "1"])
def test_boolean_truthy_strings_become_true(raw: str) -> None:
    assert _response(BOOL_Q, raw) is True


def test_boolean_passes_through_actual_bool() -> None:
    assert _response(BOOL_Q, True) is True
    assert _response(BOOL_Q, False) is False


def test_boolean_rejects_unparseable_answer() -> None:
    with pytest.raises(ValueError, match="boolean"):
        _response(BOOL_Q, "maybe")


def test_numeric_string_becomes_number() -> None:
    assert _response(NUM_Q, "42") == 42
    assert _response(NUM_Q, "3.5") == 3.5


def test_numeric_rejects_unparseable_answer() -> None:
    with pytest.raises(ValueError, match="number"):
        _response(NUM_Q, "lots")


def test_text_answer_is_untouched() -> None:
    assert _response(TEXT_Q, "false") == "false"
    assert _response(TEXT_Q, "42") == "42"


def test_payload_keeps_uuid_and_index() -> None:
    payload = build_checkin_responses([TEXT_Q, BOOL_Q], ["hi", "yes"])
    assert payload == [
        {"uuid": "q-text", "index": 0, "response": "hi"},
        {"uuid": "q-bool", "index": 1, "response": True},
    ]
