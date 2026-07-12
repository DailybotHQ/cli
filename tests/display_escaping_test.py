"""Tests that server-controlled text never reaches Rich as markup.

An API error `detail` (or any other remote string) may contain square brackets.
Rich reads `[...]` as a style tag, so an unescaped message either crashes with
`MarkupError` or silently applies styles/links the server chose.
"""

import httpx
import pytest
from rich.console import Console

from dailybot_cli.api_client import DailyBotClient
from dailybot_cli.display import print_error, print_info, print_success, print_warning

# Real payload seen from the API: a Django 500 page embedding a regex.
MARKUP_BOMB: str = r"closing tag [/\s] at position 3369"


@pytest.mark.parametrize("printer", [print_error, print_success, print_warning, print_info])
def test_printers_do_not_crash_on_bracketed_text(printer, capsys) -> None:
    printer(MARKUP_BOMB)  # must not raise rich.errors.MarkupError
    captured = capsys.readouterr()
    assert "position 3369" in captured.out + captured.err


@pytest.mark.parametrize("printer", [print_error, print_success, print_warning, print_info])
def test_printers_render_brackets_literally(printer, capsys) -> None:
    """A style tag in remote text survives as text instead of being applied."""
    printer("value [bold red]not-a-style[/bold red] end")
    out = capsys.readouterr()
    assert "[bold red]" in out.out + out.err


def test_printers_still_emit_their_own_styling() -> None:
    """The helper's own prefix markup must keep working after escaping."""
    console = Console(force_terminal=True, color_system="truecolor")
    with console.capture() as capture:
        console.print("[bold red]Error:[/bold red] plain")
    output: str = capture.get()
    assert "Error:" in output
    assert "plain" in output


def test_api_error_detail_from_html_body_is_not_dumped_verbatim() -> None:
    """A non-JSON error body (e.g. a Django 500 page) must not become the detail."""
    html = "<!DOCTYPE html><html><body>" + "x" * 5000 + "</body></html>"
    response = httpx.Response(
        500,
        text=html,
        headers={"content-type": "text/html"},
        request=httpx.Request("GET", "http://x"),
    )
    client = DailyBotClient(api_url="http://x", token="test-token")
    with pytest.raises(Exception) as exc:
        client._handle_response(response)
    detail = getattr(exc.value, "detail", "")
    assert "<!DOCTYPE" not in detail
    assert len(detail) < 200
    assert "500" in detail
