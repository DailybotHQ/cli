"""`dailybot hook` — lifecycle commands for agent harness hooks.

These commands are not meant to be typed by humans. Agent harnesses (Claude
Code, Cursor, Codex, Copilot, Gemini CLI, …) invoke them from lifecycle
hooks (session start, end of turn, after a git commit) so the agent is
deterministically reminded to send Dailybot progress reports — without the
developer or the model having to remember.

Contract with the harness:

- **Always exit 0.** A hook command must never break the developer's agent
  session, no matter what goes wrong internally.
- **Silence means "nothing to do".** Empty stdout is the common case; the
  harness only reacts when output is present.
- **Machine-readable output.** Like ``_print_org_list`` in the auth
  commands, this module intentionally bypasses ``display.py`` and emits
  plain/JSON lines via ``click.echo`` — the consumer is a harness parsing
  stdout, not a human reading a terminal.
- **No network access.** Decisions come from the local ledger
  (``dailybot_cli.ledger``) and git; the hot path never waits on the API.
"""

import json
from typing import Any

import click

from dailybot_cli import ledger

_FORMAT_CHOICES: list[str] = ["claude", "cursor", "generic"]

_STRONG_NUDGE_TEMPLATE: str = (
    "Dailybot reminder: {count} commit(s) have landed since the last progress "
    "report in this repo. If this completes a meaningful unit of work, send a "
    "progress report now using the dailybot-report skill (or `dailybot agent "
    'update "<what changed and why>"`). If work is still mid-stream, finish '
    "first and report when the unit is done."
)
_SOFT_NUDGE_MESSAGE: str = (
    "Dailybot reminder: there has been sustained work this session without a "
    "progress report. If a meaningful unit of work is complete — including "
    "non-commit work such as research, analysis, or written documents — send "
    "a progress report now using the dailybot-report skill (or `dailybot "
    "agent update`). If nothing significant happened yet, run `dailybot hook "
    "dismiss` to silence this reminder for an hour."
)
_LOGIN_NUDGE_MESSAGE: str = (
    "The Dailybot CLI is installed but not authenticated, so progress reports "
    "cannot be sent. At a natural pause, offer the developer to run `dailybot "
    "login` (or set DAILYBOT_API_KEY). Do not block their work on this."
)
_LEFTOVER_WORK_TEMPLATE: str = (
    "There are {count} unreported commit(s) in this repo from earlier "
    "sessions. Once you have context, consider sending a catch-up Dailybot "
    "progress report covering that work."
)
_LEFTOVER_PENDING_MESSAGE: str = (
    "A previous session left unreported work signals in this repo. Once you "
    "have context, consider sending a catch-up Dailybot progress report."
)


def _emit_stop(fmt: str, message: str) -> None:
    """Emit an end-of-turn reminder in the harness's hook dialect."""
    if fmt == "claude":
        click.echo(json.dumps({"decision": "block", "reason": message}))
    elif fmt == "cursor":
        click.echo(json.dumps({"followup_message": message}))
    else:
        click.echo(message)


def _emit_session_start(fmt: str, message: str) -> None:
    """Emit session-start context in the harness's hook dialect."""
    if fmt == "claude":
        click.echo(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": message,
                    }
                }
            )
        )
    elif fmt == "cursor":
        click.echo(json.dumps({"additional_context": message}))
    else:
        click.echo(message)


@click.group()
def hook() -> None:
    """Lifecycle hooks for agent harnesses (machine-oriented).

    These subcommands are wired into agent hook configs (Claude Code
    settings.json, Cursor hooks.json, etc.) so agents proactively send
    Dailybot progress reports. They read only local state (git + the
    report ledger), never call the network, and always exit 0.

    \b
      dailybot hook session-start --format claude   # SessionStart hook
      dailybot hook post-commit                     # PostToolUse on git commit
      dailybot hook activity                        # PostToolUse on file edits
      dailybot hook stop --format claude            # Stop / end-of-turn hook
      dailybot hook dismiss                         # model-invoked snooze
    """


@hook.command(name="session-start")
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(_FORMAT_CHOICES),
    default="generic",
    help="Hook output dialect of the calling harness.",
)
def hook_session_start(fmt: str) -> None:
    """Inject session-start context: login nudge and leftover unreported work.

    \b
      dailybot hook session-start --format claude
      dailybot hook session-start --format cursor
    """
    try:
        result: dict[str, Any] | None = ledger.evaluate_session_start()
    except Exception:  # hooks must never break the harness — degrade to silence
        return
    if result is None:
        return
    parts: list[str] = []
    if result["login_needed"]:
        parts.append(_LOGIN_NUDGE_MESSAGE)
    if result["unreported_commit_count"] > 0:
        parts.append(
            _LEFTOVER_WORK_TEMPLATE.format(count=result["unreported_commit_count"])
        )
    elif result["work_pending"]:
        parts.append(_LEFTOVER_PENDING_MESSAGE)
    if parts:
        _emit_session_start(fmt, " ".join(parts))


@hook.command(name="post-commit")
def hook_post_commit() -> None:
    """Record a commit signal in the report ledger (silent).

    \b
      dailybot hook post-commit
    """
    try:
        ledger.record_commit()
    except Exception:  # hooks must never break the harness — degrade to silence
        return


@hook.command(name="activity")
def hook_activity() -> None:
    """Record a file-activity signal in the report ledger (silent).

    Covers significant work that produces no commits — research notes,
    generated documents, analysis files.

    \b
      dailybot hook activity
    """
    try:
        ledger.record_activity()
    except Exception:  # hooks must never break the harness — degrade to silence
        return


@hook.command(name="stop")
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(_FORMAT_CHOICES),
    default="generic",
    help="Hook output dialect of the calling harness.",
)
def hook_stop(fmt: str) -> None:
    """End-of-turn check: remind the model to report unreported work.

    Emits nothing (exit 0) when there is nothing to report, the repo is
    disabled, a reminder fired recently, or a report was just sent.

    \b
      dailybot hook stop --format claude
      dailybot hook stop --format cursor
    """
    try:
        decision: dict[str, Any] | None = ledger.evaluate_stop()
    except Exception:  # hooks must never break the harness — degrade to silence
        return
    if decision is None:
        return
    if decision["kind"] == "commits":
        message: str = _STRONG_NUDGE_TEMPLATE.format(count=decision["commit_count"])
    else:
        message = _SOFT_NUDGE_MESSAGE
    _emit_stop(fmt, message)


@hook.command(name="dismiss")
@click.option(
    "--minutes",
    "-m",
    type=int,
    default=ledger.DEFAULT_SNOOZE_MINUTES,
    help="How long to snooze reminders for this repo.",
)
def hook_dismiss(minutes: int) -> None:
    """Snooze report reminders for this repo (model judged nothing significant).

    \b
      dailybot hook dismiss
      dailybot hook dismiss --minutes 120
    """
    try:
        ledger.dismiss(minutes=minutes)
    except Exception:  # hooks must never break the harness — degrade to silence
        return
    click.echo(f"Dailybot reminders snoozed for {minutes} minutes in this repo.")
