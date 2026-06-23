"""Textual application for `dailybot interactive`."""

import asyncio
from typing import Any, ClassVar

import httpx
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.events import Key
from textual.widgets import Input, RichLog, Static

from dailybot_cli import __version__
from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.tui.commands import (
    COMMAND_CHECKINS,
    COMMAND_CLEAR,
    COMMAND_HELP,
    COMMAND_REPORT,
    COMMAND_STATUS,
    EXIT_COMMANDS,
    HELP_TEXT,
    KNOWN_COMMANDS,
    parse_command,
)
from dailybot_cli.tui.conversation import ConversationSession

INPUT_HISTORY_LIMIT: int = 100

DAILYBOT_PIXEL_LOGO: str = """
    ▄█▄
    ▀█▀ ▄▄▄▄▄      ██  ███  █  █    █  █ █  ██   ██  ███
     ▄████████▄    █ █ █ █  █  █    █   █   █ █ █  █  █
    ████  ██  ██   █ █ ███  █  █    █   █   ██  █  █  █
    ████  ██  ██   █ █ █ █  █  █    █   █   █ █ █  █  █
    ▀███  ██  █▀   █▄▀ █ █  █  ███  █   █   ██   ██   █
      ▀██████▀
""".strip("\n")


class DailybotChatApp(App[None]):
    """Claude-style terminal chat for talking directly to Dailybot."""

    CSS = """
    Screen {
        background: #0d1117;
        color: #d6deeb;
    }

    #shell {
        height: 100%;
        padding: 1 3;
    }

    #hero {
        height: auto;
        margin-bottom: 0;
    }

    #brand {
        height: 7;
        text-style: bold;
        color: white;
        margin-bottom: 0;
    }

    #tagline {
        color: #d6deeb;
    }

    #tip {
        color: #a7b0c0;
        margin-top: 1;
    }

    #rule {
        color: #6d62cf;
        height: 1;
        margin: 1 0;
    }

    #transcript {
        height: 1fr;
        border: none;
        padding: 0 0;
        background: #0d1117;
        scrollbar-size: 0 0;
    }

    #prompt {
        height: 3;
        margin-top: 1;
        margin-bottom: 0;
        border: solid #5b5bd6;
        background: #0d1117;
        color: white;
    }

    #status {
        height: 1;
        color: #7f8798;
        margin-top: 0;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear", "Clear"),
    ]

    def __init__(self, client: DailyBotClient) -> None:
        super().__init__()
        self.client: DailyBotClient = client
        self.session: ConversationSession = ConversationSession()
        self.report_mode: bool = False
        self.user_label: str = "You"
        self.input_history: list[str] = []
        self.input_history_index: int | None = None
        self.input_history_draft: str = ""

    def compose(self) -> ComposeResult:
        with Container(id="shell"):
            with Vertical(id="hero"):
                yield Static(DAILYBOT_PIXEL_LOGO, id="brand")
                yield Static("Your daily AI companion in the terminal.", id="tagline")
                yield Static(
                    "Tip: Type /help for commands, /status for session details, /clear to reset.",
                    id="tip",
                )
            yield Static("─" * 120, id="rule")
            yield RichLog(id="transcript", markup=True, wrap=True, highlight=True)
            yield Input(placeholder="> Ask Dailybot anything...", id="prompt")
            yield Static(
                f"dailybot v{__version__} | /help",
                id="status",
            )

    def on_mount(self) -> None:
        self.title = "dailybot"
        self.query_one("#prompt", Input).focus()
        self._refresh_status()
        self._write_intro()
        self.run_worker(self._load_user_label(), exclusive=True)

    def on_key(self, event: Key) -> None:
        if self.focused is not self.query_one("#prompt", Input):
            return
        if event.key == "up":
            event.prevent_default()
            event.stop()
            self._show_previous_input()
            return
        if event.key == "down":
            event.prevent_default()
            event.stop()
            self._show_next_input()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = self.query_one("#prompt", Input)
        raw_value: str = event.value.strip()
        prompt.value = ""
        if not raw_value:
            return

        if self.report_mode:
            self.report_mode = False
            await self._submit_report(raw_value)
            return

        self._remember_input(raw_value)
        command: str | None = parse_command(raw_value)
        if command is not None:
            await self._handle_command(command)
            return

        await self._send_turn(raw_value)

    def action_clear(self) -> None:
        self.session.clear()
        log = self.query_one("#transcript", RichLog)
        log.clear()
        self._write_intro()
        self._refresh_status()
        self._write_system("Conversation cleared.")

    def _write_intro(self) -> None:
        log = self.query_one("#transcript", RichLog)
        intro = Panel(
            Text(
                "● Hi! I'm Dailybot.\n"
                "Ask me anything, brainstorm ideas, analyze, write, debug,\n"
                "or just have a thoughtful conversation.",
                style="white",
            ),
            border_style="#5b5bd6",
            width=66,
        )
        log.write(intro)

    async def _handle_command(self, command: str) -> None:
        if command in EXIT_COMMANDS:
            self.exit()
            return
        if command == COMMAND_HELP:
            self._write_help()
            return
        if command == COMMAND_CLEAR:
            self.action_clear()
            return
        if command == COMMAND_STATUS:
            await self._show_status()
            return
        if command == COMMAND_CHECKINS:
            await self._show_checkins()
            return
        if command == COMMAND_REPORT:
            self.report_mode = True
            self._write_system("Type the progress update to submit, or /clear to cancel.")
            return
        if command not in KNOWN_COMMANDS:
            self._write_error(f"Unknown command `/{command}`. Type `/help` for commands.")

    async def _send_turn(self, message: str) -> None:
        self._write_user(message)
        self._set_loading(True)
        try:
            response = await asyncio.to_thread(
                self.client.create_chat_completion,
                message=message,
                history=self.session.recent_history(),
                session_id=self.session.session_id,
            )
        except httpx.TimeoutException:
            self._write_error("Dailybot took longer than expected to answer. Please try again.")
            return
        except APIError as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)

        assistant_message: dict[str, Any] = response.get("message", {})
        content: str = str(assistant_message.get("content") or "").strip()
        if not content:
            content = "Dailybot returned an empty response."
        self.session.append_user(message)
        self.session.append_assistant(content)
        self._refresh_status()
        self._write_dailybot(content)

        actions: list[dict[str, Any]] = response.get("actions") or []
        if actions:
            action_names: str = ", ".join(
                str(action.get("name", "action")) for action in actions
            )
            self._write_system(f"Suggested action: {action_names}")

    async def _show_status(self) -> None:
        self._set_loading(True)
        try:
            data = await asyncio.to_thread(self.client.auth_status)
        except APIError as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        user_raw: Any = data.get("user", "")
        email: str = (
            user_raw.get("email", "")
            if isinstance(user_raw, dict)
            else str(user_raw or data.get("email", ""))
        )
        org_raw: Any = data.get("organization", "")
        org_name: str = org_raw.get("name", "") if isinstance(org_raw, dict) else str(org_raw)
        self._write_dailybot(f"**Session status**\n\n- User: {email or 'Unknown'}\n- Org: {org_name}")

    async def _show_checkins(self) -> None:
        self._set_loading(True)
        try:
            data = await asyncio.to_thread(self.client.get_status)
        except APIError as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        checkins: list[dict[str, Any]] = data.get("pending_checkins", [])
        if not checkins:
            self._write_dailybot("No pending check-ins for today.")
            return
        lines: list[str] = ["**Pending check-ins**"]
        for checkin in checkins:
            name = str(checkin.get("followup_name") or "Check-in")
            question_count = len(checkin.get("template_questions", []))
            lines.append(f"- {name} ({question_count} question{'s' if question_count != 1 else ''})")
        self._write_dailybot("\n".join(lines))

    async def _submit_report(self, message: str) -> None:
        if message.startswith("/"):
            command = parse_command(message)
            if command == COMMAND_CLEAR:
                self._write_system("Report cancelled.")
                return
        self._set_loading(True)
        try:
            result = await asyncio.to_thread(self.client.submit_update, message=message)
        except httpx.TimeoutException:
            self._write_error("Dailybot may still be processing the update. Check before retrying.")
            return
        except APIError as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        count = int(result.get("followups_count", 0))
        self._write_dailybot(f"Progress update submitted to {count} check-in(s).")

    def _write_user(self, content: str) -> None:
        log = self.query_one("#transcript", RichLog)
        log.write(Text(self.user_label, style="bold #7aa2f7"))
        log.write(Text(f"> {content}", style="white"))

    def _write_dailybot(self, content: str) -> None:
        log = self.query_one("#transcript", RichLog)
        log.write(Text("dailybot", style="bold #9d7cd8"))
        log.write(Markdown(content))

    def _write_help(self) -> None:
        log = self.query_one("#transcript", RichLog)
        log.write(Text("dailybot", style="bold #9d7cd8"))
        help_text = Text()
        for line in HELP_TEXT.strip().splitlines():
            help_text.append(f"{line.rstrip()}\n", style="white")
        log.write(help_text)

    def _write_system(self, content: str) -> None:
        self.query_one("#transcript", RichLog).write(Text(content, style="dim"))

    def _write_error(self, content: str) -> None:
        self.query_one("#transcript", RichLog).write(Text(content, style="bold red"))

    def _set_loading(self, loading: bool) -> None:
        prompt = self.query_one("#prompt", Input)
        prompt.disabled = loading
        prompt.placeholder = "Dailybot is thinking..." if loading else "> Ask Dailybot anything..."
        if not loading:
            prompt.focus()

    def _remember_input(self, value: str) -> None:
        if not self.input_history or self.input_history[-1] != value:
            self.input_history.append(value)
        if len(self.input_history) > INPUT_HISTORY_LIMIT:
            self.input_history = self.input_history[-INPUT_HISTORY_LIMIT:]
        self.input_history_index = None
        self.input_history_draft = ""

    def _show_previous_input(self) -> None:
        if not self.input_history:
            return
        prompt = self.query_one("#prompt", Input)
        if self.input_history_index is None:
            self.input_history_draft = prompt.value
            self.input_history_index = len(self.input_history) - 1
        elif self.input_history_index > 0:
            self.input_history_index -= 1
        self._replace_prompt_value(self.input_history[self.input_history_index])

    def _show_next_input(self) -> None:
        if self.input_history_index is None:
            return
        prompt_value: str
        if self.input_history_index < len(self.input_history) - 1:
            self.input_history_index += 1
            prompt_value = self.input_history[self.input_history_index]
        else:
            self.input_history_index = None
            prompt_value = self.input_history_draft
            self.input_history_draft = ""
        self._replace_prompt_value(prompt_value)

    def _replace_prompt_value(self, value: str) -> None:
        prompt = self.query_one("#prompt", Input)
        prompt.value = value
        prompt.cursor_position = len(value)

    def _refresh_status(self) -> None:
        self.query_one("#status", Static).update(
            f"Session {self.session.session_id[:8]} | "
            f"{len(self.session.history)} msgs | "
            f"v{__version__} | /help"
        )

    async def _load_user_label(self) -> None:
        try:
            data = await asyncio.to_thread(self.client.auth_status)
        except (APIError, httpx.HTTPError):
            return

        label = self._extract_user_label(data)
        if label:
            self.user_label = label

    @staticmethod
    def _extract_user_label(data: dict[str, Any]) -> str | None:
        user_raw: Any = data.get("user", {})
        user: dict[str, Any] = user_raw if isinstance(user_raw, dict) else {}
        for key in ("full_name", "name", "display_name"):
            value = str(user.get(key) or "").strip()
            if value:
                return value

        first_name = str(user.get("first_name") or "").strip()
        last_name = str(user.get("last_name") or "").strip()
        name = " ".join(part for part in (first_name, last_name) if part)
        if name:
            return name

        email = str(user.get("email") or data.get("email") or "").strip()
        if "@" in email:
            local_part = email.split("@", maxsplit=1)[0]
            words = [word for word in local_part.replace("_", ".").replace("-", ".").split(".") if word]
            if words:
                return " ".join(word.capitalize() for word in words)
        return None

    @staticmethod
    def _format_api_error(exc: APIError) -> str:
        if exc.status_code in (401, 403):
            return "Session expired or missing. Run: dailybot login"
        if exc.status_code == 429:
            return "Rate limit exceeded. Wait a moment and try again."
        return exc.detail


def run_chat_app(client: DailyBotClient) -> None:
    """Run the Textual chat app."""
    DailybotChatApp(client).run()
