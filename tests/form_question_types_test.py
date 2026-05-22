"""Tests for form question prompting helpers."""

from dailybot_cli.commands.user_scoped_actions import _classify_form_question_type


class TestFormQuestionTypes:
    def test_classify_text(self) -> None:
        assert _classify_form_question_type({"question_type": "text_field"}) == "text"

    def test_classify_numeric(self) -> None:
        assert _classify_form_question_type({"question_type": "numeric"}) == "numeric"
        assert _classify_form_question_type({"type": "integer"}) == "numeric"

    def test_classify_boolean(self) -> None:
        assert _classify_form_question_type({"question_type": "boolean"}) == "boolean"
        assert _classify_form_question_type({"question_type": "yes_no"}) == "boolean"

    def test_classify_choice_by_type(self) -> None:
        assert _classify_form_question_type({"question_type": "single_choice"}) == "choice"

    def test_classify_choice_by_options(self) -> None:
        assert (
            _classify_form_question_type(
                {"question_type": "text_field", "choices": ["Low", "High"]},
            )
            == "choice"
        )
