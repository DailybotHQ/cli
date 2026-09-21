"""One reporter for every Tasks write.

Four modules carried their own copy of "say what happened after a write", and the
copies drifted: only `task` learned to echo the idempotency key that makes a retry
safe, so `board create` minted one, never showed it, and left the caller unable to
perform the retry the documentation promises. One function, four call sites.

It also owns the escaping rule, which the copies got wrong in the other direction.
``present_untrusted`` already escapes and quotes, and ``print_success`` escapes
again — a board named ``x[y]`` reached the terminal with visible backslashes. The
message is therefore composed and printed here, escaped exactly once.
"""

from typing import Any

from rich.markup import escape

from dailybot_cli.api_client import IDEMPOTENCY_KEY_SENT_KEY
from dailybot_cli.display import console, present_untrusted

IDEMPOTENCY_TTL_HOURS: int = 24  # server-side slot lifetime, mirrored in the hint


def report_write(result: dict[str, Any], message: str) -> None:
    """Report a Tasks write: replay-aware, and echoing the key a retry needs.

    ``message`` is already-escaped markup (built with ``present_untrusted`` for any
    user-authored part), so it is printed as-is rather than escaped a second time.
    """
    if result.get("_idempotency_replayed"):
        console.print(
            f"[bold green]OK[/bold green] {message} — already applied "
            "(the server replayed a previous identical call; nothing new was written)."
        )
        return
    console.print(f"[bold green]OK[/bold green] {message}")
    key: Any = result.get(IDEMPOTENCY_KEY_SENT_KEY)
    if key:
        # Without this the guarantee is unreachable: re-running the command mints a
        # fresh uuid4, which the server cannot recognise, so the "safe retry" the
        # help describes would duplicate.
        console.print(
            f"[dim]Idempotency key: {escape(str(key))} — pass it with --idempotency-key "
            f"to make a retry of this exact call safe for {IDEMPOTENCY_TTL_HOURS}h.[/dim]"
        )


def named(result: dict[str, Any], fallback: str, *, field: str = "name") -> str:
    """The object's name as quoted, escaped data — never as a sentence."""
    return present_untrusted(result.get(field) or fallback)
