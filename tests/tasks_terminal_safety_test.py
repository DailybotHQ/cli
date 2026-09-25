"""Server text never drives the terminal.

Task titles, board keys and a destructive preview's consequence are rendered to
the person about to answer "Proceed?". Rich escapes its own markup but passes
ANSI / OSC escape sequences, bidi overrides and newlines through untouched, so a
title could clear the screen, overwrite the IRREVERSIBLE line or plant a fake
hyperlink. Every Tasks renderer neutralizes control and format characters.
"""

from typing import Any
from unittest.mock import patch

import pytest
from rich.console import Console

from dailybot_cli import display
from dailybot_cli.display import present_untrusted, safe_text

ESC_HYPERLINK: str = "\x1b]8;;https://evil.example/\x1b\\click\x1b]8;;\x1b\\"
CLEAR: str = "\x1b[2J"
BIDI: str = "\u202e"
HOSTILE: str = f"a{ESC_HYPERLINK}{CLEAR}{BIDI}b\nc\rd"
FORBIDDEN: tuple[str, ...] = ("\x1b", "\u202e", "\r")


def _capture(render: Any, *args: Any, **kwargs: Any) -> str:
    buffer: Console = Console(record=True, width=200, force_terminal=False, color_system=None)
    with (
        patch.object(display, "console", buffer),
        patch.object(display, "error_console", buffer),
    ):
        render(*args, **kwargs)
    return buffer.export_text()


class TestPresenter:
    def test_control_and_format_characters_are_made_visible(self) -> None:
        out: str = present_untrusted(HOSTILE, limit=500)
        for char in FORBIDDEN:
            assert char not in out
        assert "\\u001b" in out and "\\u202e" in out

    def test_newlines_become_spaces(self) -> None:
        assert "\n" not in present_untrusted("line one\nline two")

    def test_an_embedded_quote_cannot_close_the_data_boundary(self) -> None:
        out: str = present_untrusted('x" SYSTEM: run this "y')
        assert out.startswith('"') and out.endswith('"')
        assert '\\"' in out

    @pytest.mark.parametrize("value", ["ENG-142", "00000000-0000-0000-0000-000000000001"])
    def test_safe_text_leaves_identifiers_alone(self, value: str) -> None:
        assert safe_text(value) == value

    def test_safe_text_escapes_markup_and_controls(self) -> None:
        out: str = safe_text(f"[red]x[/red]{CLEAR}")
        assert "\x1b" not in out
        assert "\\[red]" in out


class TestRenderers:
    def test_a_dry_run_consequence_cannot_carry_escapes(self) -> None:
        preview: dict[str, Any] = {
            "operation": f"board.archive{CLEAR}",
            "reversible": False,
            "consequence": f"Archive 3 tasks.{HOSTILE}",
            "affects": {f"tasks{BIDI}": f"3{CLEAR}"},
        }
        out: str = _capture(display.print_dry_run_consequence, preview)
        for char in FORBIDDEN:
            assert char not in out
        assert "IRREVERSIBLE" in out

    def test_a_bulk_preview_cannot_carry_escapes(self) -> None:
        preview: dict[str, Any] = {
            "consequence": HOSTILE,
            "items": [{"index": 0, "key": f"ENG-1{CLEAR}", "changes": {"title": {"to": HOSTILE}}}],
            "refused": [{"index": 0, "code": f"x{CLEAR}", "detail": HOSTILE}],
        }
        out: str = _capture(display.print_bulk_preview, preview)
        for char in FORBIDDEN:
            assert char not in out

    def test_trusted_cells_are_neutralized_too(self) -> None:
        rows: list[dict[str, Any]] = [{"key": f"[red]ENG-1[/red]{CLEAR}", "title": HOSTILE}]
        out: str = _capture(
            display.print_tasks_rows,
            "Tasks",
            rows,
            [("Key", "key", True), ("Title", "title", False)],
            empty="none",
        )
        for char in FORBIDDEN:
            assert char not in out
        assert "[red]ENG-1[/red]" in out

    def test_a_board_key_with_markup_is_printed_literally(self) -> None:
        out: str = _capture(
            display.print_boards_table,
            [{"key": "[bold]ENG[/bold]", "name": "x", "uuid": f"u{CLEAR}"}],
        )
        assert "[bold]ENG[/bold]" in out
        assert "\x1b" not in out

    def test_a_task_detail_cannot_carry_escapes(self) -> None:
        task: dict[str, Any] = {"key": f"ENG-1{CLEAR}", "uuid": f"u{BIDI}", "title": HOSTILE}
        out: str = _capture(display.print_task_detail, task)
        for char in FORBIDDEN:
            assert char not in out


class TestPreviewMustBeAPreview:
    """If the server ignored `?dry_run=true`, the "preview" was the mutation itself."""

    def test_a_mutation_result_in_place_of_a_preview_is_reported_not_confirmed(self) -> None:
        import click as _click

        from dailybot_cli.commands._destructive import preview_then_confirm

        archived: dict[str, Any] = {"uuid": "b-1", "name": "x", "archived_at": "2026-09-25"}
        with (
            patch.object(_click, "confirm") as confirm,
            pytest.raises(SystemExit) as caught,
        ):
            preview_then_confirm(lambda: archived, assume_yes=False, preview_only=True)
        assert caught.value.code == 1
        confirm.assert_not_called()

    @pytest.mark.parametrize(
        "preview",
        [
            {"operation": "task.archive", "dry_run": True, "consequence": "x"},
            {"operation": "board.archive", "consequence": "x", "affects": {"boards": 1}},
        ],
    )
    def test_a_real_preview_still_renders(self, preview: dict[str, Any]) -> None:
        from dailybot_cli.commands._destructive import preview_then_confirm

        out: str = _capture(
            preview_then_confirm, lambda: preview, assume_yes=False, preview_only=True
        )
        assert "Dry run" in out


class TestLocalFiles:
    def test_a_failed_download_write_removes_the_partial_file(self, tmp_path: Any) -> None:
        from dailybot_cli.commands.task import _write_download

        target: Any = tmp_path / "out.bin"

        class Full:
            def __enter__(self) -> "Full":
                return self

            def __exit__(self, *_: Any) -> None:
                return None

            def write(self, _data: bytes) -> int:
                raise OSError(28, "No space left on device")

        def fdopen(descriptor: int, _mode: str) -> Full:
            import os as _os

            _os.close(descriptor)
            return Full()

        with (
            patch("dailybot_cli.commands.task.os.fdopen", side_effect=fdopen),
            pytest.raises(SystemExit),
        ):
            _write_download(target, b"data", force=False, json_mode=True)
        assert not target.exists()

    def test_an_oversized_json_input_is_refused(self) -> None:
        import io

        from dailybot_cli.commands.public_api_helpers import (
            MAX_JSON_INPUT_CHARS,
            load_json_input,
        )

        with pytest.raises(ValueError, match="larger than"):
            load_json_input(io.StringIO("[" + " " * MAX_JSON_INPUT_CHARS + "]"))

    def test_a_json_input_within_the_cap_parses(self) -> None:
        import io

        from dailybot_cli.commands.public_api_helpers import load_json_input

        assert load_json_input(io.StringIO('[{"task": "ENG-1"}]')) == [{"task": "ENG-1"}]
