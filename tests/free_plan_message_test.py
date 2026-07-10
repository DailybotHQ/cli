"""The free-plan gating message must name what FREE actually still allows.

The allowlist (FREE_PLAN_ALLOWLIST) permits agent reports, agent emails, agent
messages/health, reading your own profile (me/org), and viewing today's pending
check-ins (cli_status). The user-facing message should not omit a whole
category, or a developer on FREE won't know `dailybot checkin list` still works.
"""

from dailybot_cli.commands.public_api_helpers import ERROR_CODE_MESSAGES


def test_message_mentions_pending_checkins() -> None:
    msg = ERROR_CODE_MESSAGES["plan_upgrade_required"].lower()
    assert "check-in" in msg


def test_message_mentions_reports_and_profile() -> None:
    msg = ERROR_CODE_MESSAGES["plan_upgrade_required"].lower()
    assert "report" in msg
    assert "profile" in msg


def test_message_does_not_promise_paid_only_features() -> None:
    msg = ERROR_CODE_MESSAGES["plan_upgrade_required"].lower()
    for gated in ("kudos", "workflow", "form"):
        assert gated not in msg
