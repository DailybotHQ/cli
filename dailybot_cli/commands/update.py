"""Update command for Dailybot CLI."""

from typing import Any

import click
import httpx

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.config import get_agent_auth
from dailybot_cli.display import console, print_error, print_info, print_update_result


def _require_auth() -> DailyBotClient:
    """Ensure user is authenticated, return a client.

    Accepts either a Bearer login session or an org API key — the server now
    honours ``X-API-KEY`` on ``POST /v1/cli/updates/``.
    """
    if get_agent_auth() is None:
        print_error("Not authenticated. Run: dailybot login or set DAILYBOT_API_KEY")
        raise SystemExit(1)
    return DailyBotClient()


@click.command()
@click.argument("message", required=False)
@click.option("--done", "-d", help="What you completed.")
@click.option("--doing", "-w", help="What you are working on.")
@click.option("--blocked", "-b", help="Any blockers.")
def update(
    message: str | None,
    done: str | None,
    doing: str | None,
    blocked: str | None,
) -> None:
    """Submit a check-in update.

    You can provide a free-text message or use structured flags:

    \b
      dailybot update "I finished the auth module and now working on tests."
      dailybot update --done "Auth module" --doing "Tests" --blocked "None"
    """
    client: DailyBotClient = _require_auth()

    # If no args at all, prompt for input
    if not message and not done and not doing and not blocked:
        print_info("Enter your update (press Enter twice to submit):")
        lines: list[str] = []
        empty_count: int = 0
        while True:
            try:
                line: str = input()
            except EOFError:
                break
            if line == "":
                empty_count += 1
                if empty_count >= 1 and lines:
                    break
                lines.append("")
            else:
                empty_count = 0
                lines.append(line)
        message = "\n".join(lines).strip()
        if not message:
            print_error("Empty update. Nothing sent.")
            raise SystemExit(1)

    try:
        with console.status("Submitting update..."):
            result: dict[str, Any] = client.submit_update(
                message=message,
                done=done,
                doing=doing,
                blocked=blocked,
            )
        print_update_result(result)
    except httpx.TimeoutException:
        print_error(
            "The request timed out. Dailybot may be processing your update — "
            "please check your check-ins before retrying."
        )
        raise SystemExit(1)
    except APIError as e:
        if e.status_code in (401, 403):
            print_error("Session expired. Please log in again: dailybot login")
        elif e.status_code == 400 and "ai processing failed" in e.detail.lower():
            print_error(
                "Dailybot could not process your message. "
                "Please try again, and if the issue persists contact support@dailybot.com"
            )
        else:
            print_error(e.detail)
        raise SystemExit(1)
