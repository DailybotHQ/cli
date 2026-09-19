"""Tasks error taxonomy and credential guidance (plan task 3).

The messages here are written against what the **server actually returned** in
task 1's live probe (`analysis_results/PERMISSION_MATRIX_OBSERVED.md`), not against
the handoff's documented shapes. Where the two disagree, both are handled.
"""


import pytest

from dailybot_cli.api_client import APIError
from dailybot_cli.commands.public_api_helpers import (
    ERROR_CODE_MESSAGES,
    EXIT_NOT_AUTHENTICATED,
    EXIT_NOT_FOUND,
    PERSON_SHAPED_TASKS_DOORS,
    TASKS_ERROR_CODES,
    is_person_shaped_refusal,
    resolve_error_message,
)


class TestTasksVocabularyIsComplete:
    def test_every_documented_tasks_code_has_a_message(self) -> None:
        missing: list[str] = [c for c in TASKS_ERROR_CODES if c not in ERROR_CODE_MESSAGES]
        assert missing == [], f"codes without a message: {missing}"

    @pytest.mark.parametrize("code", sorted(TASKS_ERROR_CODES))
    def test_each_message_is_one_actionable_sentence(self, code: str) -> None:
        message: str = ERROR_CODE_MESSAGES[code]
        assert message and message[0].isupper()
        # "DailyBot" (capital B) is the legacy spelling — rule 13.
        assert "DailyBot" not in message

    def test_the_observed_codes_from_the_live_probe_are_covered(self) -> None:
        # Exactly what task 1 saw on the wire.
        for observed in ("insufficient_scope", "idempotency_key_required", "invalid_credentials"):
            assert observed in ERROR_CODE_MESSAGES


class TestPersonShapedRefusal:
    """C-7 — one condition, historically two shapes."""

    def test_the_handoff_shape_is_recognised(self) -> None:
        # The pack documents 400 actor_required on me/tasks/.
        exc = APIError(status_code=400, detail="Use a signed-in person for 'me'.", code="actor_required")
        assert is_person_shaped_refusal(exc, door="me/tasks") is True

    def test_the_observed_shape_is_recognised(self) -> None:
        # Task 1 measured 403 insufficient_scope on all six doors instead.
        exc = APIError(status_code=403, detail="You do not have permission to do that.",
                       code="insufficient_scope")
        assert is_person_shaped_refusal(exc, door="me/tasks") is True

    def test_both_shapes_produce_the_same_guidance(self) -> None:
        old = APIError(status_code=400, detail="x", code="actor_required")
        new = APIError(status_code=403, detail="x", code="insufficient_scope")
        assert resolve_error_message(old, door="inbox") == resolve_error_message(new, door="inbox")

    def test_the_guidance_names_the_fix(self) -> None:
        exc = APIError(status_code=403, detail="x", code="insufficient_scope")
        assert "dailybot login" in resolve_error_message(exc, door="inbox")

    def test_a_scope_refusal_on_a_normal_door_is_not_person_shaped(self) -> None:
        # Same code, different door: this one is a genuine scope problem.
        exc = APIError(status_code=403, detail="x", code="insufficient_scope")
        assert is_person_shaped_refusal(exc, door="boards") is False

    def test_the_person_shaped_door_list_matches_what_was_measured(self) -> None:
        assert frozenset(
            {"me/tasks", "me/tasks/counts", "me/recents", "me/activity-cursor",
             "inbox", "inbox/unread-count"}
        ) == PERSON_SHAPED_TASKS_DOORS


class TestIsolationIsNotPermission:
    """C-9 — a cross-tenant uuid is invisible, not forbidden."""

    def test_not_found_never_renders_permission_language(self) -> None:
        message: str = ERROR_CODE_MESSAGES["not_found"].lower()
        for forbidden in ("permission", "forbidden", "not allowed", "access denied"):
            assert forbidden not in message

    def test_not_found_maps_to_the_not_found_exit_code(self) -> None:
        exc = APIError(status_code=404, detail="Not found.", code="not_found")
        assert resolve_error_message(exc)  # has a message
        assert EXIT_NOT_FOUND == 5


class TestAdminScopeIsUnstorable:
    """C-8 — task 1 measured this refusal against an ADMIN_ORG owner too."""

    def test_the_message_blames_the_credential_kind_not_the_role(self) -> None:
        exc = APIError(status_code=403, detail="x", code="insufficient_scope",
                       extra={"required_scope": "tasks:admin"})
        message: str = resolve_error_message(exc)
        assert "api key" in message.lower()
        assert "dailybot login" in message
        # An org admin reading "you must be an admin" would hunt for a setting
        # that cannot exist — task 1 proved an ADMIN_ORG owner gets this too.
        assert "be an admin" not in message.lower()

    def test_a_non_admin_scope_refusal_still_names_the_scope(self) -> None:
        exc = APIError(status_code=403, detail="x", code="insufficient_scope",
                       extra={"required_scope": "tasks:write"})
        assert "tasks:write" in resolve_error_message(exc)


class TestScopesDoNotNest:
    def test_write_does_not_imply_read(self) -> None:
        # A tasks:write-only key refused a read must see which scope it lacked.
        exc = APIError(status_code=403, detail="x", code="insufficient_scope",
                       extra={"required_scope": "tasks:read"})
        assert "tasks:read" in resolve_error_message(exc)

    def test_guest_not_allowed_is_distinct_from_a_scope_refusal(self) -> None:
        guest = APIError(status_code=403, detail="x", code="guest_not_allowed")
        scope = APIError(status_code=403, detail="x", code="insufficient_scope",
                         extra={"required_scope": "tasks:write"})
        assert resolve_error_message(guest) != resolve_error_message(scope)
        # The fix differs: a role change, not a credential change.
        assert "role" in resolve_error_message(guest).lower()


class TestIdempotencyCodes:
    def test_key_required_names_the_flag_that_supplies_one(self) -> None:
        assert "--idempotency-key" in ERROR_CODE_MESSAGES["idempotency_key_required"]

    def test_payload_mismatch_says_a_new_key_is_the_fix_not_a_retry(self) -> None:
        message: str = ERROR_CODE_MESSAGES["idempotency_key_payload_mismatch"].lower()
        assert "new" in message and "key" in message

    def test_in_progress_does_not_advise_retrying_immediately(self) -> None:
        assert "idempotency_in_progress" in ERROR_CODE_MESSAGES


class TestDeltaAndVolumeCodes:
    def test_window_expired_says_resnapshot_not_retry(self) -> None:
        message: str = ERROR_CODE_MESSAGES["delta_window_expired"].lower()
        assert "snapshot" in message
        assert "retry" not in message

    def test_too_many_items_names_the_cap(self) -> None:
        assert "100" in ERROR_CODE_MESSAGES["too_many_items"]

    def test_state_in_use_names_migrate_to(self) -> None:
        assert "migrate_to" in ERROR_CODE_MESSAGES["state_in_use"]


class TestAuthTaxonomy:
    @pytest.mark.parametrize(
        "code", ["credential_absent", "credential_malformed", "credential_expired",
                 "invalid_credentials", "token_not_valid"],
    )
    def test_credential_problems_point_at_login(self, code: str) -> None:
        assert "dailybot login" in ERROR_CODE_MESSAGES[code] or "key" in ERROR_CODE_MESSAGES[code].lower()

    def test_exit_code_for_a_credential_problem_is_not_authenticated(self) -> None:
        assert EXIT_NOT_AUTHENTICATED == 3


class TestExistingBehaviourUnchanged:
    def test_a_pre_existing_code_kept_its_message(self) -> None:
        assert ERROR_CODE_MESSAGES["form_response_not_found"] == "Response not found."

    def test_resolve_falls_back_to_the_server_detail_for_an_unknown_code(self) -> None:
        exc = APIError(status_code=418, detail="Server said something new.", code="brand_new_code")
        assert resolve_error_message(exc) == "Server said something new."
