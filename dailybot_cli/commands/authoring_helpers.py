"""Parsing and validation helpers for forms & check-ins authoring commands.

These helpers do **shape/format validation only**. Authorization (who may create
or edit what) is enforced server-side by role — the CLI never approximates it.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

import click
import questionary

from dailybot_cli.api_client import DailyBotClient
from dailybot_cli.commands.public_api_helpers import (
    resolve_team_by_name_or_uuid,
    resolve_user_by_name_or_uuid,
)
from dailybot_cli.display import print_error

# Question types accepted by the server. Anything else is rejected with 400.
VALID_QUESTION_TYPES: tuple[str, ...] = ("text", "multiple_choice", "boolean", "numeric")
# Server-side ceiling; mirrored here so the CLI fails fast on obviously-too-many.
MAX_QUESTIONS: int = 50
# Per-question extras (short report title + alternate phrasings). Limits mirror
# the server contract so the CLI fails fast; the server stays authoritative.
SHORT_QUESTION_MAX_LEN: int = 512
VARIATIONS_MAX: int = 10
# Question logic (conditional/branching) vocabulary, mirroring the server contract.
# The operator set is the *union* across question types (text/numeric/mc/boolean);
# the server enforces which operators are legal for a given type, so the CLI stays
# lenient here to avoid false rejections.
LOGIC_OPERATORS: tuple[str, ...] = (
    "is_equal_to",
    "is_not_equal_to",
    "contains",
    "not_contains",
    "begins_with",
    "not_begins_with",
    "ends_with",
    "not_ends_with",
    "lower_than",
    "lower_or_equal_than",
    "greater_than",
    "greater_or_equal_than",
)
LOGIC_ACTIONS: tuple[str, ...] = ("jump_to", "trigger_checkin", "trigger_form")
LOGIC_CONNECTORS: tuple[str, ...] = ("and", "or")
# Sentinel target meaning "jump to the end of the questionnaire".
LOGIC_JUMP_TO_END: int = -1
# Schedule validation: ISO weekday ints (0=Sunday .. 6=Saturday) and HH:MM time.
MIN_WEEKDAY: int = 0
MAX_WEEKDAY: int = 6
_TIME_PATTERN: re.Pattern[str] = re.compile(r"^\d{2}:\d{2}$")

# Check-in configuration enums + constraints (mirror the server contract so the
# CLI fails fast; the server remains the source of truth). ``frequency_type`` is
# weekly-only — monthly/custom cadences are driven by ``frequency_advanced``
# (+ ``frequency_cron`` for custom).
FREQUENCY_TYPES: tuple[str, ...] = ("weekly",)
PRIVACY_LEVELS: tuple[str, ...] = (
    "only_owner",
    "owner_and_members",
    "managers_and_members",
    "managers_and_admins",
    "org_admins",
    "everyone",
    "custom",
)
REMINDER_CONDITIONS: tuple[str, ...] = ("smart_frequency", "fixed_frequency")
REMINDER_TONES: tuple[str, ...] = ("standard", "persuasive")
FREQUENCY_ADVANCED: tuple[str, ...] = ("disabled", "monthly", "custom")
REMINDERS_MAX_COUNT: int = 5
REMINDER_INTERVAL_MAX: int = 60
# AI / smart check-in: max clarifying follow-up questions per response.
MAX_CLARIFYING_QUESTIONS: int = 5
INTRO_OUTRO_MIN_LEN: int = 3
INTRO_OUTRO_MAX_LEN: int = 1024
# Standard 5-field cron (minute hour day-of-month month day-of-week); the server
# does the full parse — we only fail fast on an obviously wrong field count.
CRON_FIELD_COUNT: int = 5
_DATE_PATTERN: re.Pattern[str] = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REPORT_TIME_PATTERN: re.Pattern[str] = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")


class AuthoringError(click.ClickException):
    """A user-facing validation error for authoring input.

    Rendered through ``display.print_error`` (stderr) and exits non-zero, so
    command callbacks don't need to wrap helper calls in try/except.
    """

    def show(self, file: Any = None) -> None:
        print_error(self.message)


def question_extras_options(func: Any) -> Any:
    """Attach the shared per-question extra flags (short title, variations, logic).

    Applied to ``questions add`` and ``questions edit`` on both check-ins and forms.
    Dest names match ``resolve_question_extras`` kwargs so callbacks can forward
    them directly.
    """
    options: list[Any] = [
        click.option(
            "--short-question",
            "short_question",
            default=None,
            help="Short title shown in web & chat reports (<=512 chars).",
        ),
        click.option(
            "--variation",
            "variations_raw",
            multiple=True,
            help="Alternate phrasing rotated per run (repeatable; up to 10).",
        ),
        click.option(
            "--logic-file",
            "logic_file",
            default=None,
            help='Path to a JSON question-logic object ({"rules": {...}}).',
        ),
        click.option(
            "--jump-if-equals",
            "jump_if_equals",
            default=None,
            help="Inline logic: answer value that triggers the jump (needs --jump-to).",
        ),
        click.option(
            "--jump-to",
            "jump_to",
            type=int,
            default=None,
            help="Inline logic: target question index to jump to (-1 = end).",
        ),
        click.option(
            "--else-jump-to",
            "else_jump_to",
            type=int,
            default=None,
            help="Inline logic: fallback target when the condition doesn't match "
            "(default -1 = end).",
        ),
    ]
    for option in reversed(options):
        func = option(func)
    return func


def parse_options(raw: str | None) -> list[str] | None:
    """Split a comma-separated ``--options`` string into a trimmed list."""
    if raw is None:
        return None
    options: list[str] = [part.strip() for part in raw.split(",") if part.strip()]
    return options or None


def build_question(
    question_type: str,
    question: str,
    *,
    options: list[str] | None = None,
    required: bool = True,
    is_blocker: bool = False,
    short_question: str | None = None,
    variations: list[str] | None = None,
    logic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a validated question payload (explicit ``question_type``/``question``).

    Enforces the type whitelist, that ``multiple_choice`` carries options, that
    other types do not, and that the question text is non-empty. ``is_blocker``
    tags the question as the blocker prompt (common on boolean check-in Qs).
    ``short_question`` (report title), ``variations`` (alternate phrasings), and
    ``logic`` (conditional branching) are optional per-question extras; callers
    pass already-validated values (see ``resolve_question_extras``).
    """
    qtype: str = question_type.strip().lower()
    if qtype not in VALID_QUESTION_TYPES:
        raise AuthoringError(
            f"Invalid question type '{question_type}'. "
            f"Choose from: {', '.join(VALID_QUESTION_TYPES)}."
        )
    text: str = question.strip()
    if not text:
        raise AuthoringError("Question text is required.")

    payload: dict[str, Any] = {
        "question_type": qtype,
        "question": text,
        "required": required,
        "is_blocker": is_blocker,
    }
    if qtype == "multiple_choice":
        if not options:
            raise AuthoringError(
                "Multiple-choice questions require at least one option (use --options)."
            )
        payload["options"] = options
    elif options:
        raise AuthoringError(f"'{qtype}' questions do not take options.")
    if short_question is not None:
        payload["short_question"] = validate_short_question(short_question)
    if variations is not None:
        payload["variations"] = variations
    if logic is not None:
        payload["logic"] = logic
    return payload


def build_question_edit_fields(
    question: str | None,
    question_type: str | None,
    options: str | None,
    required: bool | None,
    is_blocker: bool | None = None,
    *,
    short_question: str | None = None,
    variations: list[str] | None = None,
    logic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a partial question-update payload from provided edit flags.

    Only shape checks run here; the server does full validation. ``build_question``
    isn't reused because edits are partial (no required question/type pairing).
    Omitted flags are not sent (non-destructive PATCH). ``short_question`` /
    ``variations`` / ``logic`` arrive already validated from
    ``resolve_question_extras``.
    """
    fields: dict[str, Any] = {}
    if question is not None:
        fields["question"] = question
    if question_type is not None:
        fields["question_type"] = question_type
    if options is not None:
        fields["options"] = parse_options(options) or []
    if required is not None:
        fields["required"] = required
    if is_blocker is not None:
        fields["is_blocker"] = is_blocker
    if short_question is not None:
        fields["short_question"] = validate_short_question(short_question)
    if variations is not None:
        fields["variations"] = variations
    if logic is not None:
        fields["logic"] = logic
    return fields


def validate_short_question(text: str) -> str:
    """Trim and length-check a per-question report title (``short_question``)."""
    stripped: str = text.strip()
    if not stripped:
        raise AuthoringError("--short-question cannot be empty.")
    if len(stripped) > SHORT_QUESTION_MAX_LEN:
        raise AuthoringError(
            f"--short-question must be at most {SHORT_QUESTION_MAX_LEN} characters "
            f"(got {len(stripped)})."
        )
    return stripped


def build_variations(raw: tuple[str, ...] | list[str]) -> list[str] | None:
    """Validate alternate phrasings; returns ``None`` when none were provided.

    Each variation must be non-empty (whitespace-only rejected) and the count is
    capped at ``VARIATIONS_MAX`` — mirroring ``invalid_question_variations``.
    """
    if not raw:
        return None
    variations: list[str] = []
    for item in raw:
        text: str = str(item).strip()
        if not text:
            raise AuthoringError("Question variations cannot be empty.")
        variations.append(text)
    if len(variations) > VARIATIONS_MAX:
        raise AuthoringError(
            f"Too many variations ({len(variations)}); the limit is {VARIATIONS_MAX}."
        )
    return variations


def _validate_logic_condition(condition: Any) -> None:
    if not isinstance(condition, dict):
        raise AuthoringError("Each logic condition must be an object.")
    operator: Any = condition.get("operator")
    if operator not in LOGIC_OPERATORS:
        raise AuthoringError(
            f"Invalid logic operator '{operator}'. Choose from: {', '.join(LOGIC_OPERATORS)}."
        )
    if "comparison_value" not in condition:
        raise AuthoringError("Each logic condition needs a 'comparison_value'.")
    connector: Any = condition.get("logic_connector", "and")
    if connector not in LOGIC_CONNECTORS:
        raise AuthoringError(
            f"Invalid logic connector '{connector}'. Choose from: {', '.join(LOGIC_CONNECTORS)}."
        )


def _validate_logic_action(action: Any) -> None:
    if not isinstance(action, dict):
        raise AuthoringError("A logic action must be an object with 'action' and 'target'.")
    act: Any = action.get("action")
    if act not in LOGIC_ACTIONS:
        raise AuthoringError(
            f"Invalid logic action '{act}'. Choose from: {', '.join(LOGIC_ACTIONS)}."
        )
    target: Any = action.get("target")
    if act == "jump_to":
        if not isinstance(target, int) or isinstance(target, bool):
            raise AuthoringError(
                "A 'jump_to' action needs an integer 'target' (question index, or -1 for end)."
            )
    elif not isinstance(target, str) or not target:
        raise AuthoringError(f"A '{act}' action needs a string 'target' (a UUID).")


def validate_logic(logic: Any) -> dict[str, Any]:
    """Validate a question-logic object's structure against the server contract.

    Checks the ``rules`` envelope, each ``rules_if`` rule's conditions/action, and
    the **required** ``rules_else`` fallback action. Forward-only jump targets and
    per-type operator/value legality are enforced by the server (it owns the
    question index); this fails fast on obvious structural mistakes.
    """
    if not isinstance(logic, dict):
        raise AuthoringError("Question logic must be a JSON object.")
    rules: Any = logic.get("rules")
    if not isinstance(rules, dict):
        raise AuthoringError('Question logic must have a "rules" object.')
    rules_if: Any = rules.get("rules_if", [])
    if not isinstance(rules_if, list):
        raise AuthoringError('"rules_if" must be a list of rules.')
    for rule in rules_if:
        if not isinstance(rule, dict):
            raise AuthoringError("Each logic rule must be an object.")
        conditions: Any = rule.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            raise AuthoringError("Each logic rule needs a non-empty 'conditions' list.")
        for condition in conditions:
            _validate_logic_condition(condition)
        _validate_logic_action(rule.get("then"))
    rules_else: Any = rules.get("rules_else")
    if not isinstance(rules_else, dict):
        raise AuthoringError(
            'Question logic must include a "rules_else" fallback action '
            "(what happens when no condition matches — the server requires it)."
        )
    _validate_logic_action(rules_else)
    return logic


def _coerce_comparison_value(raw: str) -> Any:
    """Coerce an inline ``--jump-if-equals`` string to the value type it implies.

    ``true``/``false`` (case-insensitive) become JSON booleans, which is what the
    server requires for boolean questions. Everything else stays a string; for
    numeric comparisons use ``--logic-file`` with an explicit number.
    """
    lowered: str = raw.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    return raw


def build_question_logic(
    *,
    logic_file: str | None = None,
    jump_if_equals: str | None = None,
    jump_to: int | None = None,
    else_jump_to: int | None = None,
) -> dict[str, Any] | None:
    """Assemble question logic from a JSON file or an inline single-jump rule.

    ``--logic-file`` carries the full ``{rules: {...}}`` structure. The inline
    ``--jump-if-equals VALUE --jump-to N`` pair is a convenience for the common
    "branch on one answer" case; ``--else-jump-to`` sets the fallback (defaults to
    ``-1`` = end). Returns ``None`` when neither is provided. Jump targets must be
    forward (greater than this question's index) or ``-1`` — the server enforces it.
    """
    if logic_file:
        try:
            raw: str = Path(logic_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise AuthoringError(f"Cannot read logic file '{logic_file}': {exc}") from exc
        try:
            data: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthoringError(f"Logic file '{logic_file}' is not valid JSON: {exc}") from exc
        return validate_logic(data)
    if jump_to is not None:
        if jump_if_equals is None:
            raise AuthoringError(
                "--jump-to requires --jump-if-equals (the answer that triggers the jump)."
            )
        logic: dict[str, Any] = {
            "rules": {
                "rules_if": [
                    {
                        "conditions": [
                            {
                                "operator": "is_equal_to",
                                "comparison_value": _coerce_comparison_value(jump_if_equals),
                                "logic_connector": "and",
                            }
                        ],
                        "then": {"action": "jump_to", "target": jump_to},
                    }
                ],
                "rules_else": {
                    "action": "jump_to",
                    "target": else_jump_to if else_jump_to is not None else LOGIC_JUMP_TO_END,
                },
            }
        }
        return validate_logic(logic)
    if jump_if_equals is not None:
        raise AuthoringError("--jump-if-equals requires --jump-to (the target question index).")
    if else_jump_to is not None:
        raise AuthoringError("--else-jump-to only applies with --jump-if-equals and --jump-to.")
    return None


def resolve_question_extras(
    *,
    short_question: str | None = None,
    variations_raw: tuple[str, ...] = (),
    logic_file: str | None = None,
    jump_if_equals: str | None = None,
    jump_to: int | None = None,
    else_jump_to: int | None = None,
) -> dict[str, Any]:
    """Turn the shared question-extra flags into validated ``build_question`` kwargs.

    Returns only the keys the caller supplied, so both add (full) and edit
    (partial) paths can splat the result without sending untouched fields.
    """
    extras: dict[str, Any] = {}
    if short_question is not None:
        extras["short_question"] = validate_short_question(short_question)
    variations: list[str] | None = build_variations(variations_raw)
    if variations is not None:
        extras["variations"] = variations
    logic: dict[str, Any] | None = build_question_logic(
        logic_file=logic_file,
        jump_if_equals=jump_if_equals,
        jump_to=jump_to,
        else_jump_to=else_jump_to,
    )
    if logic is not None:
        extras["logic"] = logic
    return extras


def parse_questions_file(path: str) -> list[dict[str, Any]]:
    """Load and validate a JSON array of question objects from ``path``.

    Accepts both field conventions (``question_type``/``question`` or
    ``type``/``label``) and enforces ``MAX_QUESTIONS``.
    """
    try:
        raw: str = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise AuthoringError(f"Cannot read questions file '{path}': {exc}") from exc
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthoringError(f"Questions file '{path}' is not valid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise AuthoringError("Questions file must be a JSON array of question objects.")
    if len(data) > MAX_QUESTIONS:
        raise AuthoringError(f"Too many questions ({len(data)}); the limit is {MAX_QUESTIONS}.")

    questions: list[dict[str, Any]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise AuthoringError(f"Question #{index + 1} must be an object.")
        qtype: str = str(item.get("question_type") or item.get("type") or "")
        qtext: str = str(item.get("question") or item.get("label") or "")
        raw_options: Any = item.get("options")
        options: list[str] | None = (
            [str(option) for option in raw_options] if isinstance(raw_options, list) else None
        )
        required: bool = bool(item.get("required", True))
        is_blocker: bool = bool(item.get("is_blocker", False))
        extras: dict[str, Any] = {}
        raw_short: Any = item.get("short_question")
        if raw_short is not None:
            extras["short_question"] = validate_short_question(str(raw_short))
        raw_variations: Any = item.get("variations")
        if raw_variations is not None:
            if not isinstance(raw_variations, list):
                raise AuthoringError(
                    f"Question #{index + 1}: 'variations' must be a list of strings."
                )
            built: list[str] | None = build_variations([str(v) for v in raw_variations])
            if built is not None:
                extras["variations"] = built
        raw_logic: Any = item.get("logic")
        if raw_logic is not None:
            extras["logic"] = validate_logic(raw_logic)
        questions.append(
            build_question(
                qtype,
                qtext,
                options=options,
                required=required,
                is_blocker=is_blocker,
                **extras,
            )
        )
    return questions


def _validate_schedule_dict(schedule: dict[str, Any]) -> dict[str, Any]:
    """Validate the shape of a schedule dict (``days``, ``time``); leave tz to server."""
    validated: dict[str, Any] = dict(schedule)
    if "days" in validated:
        days: Any = validated["days"]
        if not isinstance(days, list) or not all(
            isinstance(day, int) and MIN_WEEKDAY <= day <= MAX_WEEKDAY for day in days
        ):
            raise AuthoringError(
                "Schedule days must be a list of integers 0-6 (0=Sunday .. 6=Saturday)."
            )
    if "time" in validated and not _TIME_PATTERN.match(str(validated["time"])):
        raise AuthoringError("Schedule time must be in HH:MM format (e.g. 09:00).")
    return validated


def parse_schedule(
    *,
    days: str | None = None,
    time: str | None = None,
    timezone: str | None = None,
    schedule_file: str | None = None,
) -> dict[str, Any] | None:
    """Build a schedule dict from a JSON file or individual flags.

    Returns ``None`` when nothing is provided (so the field is omitted). The
    timezone is not validated locally — the server returns ``invalid_timezone``.
    """
    if schedule_file:
        try:
            raw: str = Path(schedule_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise AuthoringError(f"Cannot read schedule file '{schedule_file}': {exc}") from exc
        try:
            data: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthoringError(
                f"Schedule file '{schedule_file}' is not valid JSON: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise AuthoringError("Schedule file must be a JSON object.")
        return _validate_schedule_dict(data)

    schedule: dict[str, Any] = {}
    if days is not None:
        parsed_days: list[int] = []
        for part in days.split(","):
            token: str = part.strip()
            if not token:
                continue
            try:
                parsed_days.append(int(token))
            except ValueError as exc:
                raise AuthoringError(
                    "Schedule days must be comma-separated integers 0-6 (0=Sunday .. 6=Saturday)."
                ) from exc
        schedule["days"] = parsed_days
    if time is not None:
        schedule["time"] = time
    if timezone is not None:
        schedule["timezone"] = timezone

    if not schedule:
        return None
    return _validate_schedule_dict(schedule)


def _check_enum(value: str, allowed: tuple[str, ...], label: str) -> str:
    normalized: str = value.strip().lower()
    if normalized not in allowed:
        raise AuthoringError(f"Invalid {label} '{value}'. Choose from: {', '.join(allowed)}.")
    return normalized


def _check_int_range(value: int, low: int, high: int, label: str) -> int:
    if not low <= value <= high:
        raise AuthoringError(f"{label} must be between {low} and {high} (got {value}).")
    return value


def build_checkin_config(
    *,
    start_on: str | None = None,
    end_on: str | None = None,
    frequency_type: str | None = None,
    frequency: int | None = None,
    is_trigger_based: bool | None = None,
    use_participant_timezone: bool | None = None,
    reminders_max_count: int | None = None,
    reminders_frequency_time: int | None = None,
    reminders_trigger_condition: str | None = None,
    use_user_defined_work_days: bool | None = None,
    allow_responses_before_trigger: bool | None = None,
    allow_past_responses: bool | None = None,
    allow_future_responses: bool | None = None,
    is_anonymous: bool | None = None,
    privacy: str | None = None,
    send_reports_one_by_one: bool | None = None,
    custom_template_intro: str | None = None,
    custom_template_outro: str | None = None,
    time_for_report: str | None = None,
    reminder_tone: str | None = None,
    is_smart_checkin: bool | None = None,
    is_intelligence_enabled: bool | None = None,
    max_clarifying_questions: int | None = None,
    frequency_cron: str | None = None,
    frequency_advanced: str | None = None,
) -> dict[str, Any]:
    """Assemble a validated check-in config dict from create/config flags.

    Only fields the caller supplied (non-``None``) are included, so ``config``
    stays a partial update. Enum/range checks mirror the server contract to fail
    fast; the server remains authoritative (and rejects unknown fields with 400).
    """
    config: dict[str, Any] = {}

    for value, field, label in (
        (start_on, "start_on", "start date"),
        (end_on, "end_on", "end date"),
    ):
        if value is not None:
            if not _DATE_PATTERN.match(value):
                raise AuthoringError(f"Invalid {label} '{value}'. Use YYYY-MM-DD.")
            config[field] = value

    if frequency_type is not None:
        config["frequency_type"] = _check_enum(frequency_type, FREQUENCY_TYPES, "frequency")
    if frequency is not None:
        if frequency < 1:
            raise AuthoringError(f"--every must be >= 1 (got {frequency}).")
        config["frequency"] = frequency
    if is_trigger_based is not None:
        config["is_trigger_based"] = is_trigger_based
    if use_participant_timezone is not None:
        config["use_participant_timezone"] = use_participant_timezone

    if reminders_max_count is not None:
        config["reminders_max_count"] = _check_int_range(
            reminders_max_count, 0, REMINDERS_MAX_COUNT, "--reminders"
        )
    if reminders_frequency_time is not None:
        config["reminders_frequency_time"] = _check_int_range(
            reminders_frequency_time, 0, REMINDER_INTERVAL_MAX, "--reminder-interval"
        )
    if reminders_trigger_condition is not None:
        config["reminders_trigger_condition"] = _check_enum(
            reminders_trigger_condition, REMINDER_CONDITIONS, "reminder condition"
        )

    for flag, flag_field in (
        (use_user_defined_work_days, "use_user_defined_work_days"),
        (allow_responses_before_trigger, "allow_responses_before_trigger"),
        (allow_past_responses, "allow_past_responses"),
        (allow_future_responses, "allow_future_responses"),
        (is_anonymous, "is_anonymous"),
        (send_reports_one_by_one, "send_reports_one_by_one"),
    ):
        if flag is not None:
            config[flag_field] = flag

    if privacy is not None:
        config["privacy"] = _check_enum(privacy, PRIVACY_LEVELS, "privacy")

    for text, text_field in (
        (custom_template_intro, "custom_template_intro"),
        (custom_template_outro, "custom_template_outro"),
    ):
        if text is not None:
            if not INTRO_OUTRO_MIN_LEN <= len(text) <= INTRO_OUTRO_MAX_LEN:
                raise AuthoringError(
                    f"{text_field} must be {INTRO_OUTRO_MIN_LEN}-{INTRO_OUTRO_MAX_LEN} characters."
                )
            config[text_field] = text

    if time_for_report is not None:
        if not _REPORT_TIME_PATTERN.match(time_for_report):
            raise AuthoringError(f"Invalid --report-time '{time_for_report}'. Use HH:MM.")
        config["time_for_report"] = time_for_report

    if reminder_tone is not None:
        config["reminder_tone"] = _check_enum(reminder_tone, REMINDER_TONES, "reminder tone")

    # Smart / AI check-in. The dependency rules (intelligence needs smart; a
    # clarifying cap needs intelligence) are enforced server-side and echoed as
    # `intelligence_requires_smart_checkin` — we don't approximate them here so a
    # partial config flip (e.g. enabling intelligence on an already-smart check-in)
    # isn't rejected by the CLI before the server can decide.
    if is_smart_checkin is not None:
        config["is_smart_checkin"] = is_smart_checkin
    if is_intelligence_enabled is not None:
        config["is_intelligence_enabled"] = is_intelligence_enabled
    if max_clarifying_questions is not None:
        config["max_clarifying_questions"] = _check_int_range(
            max_clarifying_questions, 0, MAX_CLARIFYING_QUESTIONS, "--max-clarifying"
        )

    if frequency_advanced is not None:
        config["frequency_advanced"] = _check_enum(
            frequency_advanced, FREQUENCY_ADVANCED, "advanced frequency"
        )
    if frequency_cron is not None:
        if len(frequency_cron.split()) != CRON_FIELD_COUNT:
            raise AuthoringError(
                f"Invalid --cron '{frequency_cron}'. Use a 5-field cron expression "
                "(minute hour day-of-month month day-of-week), e.g. '0 9 * * 1,3,5'."
            )
        config["frequency_cron"] = frequency_cron

    return config


def build_questions_interactively() -> list[dict[str, Any]]:
    """Walk the user through building questions with questionary prompts.

    Every question passes through ``build_question``, so the interactive path
    enforces the same validation as the flag and file paths. Requires a TTY.
    """
    if not sys.stdin.isatty():
        raise AuthoringError(
            "--interactive requires a terminal. Use --questions-file or inline "
            "flags in a non-interactive context."
        )

    questions: list[dict[str, Any]] = []
    while len(questions) < MAX_QUESTIONS:
        qtype: str | None = questionary.select(
            "Question type:", choices=list(VALID_QUESTION_TYPES)
        ).ask()
        if qtype is None:
            break
        text: str | None = questionary.text("Question text:").ask()
        if text is None:
            break
        options: list[str] | None = None
        if qtype == "multiple_choice":
            raw_options: str | None = questionary.text("Options (comma-separated):").ask()
            options = parse_options(raw_options)
        required: bool | None = questionary.confirm("Required?", default=True).ask()
        is_blocker: bool | None = questionary.confirm(
            "Is this the blocker question?", default=False
        ).ask()

        try:
            questions.append(
                build_question(
                    qtype,
                    text or "",
                    options=options,
                    required=bool(required),
                    is_blocker=bool(is_blocker),
                )
            )
        except AuthoringError as exc:
            print_error(exc.message)
            continue

        if not questionary.confirm("Add another question?", default=True).ask():
            break
    return questions


def prompt_participants_interactively(client: DailyBotClient) -> dict[str, Any]:
    """Interactively pick check-in participants (teams and/or people).

    A check-in must always have at least one participant, so ``checkin create``
    calls this when none were passed on the command line. The first team is
    suggested (pre-checked) as a sensible default. Requires a TTY; returns
    ``{user_uuids?, team_uuids?}`` — an empty dict if there's no terminal, no
    directory, or nothing was selected (the caller then errors out).
    """
    if not sys.stdin.isatty():
        return {}
    teams: list[dict[str, Any]] = client.list_teams()
    users: list[dict[str, Any]] = client.list_users()
    choices: list[questionary.Choice] = []
    for index, team in enumerate(teams):
        team_uuid: str = str(team.get("uuid") or team.get("id") or "")
        if not team_uuid:
            continue
        choices.append(
            questionary.Choice(
                title=f"team · {team.get('name') or team_uuid}",
                value=("team", team_uuid),
                checked=(index == 0),  # suggest the default team
            )
        )
    for user in users:
        user_uuid: str = str(user.get("uuid") or user.get("id") or "")
        if not user_uuid:
            continue
        label: Any = user.get("name") or user.get("full_name") or user.get("email") or user_uuid
        choices.append(questionary.Choice(title=f"user · {label}", value=("user", user_uuid)))
    if not choices:
        return {}
    selected: list[tuple[str, str]] | None = questionary.checkbox(
        "Add participants — a check-in needs at least one (teams or people):",
        choices=choices,
    ).ask()
    if not selected:
        return {}
    participants: dict[str, Any] = {}
    team_ids: list[str] = [uuid for kind, uuid in selected if kind == "team"]
    user_ids: list[str] = [uuid for kind, uuid in selected if kind == "user"]
    if user_ids:
        participants["user_uuids"] = user_ids
    if team_ids:
        participants["team_uuids"] = team_ids
    return participants


def parse_participants(
    users: tuple[str, ...],
    teams: tuple[str, ...],
    client: DailyBotClient,
) -> dict[str, Any]:
    """Resolve name-or-UUID participants into ``{user_uuids, team_uuids}``.

    Empty groups are omitted. Resolution reuses the shared resolver helpers, so
    ambiguous or unknown names raise the same friendly errors as other commands.
    """
    participants: dict[str, Any] = {}
    try:
        if users:
            directory: list[dict[str, Any]] = client.list_users()
            participants["user_uuids"] = [
                resolve_user_by_name_or_uuid(directory, identifier)[0] for identifier in users
            ]
        if teams:
            team_directory: list[dict[str, Any]] = client.list_teams()
            participants["team_uuids"] = [
                resolve_team_by_name_or_uuid(team_directory, identifier)[0] for identifier in teams
            ]
    except ValueError as exc:
        # The shared resolvers raise ValueError for unknown/ambiguous names; surface
        # it as a friendly authoring error instead of an uncaught traceback.
        raise AuthoringError(str(exc)) from exc
    return participants
