"""Textual application for `dailybot interactive`."""

import asyncio
from datetime import date
from typing import Any, ClassVar

import httpx
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Container, Vertical
from textual.events import Key
from textual.widgets import Input, RichLog, Static

from dailybot_cli import __version__
from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.tui.commands import (
    COMMAND_CHECKINS,
    COMMAND_CLEAR,
    COMMAND_COMPLETIONS,
    COMMAND_DASHBOARD,
    COMMAND_FORM,
    COMMAND_FORMS,
    COMMAND_HELP,
    COMMAND_KUDOS,
    COMMAND_MOOD,
    COMMAND_REPORT,
    COMMAND_STATUS,
    COMMAND_TEAM,
    COMMAND_TEAMS,
    COMMAND_TIMEOFF,
    COMMAND_USERS,
    EXIT_COMMANDS,
    HELP_TEXT,
    KNOWN_COMMANDS,
    TERMINAL_COMMANDS,
    parse_command,
    parse_command_args,
)
from dailybot_cli.tui.conversation import ConversationSession
from dailybot_cli.tui.intents import (
    KudosIntent,
    TerminalActionIntent,
    TerminalCheckinIntent,
    is_checkins_intent,
    matching_teams,
    matching_users,
    parse_kudos_intent,
    parse_terminal_action_intent,
    parse_terminal_checkin_intent,
)

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

_CONFIRM_YES: frozenset[str] = frozenset({"1", "yes", "y"})
_CONFIRM_NO: frozenset[str] = frozenset({"2", "no", "n"})


def _parse_confirmation(raw_value: str, *, extra_yes: frozenset[str] = frozenset()) -> bool | None:
    """Parse a yes/no reply: True = confirm, False = cancel, None = unrecognized."""
    normalized: str = raw_value.strip().lower()
    if normalized in _CONFIRM_YES or normalized in extra_yes:
        return True
    if normalized in _CONFIRM_NO:
        return False
    return None


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

    BINDINGS: ClassVar[list[BindingType]] = [
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
        self.pending_flow: dict[str, Any] | None = None
        self.completion_state: dict[str, Any] | None = None
        self.mention_completion_items: list[str] | None = None

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
            return
        if event.key == "tab":
            event.prevent_default()
            event.stop()
            # Own worker group so Tab-cycling only cancels prior completions, not
            # the startup user-label worker (shift+tab is handled separately below).
            self.run_worker(
                self._complete_prompt(reverse=False),
                exclusive=True,
                group="completion",
            )
            return
        if event.key in {"shift+tab", "shift_tab", "backtab"}:
            event.prevent_default()
            event.stop()
            self.run_worker(self._complete_prompt(reverse=True), exclusive=True, group="completion")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = self.query_one("#prompt", Input)
        raw_value: str = event.value.strip()
        prompt.value = ""
        if not raw_value and self.pending_flow is None:
            return

        if self.pending_flow is not None:
            self._remember_input(raw_value)
            self._write_user(raw_value)
            await self._handle_pending_flow(raw_value)
            return

        if self.report_mode:
            self.report_mode = False
            await self._submit_report(raw_value)
            return

        self._remember_input(raw_value)
        checkin_intent: TerminalCheckinIntent | None = parse_terminal_checkin_intent(raw_value)
        if checkin_intent is not None:
            self._write_user(raw_value)
            await self._handle_terminal_checkin_intent(checkin_intent)
            return

        command: str | None = parse_command(raw_value)
        if command is not None:
            await self._handle_command(command, raw_value)
            return

        if is_checkins_intent(raw_value):
            self._write_user(raw_value)
            await self._start_checkins_flow()
            return

        kudos_intent: KudosIntent | None = parse_kudos_intent(raw_value)
        if kudos_intent is not None:
            self._write_user(raw_value)
            await self._start_kudos_flow(kudos_intent)
            return

        action_intent: TerminalActionIntent | None = parse_terminal_action_intent(raw_value)
        if action_intent is not None:
            self._write_user(raw_value)
            await self._handle_terminal_action_intent(action_intent)
            return

        await self._send_turn(raw_value)

    def action_clear(self) -> None:
        self.session.clear()
        self.pending_flow = None
        self.report_mode = False
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

    async def _handle_command(self, command: str, raw_value: str = "") -> None:
        args: list[str] = parse_command_args(raw_value)
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
            await self._start_checkins_flow()
            return
        if command == COMMAND_KUDOS:
            await self._start_kudos_menu()
            return
        if command in {COMMAND_FORMS, COMMAND_FORM}:
            await self._handle_form_command(args)
            return
        if command == COMMAND_USERS:
            await self._show_users()
            return
        if command == COMMAND_TEAMS:
            await self._show_teams()
            return
        if command == COMMAND_TEAM:
            await self._start_team_detail_flow(" ".join(args))
            return
        if command == COMMAND_DASHBOARD:
            self._show_dashboard()
            return
        if command == COMMAND_MOOD:
            await self._start_mood_flow()
            return
        if command == COMMAND_TIMEOFF:
            self._write_dailybot(
                "The native time-off terminal flow is not available yet. "
                "Use Dailybot chat or the web app for time off until that API is exposed to the CLI."
            )
            return
        if command == COMMAND_REPORT:
            self.report_mode = True
            self._write_system("Type the progress update to submit, or /clear to cancel.")
            return
        if command not in KNOWN_COMMANDS:
            self._write_error(f"Unknown command `/{command}`. Type `/help` for commands.")

    async def _handle_terminal_checkin_intent(self, intent: TerminalCheckinIntent) -> None:
        if intent.action == "complete":
            await self._start_checkins_flow()
            return
        if intent.action == "edit":
            await self._start_checkin_edit_flow()
            return
        if intent.action in {"reset", "delete"}:
            await self._start_checkin_reset_flow()
            return
        self._write_error("Unsupported check-in action. Type `/checkins` to complete one.")

    async def _handle_pending_flow(self, raw_value: str) -> None:
        if raw_value.lower() in {"cancel", "q", "quit", "exit"}:
            self.pending_flow = None
            self._write_system("Cancelled.")
            self._set_prompt_hint()
            return
        command: str | None = parse_command(raw_value)
        if command == COMMAND_CLEAR:
            self.action_clear()
            return

        assert self.pending_flow is not None
        flow_type: str = str(self.pending_flow.get("type"))
        handlers: dict[str, Any] = {
            "checkin_select": self._select_checkin,
            "checkin_answer": self._answer_checkin_question,
            "checkin_edit_select": self._select_checkin_to_edit,
            "checkin_edit_answer": self._answer_checkin_edit_question,
            "checkin_reset_select": self._select_checkin_to_reset,
            "checkin_reset_confirm": self._confirm_checkin_reset,
            "kudos_receiver_kind": self._select_kudos_receiver_kind,
            "kudos_user_select": self._select_kudos_user,
            "kudos_team_select": self._select_kudos_team,
            "kudos_message": self._send_kudos_message,
            "kudos_value": self._set_kudos_value,
            "kudos_confirm": self._confirm_kudos,
            "form_select": self._select_form_action,
            "form_action": self._select_form_action_choice,
            "form_submit_answer": self._answer_form_submit_question,
            "form_response_select": self._select_form_response,
            "form_update_answer": self._answer_form_update_question,
            "form_transition_select": self._select_form_transition,
            "form_transition_note": self._set_form_transition_note,
            "form_delete_confirm": self._confirm_form_delete,
            "team_detail_select": self._select_team_detail,
            "mood_select": self._select_mood,
            "terminal_action_confirm": self._confirm_terminal_action,
        }
        handler: Any = handlers.get(flow_type)
        if handler is not None:
            await handler(raw_value)
            return

        self.pending_flow = None
        self._write_error("That terminal menu expired. Try the command again.")
        self._set_prompt_hint()

    async def _send_turn(self, message: str) -> None:
        self._write_user(message)
        self._set_loading(True)
        try:
            response = await asyncio.to_thread(
                self.client.create_chat_completion,
                message=message,
                history=self.session.recent_history(),
                session_id=self.session.session_id,
                available_commands=list(TERMINAL_COMMANDS),
            )
        except httpx.TimeoutException:
            self._write_error("Dailybot took longer than expected to answer. Please try again.")
            return
        except (APIError, httpx.HTTPError) as exc:
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
            await self._handle_chat_actions(actions)

    async def _show_status(self) -> None:
        self._set_loading(True)
        try:
            data, status_data = await asyncio.gather(
                asyncio.to_thread(self.client.auth_status),
                asyncio.to_thread(self.client.get_status),
            )
        except (APIError, httpx.HTTPError) as exc:
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
        pending_checkins: list[dict[str, Any]] = status_data.get("pending_checkins", [])
        checkin_lines: list[str] = [
            f"- {self._checkin_label(checkin)}" for checkin in pending_checkins[:5]
        ]
        if len(pending_checkins) > 5:
            checkin_lines.append(f"- ...and {len(pending_checkins) - 5} more")
        checkins_text: str = "\n".join(checkin_lines) if checkin_lines else "- None pending"
        self._write_dailybot(
            "**Session status**\n\n"
            f"- User: {email or 'Unknown'}\n"
            f"- Org: {org_name}\n"
            f"- Pending check-ins: {len(pending_checkins)}\n\n"
            f"**Pending check-ins**\n{checkins_text}"
        )

    async def _start_checkins_flow(self) -> None:
        self._set_loading(True)
        try:
            data = await asyncio.to_thread(self.client.get_status)
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        checkins: list[dict[str, Any]] = data.get("pending_checkins", [])
        if not checkins:
            self._write_dailybot("No pending check-ins for today.")
            return
        self.pending_flow = {"type": "checkin_select", "items": checkins}
        self._write_dailybot(
            self._format_numbered_menu(
                "Select a check-in to complete:",
                checkins,
                self._checkin_label,
            )
        )
        self._set_prompt_hint("Type a number, or `cancel`.")

    async def _start_checkin_edit_flow(self) -> None:
        self._set_loading(True)
        try:
            candidates = await asyncio.to_thread(self._load_editable_checkin_candidates)
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)

        if not candidates:
            self._write_dailybot("No submitted check-ins found for today.")
            return
        self.pending_flow = {"type": "checkin_edit_select", "items": candidates}
        self._write_dailybot(
            self._format_numbered_menu(
                "Select a submitted check-in to edit:",
                candidates,
                self._checkin_edit_label,
            )
        )
        self._set_prompt_hint("Type a number, or `cancel`.")

    def _load_editable_checkin_candidates(self) -> list[dict[str, Any]]:
        today: str = date.today().isoformat()
        # Check-in responses default to all participants, so scope to the caller's
        # own response before picking one to edit. Unknown user (e.g. API-key auth)
        # falls back to the first response returned.
        try:
            self_uuid: str | None = self._get_current_user_uuid()
        except APIError:
            self_uuid = None
        candidates: list[dict[str, Any]] = []
        for checkin in self.client.list_checkins():
            followup_uuid: str = str(checkin.get("id") or checkin.get("followup_uuid") or "")
            if not followup_uuid:
                continue
            responses = self.client.list_checkin_responses(
                followup_uuid,
                date_start=today,
                date_end=today,
                user=self_uuid,
            )
            if responses:
                candidates.append({"checkin": checkin, "response": responses[0]})
        return candidates

    async def _select_checkin_to_edit(self, raw_value: str) -> None:
        selected: dict[str, Any] | None = self._select_numbered_item(raw_value)
        if selected is None:
            return

        self._set_loading(True)
        try:
            edit_context = await asyncio.to_thread(self._load_checkin_edit_context, selected)
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)

        questions: list[dict[str, Any]] = edit_context["questions"]
        if not questions:
            self.pending_flow = None
            self._set_prompt_hint()
            self._write_error("Selected check-in has no editable questions.")
            return
        self.pending_flow = {
            "type": "checkin_edit_answer",
            "checkin": edit_context["checkin"],
            "questions": questions,
            "existing_responses": edit_context["existing_responses"],
            "answers": [],
            "index": 0,
        }
        self._ask_current_checkin_edit_question()

    def _load_checkin_edit_context(self, selected: dict[str, Any]) -> dict[str, Any]:
        checkin: dict[str, Any] = selected["checkin"]
        followup_uuid: str = str(checkin.get("id") or checkin.get("followup_uuid") or "")
        checkin_detail = self.client.get_checkin(followup_uuid)
        template_uuid: str = str(checkin_detail.get("template") or "")
        if not template_uuid:
            return {"checkin": checkin_detail, "questions": [], "existing_responses": []}
        template = self.client.get_template(template_uuid, followup_uuid=followup_uuid)
        questions: list[dict[str, Any]] = (template.get("questions") or {}).get("fields") or []
        existing_responses: list[dict[str, Any]] = (
            selected.get("response", {}).get("responses") or []
        )
        return {
            "checkin": checkin_detail,
            "questions": questions,
            "existing_responses": existing_responses,
        }

    async def _select_checkin(self, raw_value: str) -> None:
        selected: dict[str, Any] | None = self._select_numbered_item(raw_value)
        if selected is None:
            return
        self._set_loading(True)
        try:
            questions = await asyncio.to_thread(self._load_checkin_questions, selected)
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        if not questions:
            self.pending_flow = None
            self._set_prompt_hint()
            self._write_error("Selected check-in has no questions.")
            return
        self.pending_flow = {
            "type": "checkin_answer",
            "checkin": selected,
            "questions": questions,
            "answers": [],
            "index": 0,
        }
        self._ask_current_checkin_question()

    def _load_checkin_questions(self, checkin: dict[str, Any]) -> list[dict[str, Any]]:
        followup_uuid: str = str(checkin.get("followup_uuid") or checkin.get("id") or "")
        if not followup_uuid:
            return checkin.get("template_questions") or []
        checkin_detail = self.client.get_checkin(followup_uuid)
        template_uuid: str = str(checkin_detail.get("template") or "")
        if not template_uuid:
            return checkin.get("template_questions") or []
        template = self.client.get_template(template_uuid, followup_uuid=followup_uuid)
        rendered_questions: list[dict[str, Any]] = (template.get("questions") or {}).get(
            "fields"
        ) or []
        return rendered_questions or checkin.get("template_questions") or []

    async def _answer_checkin_question(self, raw_value: str) -> None:
        assert self.pending_flow is not None
        questions: list[dict[str, Any]] = self.pending_flow["questions"]
        index: int = int(self.pending_flow["index"])
        question: dict[str, Any] = questions[index]
        answer: Any = self._parse_question_answer(raw_value, question)
        if answer is None:
            return
        self.pending_flow["answers"].append(answer)
        self.pending_flow["index"] = index + 1
        if self.pending_flow["index"] < len(questions):
            self._ask_current_checkin_question()
            return

        checkin: dict[str, Any] = self.pending_flow["checkin"]
        responses: list[dict[str, Any]] = self._build_checkin_responses(
            questions,
            self.pending_flow["answers"],
        )
        self.pending_flow = None
        self._set_prompt_hint()
        self._set_loading(True)
        try:
            await asyncio.to_thread(
                self.client.complete_checkin,
                str(checkin.get("followup_uuid") or checkin.get("id") or ""),
                responses,
                len(responses) - 1,
            )
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        self._write_dailybot(f"Done — submitted **{self._checkin_name(checkin)}**.")

    async def _answer_checkin_edit_question(self, raw_value: str) -> None:
        assert self.pending_flow is not None
        questions: list[dict[str, Any]] = self.pending_flow["questions"]
        index: int = int(self.pending_flow["index"])
        question: dict[str, Any] = questions[index]
        existing_value: Any = self._existing_response_value(question, index)
        answer: Any
        if raw_value == "":
            answer = existing_value
        else:
            answer = self._parse_question_answer(raw_value, question)
            if answer is None:
                return

        self.pending_flow["answers"].append(answer)
        self.pending_flow["index"] = index + 1
        if self.pending_flow["index"] < len(questions):
            self._ask_current_checkin_edit_question()
            return

        checkin: dict[str, Any] = self.pending_flow["checkin"]
        responses: list[dict[str, Any]] = self._build_checkin_responses(
            questions,
            self.pending_flow["answers"],
        )
        self.pending_flow = None
        self._set_prompt_hint()
        self._set_loading(True)
        try:
            await asyncio.to_thread(
                self.client.update_checkin_response,
                str(checkin.get("id") or checkin.get("followup_uuid") or ""),
                responses,
                len(responses) - 1,
            )
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        self._write_dailybot(f"Done — updated **{self._checkin_name(checkin)}**.")

    async def _start_kudos_menu(self) -> None:
        self._set_loading(True)
        try:
            users, teams, current_uuid = await asyncio.gather(
                asyncio.to_thread(self.client.list_users),
                asyncio.to_thread(self.client.list_teams),
                asyncio.to_thread(self._get_current_user_uuid),
            )
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)

        self.pending_flow = {
            "type": "kudos_receiver_kind",
            "users": users,
            "teams": teams,
            "current_uuid": current_uuid,
        }
        self._write_dailybot(
            "Who should receive kudos?\n1. One or more users\n2. One or more teams"
        )
        self._set_prompt_hint("Type 1 or 2, or `cancel`.")

    async def _start_kudos_flow(self, intent: KudosIntent) -> None:
        self._set_loading(True)
        try:
            users, teams, current_uuid = await asyncio.gather(
                asyncio.to_thread(self.client.list_users),
                asyncio.to_thread(self.client.list_teams),
                asyncio.to_thread(self._get_current_user_uuid),
            )
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)

        user_candidates: list[dict[str, Any]] = [
            user
            for user in matching_users(users, intent.receiver_query)
            if str(user.get("uuid") or "") != str(current_uuid or "")
        ]
        team_candidates: list[dict[str, Any]] = matching_teams(teams, intent.receiver_query)
        if intent.receiver_kind == "team" or (not user_candidates and team_candidates):
            if not team_candidates:
                self._write_error(f"I couldn't find a team matching `{intent.receiver_query}`.")
                return
            self._prompt_kudos_team_selection(team_candidates, intent.message)
            return

        if not user_candidates:
            self._write_error(f"I couldn't find a teammate matching `{intent.receiver_query}`.")
            return
        self._prompt_kudos_user_selection(user_candidates, intent.message, current_uuid)

    async def _select_kudos_receiver_kind(self, raw_value: str) -> None:
        assert self.pending_flow is not None
        value: str = raw_value.strip().lower()
        if value not in {"1", "2", "user", "users", "team", "teams"}:
            self._write_error("Type 1 for users or 2 for teams.")
            return
        if value in {"1", "user", "users"}:
            users: list[dict[str, Any]] = [
                user
                for user in self.pending_flow.get("users", [])
                if str(user.get("uuid") or "") != str(self.pending_flow.get("current_uuid") or "")
            ]
            self._prompt_kudos_user_selection(
                users,
                "",
                self.pending_flow.get("current_uuid"),
            )
            return
        self._prompt_kudos_team_selection(self.pending_flow.get("teams", []), "")

    def _prompt_kudos_user_selection(
        self,
        candidates: list[dict[str, Any]],
        message: str,
        current_uuid: str | None,
    ) -> None:
        if not candidates:
            self.pending_flow = None
            self._set_prompt_hint()
            self._write_error("No teammates are available for kudos.")
            return
        self.pending_flow = {
            "type": "kudos_user_select",
            "items": candidates,
            "message": message,
            "current_uuid": current_uuid,
        }
        self._write_dailybot(
            self._format_numbered_menu(
                "Who should receive kudos? You can type multiple numbers like `1,3`.",
                candidates,
                self._user_label,
            )
        )
        self._set_prompt_hint("Type one or more numbers, or `cancel`.")

    def _prompt_kudos_team_selection(
        self,
        candidates: list[dict[str, Any]],
        message: str,
    ) -> None:
        if not candidates:
            self.pending_flow = None
            self._set_prompt_hint()
            self._write_error("No teams are visible to you.")
            return
        self.pending_flow = {
            "type": "kudos_team_select",
            "items": candidates,
            "message": message,
        }
        self._write_dailybot(
            self._format_numbered_menu(
                "Which team should receive kudos? You can type multiple numbers like `1,3`.",
                candidates,
                self._team_label,
            )
        )
        self._set_prompt_hint("Type one or more numbers, or `cancel`.")

    async def _select_kudos_user(self, raw_value: str) -> None:
        selected: list[dict[str, Any]] | None = self._select_numbered_items(raw_value)
        if selected is None:
            return
        assert self.pending_flow is not None
        message: str = str(self.pending_flow.get("message") or "").strip()
        current_uuid: str | None = self.pending_flow.get("current_uuid")
        selected = [
            user for user in selected if str(user.get("uuid") or "") != str(current_uuid or "")
        ]
        if not selected:
            self._write_error("You cannot give kudos to yourself.")
            return
        if not message:
            self.pending_flow = {
                "type": "kudos_message",
                "users": selected,
                "teams": [],
                "current_uuid": current_uuid,
            }
            self._write_dailybot(
                f"What should the kudos message say for **{self._join_labels(selected, self._user_label)}**?"
            )
            self._set_prompt_hint("Type the kudos message, or `cancel`.")
            return
        self._ask_kudos_value(selected, [], message, current_uuid=current_uuid)

    async def _select_kudos_team(self, raw_value: str) -> None:
        selected: list[dict[str, Any]] | None = self._select_numbered_items(raw_value)
        if selected is None:
            return
        assert self.pending_flow is not None
        message: str = str(self.pending_flow.get("message") or "").strip()
        if not message:
            self.pending_flow = {
                "type": "kudos_message",
                "users": [],
                "teams": selected,
            }
            self._write_dailybot(
                f"What should the kudos message say for **{self._join_labels(selected, self._team_label)}**?"
            )
            self._set_prompt_hint("Type the kudos message, or `cancel`.")
            return
        self._ask_kudos_value([], selected, message, current_uuid=None)

    async def _send_kudos_message(self, raw_value: str) -> None:
        message: str = raw_value.strip()
        if not message:
            self._write_error("Empty kudos message. Type a message or `cancel`.")
            return
        assert self.pending_flow is not None
        self._ask_kudos_value(
            self.pending_flow.get("users") or [],
            self.pending_flow.get("teams") or [],
            message,
            current_uuid=self.pending_flow.get("current_uuid"),
        )

    def _ask_kudos_value(
        self,
        users: list[dict[str, Any]],
        teams: list[dict[str, Any]],
        message: str,
        *,
        current_uuid: str | None = None,
    ) -> None:
        self.pending_flow = {
            "type": "kudos_value",
            "users": users,
            "teams": teams,
            "message": message,
            "current_uuid": current_uuid,
        }
        self._write_dailybot(
            "Optional: type a company value for this kudos, or press Enter to skip."
        )
        self._set_prompt_hint("Type a value, press Enter to skip, or `cancel`.")

    async def _set_kudos_value(self, raw_value: str) -> None:
        assert self.pending_flow is not None
        self.pending_flow["company_value"] = raw_value.strip() or None
        self.pending_flow["type"] = "kudos_confirm"
        self._write_dailybot(self._kudos_confirmation_text(self.pending_flow))
        self._set_prompt_hint("Type 1 to send, 2 to cancel.")

    async def _confirm_kudos(self, raw_value: str) -> None:
        assert self.pending_flow is not None
        decision: bool | None = _parse_confirmation(raw_value, extra_yes=frozenset({"send"}))
        if decision is None:
            self._write_error("Type 1 to send or 2 to cancel.")
            return
        if not decision:
            self.pending_flow = None
            self._set_prompt_hint()
            self._write_system("Kudos cancelled.")
            return
        users: list[dict[str, Any]] = self.pending_flow.get("users") or []
        teams: list[dict[str, Any]] = self.pending_flow.get("teams") or []
        message: str = str(self.pending_flow.get("message") or "")
        company_value: str | None = self.pending_flow.get("company_value")
        user_uuids: list[str] = [str(user.get("uuid") or "") for user in users if user.get("uuid")]
        team_uuids: list[str] = [
            str(team.get("uuid") or team.get("id") or "")
            for team in teams
            if team.get("uuid") or team.get("id")
        ]
        self.pending_flow = None
        self._set_prompt_hint()
        self._set_loading(True)
        try:
            await asyncio.to_thread(
                self.client.give_kudos,
                content=message,
                user_uuid_receivers=user_uuids or None,
                team_uuid_receivers=team_uuids or None,
                company_value=company_value,
            )
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        receiver_labels: list[str] = [
            *(self._user_label(user) for user in users),
            *(self._team_label(team) for team in teams),
        ]
        self._write_dailybot(
            f"Done — kudos sent to **{', '.join(receiver_labels)}** for {message}."
        )

    async def _handle_form_command(self, args: list[str]) -> None:
        action: str | None = args[0].lower() if args else None
        aliases: dict[str, str] = {
            "list": "list",
            "submit": "submit",
            "responses": "responses",
            "response": "responses",
            "update": "update",
            "edit": "update",
            "transition": "transition",
            "delete": "delete",
            "remove": "delete",
        }
        if action is not None and action not in aliases:
            self._write_error("Unknown form action. Type `/help` for form commands.")
            return
        await self._start_forms_flow(aliases.get(action) if action else None)

    async def _start_forms_flow(self, action: str | None = None) -> None:
        self._set_loading(True)
        try:
            forms = await asyncio.to_thread(self.client.list_forms, include_questions=True)
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)

        if not forms:
            self._write_dailybot("No forms are visible to you.")
            return
        if action == "list":
            self._write_dailybot(
                self._format_numbered_menu("Visible forms:", forms, self._form_label)
            )
            return
        self.pending_flow = {"type": "form_select", "items": forms, "action": action}
        heading: str = "Select a form:"
        if action:
            heading = f"Select a form to {action}:"
        self._write_dailybot(self._format_numbered_menu(heading, forms, self._form_label))
        self._set_prompt_hint("Type a number, or `cancel`.")

    async def _select_form_action(self, raw_value: str) -> None:
        selected: dict[str, Any] | None = self._select_numbered_item(raw_value)
        if selected is None:
            return
        assert self.pending_flow is not None
        action: str | None = self.pending_flow.get("action")
        if action:
            await self._prepare_form_action(selected, action)
            return
        self.pending_flow = {
            "type": "form_action",
            "form": selected,
            "items": [
                {"action": "submit", "label": "Submit a response"},
                {"action": "responses", "label": "Browse responses"},
                {"action": "update", "label": "Update a response"},
                {"action": "transition", "label": "Transition a workflow response"},
                {"action": "delete", "label": "Delete a response"},
            ],
        }
        self._write_dailybot(
            self._format_numbered_menu(
                f"What do you want to do with **{self._form_label(selected)}**?",
                self.pending_flow["items"],
                lambda item: str(item["label"]),
            )
        )
        self._set_prompt_hint("Type a number, or `cancel`.")

    async def _select_form_action_choice(self, raw_value: str) -> None:
        selected: dict[str, Any] | None = self._select_numbered_item(raw_value)
        if selected is None:
            return
        assert self.pending_flow is not None
        await self._prepare_form_action(self.pending_flow["form"], str(selected["action"]))

    async def _prepare_form_action(self, form: dict[str, Any], action: str) -> None:
        if action == "submit":
            await self._start_form_submit_flow(form)
            return
        if action == "responses":
            await self._start_form_response_picker(form, purpose="view")
            return
        if action == "update":
            await self._start_form_response_picker(form, purpose="update")
            return
        if action == "transition":
            await self._start_form_response_picker(form, purpose="transition")
            return
        if action == "delete":
            await self._start_form_response_picker(form, purpose="delete")
            return
        self._write_error("Unsupported form action.")

    async def _start_form_submit_flow(self, form: dict[str, Any]) -> None:
        form_data: dict[str, Any] | None = await self._load_form_detail(form)
        if form_data is None:
            return
        questions: list[dict[str, Any]] = self._form_questions(form_data)
        if not questions:
            self._write_error("Selected form has no answerable questions.")
            return
        self.pending_flow = {
            "type": "form_submit_answer",
            "form": form_data,
            "questions": questions,
            "answers": [],
            "index": 0,
        }
        self._ask_current_form_question()

    async def _answer_form_submit_question(self, raw_value: str) -> None:
        assert self.pending_flow is not None
        questions: list[dict[str, Any]] = self.pending_flow["questions"]
        index: int = int(self.pending_flow["index"])
        question: dict[str, Any] = questions[index]
        answer: Any = self._parse_question_answer(raw_value, question)
        if answer is None:
            return
        self.pending_flow["answers"].append(answer)
        self.pending_flow["index"] = index + 1
        if self.pending_flow["index"] < len(questions):
            self._ask_current_form_question()
            return

        form: dict[str, Any] = self.pending_flow["form"]
        content: dict[str, Any] = self._build_form_content(questions, self.pending_flow["answers"])
        self.pending_flow = None
        self._set_prompt_hint()
        self._set_loading(True)
        try:
            await asyncio.to_thread(
                self.client.submit_form_response,
                str(form.get("id") or form.get("uuid") or ""),
                content,
            )
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        self._write_dailybot(f"Done — submitted **{self._form_label(form)}**.")

    async def _start_form_response_picker(self, form: dict[str, Any], *, purpose: str) -> None:
        form_uuid: str = str(form.get("id") or form.get("uuid") or "")
        self._set_loading(True)
        try:
            form_data, responses = await asyncio.gather(
                asyncio.to_thread(self.client.get_form, form_uuid),
                asyncio.to_thread(self.client.list_form_responses, form_uuid),
            )
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        if not responses:
            self._write_dailybot(f"No responses found for **{self._form_label(form_data)}**.")
            return
        self.pending_flow = {
            "type": "form_response_select",
            "form": form_data,
            "items": responses,
            "purpose": purpose,
        }
        self._write_dailybot(
            self._format_numbered_menu(
                f"Select a response to {purpose}:",
                responses,
                self._form_response_label,
            )
        )
        self._set_prompt_hint("Type a number, or `cancel`.")

    async def _select_form_response(self, raw_value: str) -> None:
        selected: dict[str, Any] | None = self._select_numbered_item(raw_value)
        if selected is None:
            return
        assert self.pending_flow is not None
        form: dict[str, Any] = self.pending_flow["form"]
        purpose: str = str(self.pending_flow.get("purpose") or "view")
        response_uuid: str = str(selected.get("id") or selected.get("uuid") or "")
        form_uuid: str = str(form.get("id") or form.get("uuid") or "")
        self._set_loading(True)
        try:
            response = await asyncio.to_thread(
                self.client.get_form_response,
                form_uuid,
                response_uuid,
            )
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)

        if purpose == "view":
            self.pending_flow = None
            self._set_prompt_hint()
            self._write_dailybot(self._form_response_detail_text(response, form))
            return
        if purpose == "update":
            await self._start_form_update_flow(form, response)
            return
        if purpose == "transition":
            self._start_form_transition_flow(form, response)
            return
        if purpose == "delete":
            self._start_form_delete_flow(form, response)
            return

    async def _start_form_update_flow(
        self,
        form: dict[str, Any],
        response: dict[str, Any],
    ) -> None:
        questions: list[dict[str, Any]] = self._form_questions(form)
        if not questions:
            self.pending_flow = None
            self._set_prompt_hint()
            self._write_error("Selected form has no editable questions.")
            return
        self.pending_flow = {
            "type": "form_update_answer",
            "form": form,
            "response": response,
            "questions": questions,
            "answers": [],
            "index": 0,
        }
        self._ask_current_form_update_question()

    async def _answer_form_update_question(self, raw_value: str) -> None:
        assert self.pending_flow is not None
        questions: list[dict[str, Any]] = self.pending_flow["questions"]
        index: int = int(self.pending_flow["index"])
        question: dict[str, Any] = questions[index]
        existing_value: Any = self._existing_form_response_value(question)
        answer: Any = (
            existing_value if raw_value == "" else self._parse_question_answer(raw_value, question)
        )
        if answer is None:
            return
        self.pending_flow["answers"].append(answer)
        self.pending_flow["index"] = index + 1
        if self.pending_flow["index"] < len(questions):
            self._ask_current_form_update_question()
            return

        form: dict[str, Any] = self.pending_flow["form"]
        response: dict[str, Any] = self.pending_flow["response"]
        content: dict[str, Any] = self._build_form_content(questions, self.pending_flow["answers"])
        self.pending_flow = None
        self._set_prompt_hint()
        self._set_loading(True)
        try:
            await asyncio.to_thread(
                self.client.update_form_response,
                str(form.get("id") or form.get("uuid") or ""),
                str(response.get("id") or response.get("uuid") or ""),
                content,
            )
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        self._write_dailybot(f"Done — updated response **{self._form_response_id(response)}**.")

    def _start_form_transition_flow(self, form: dict[str, Any], response: dict[str, Any]) -> None:
        transitions: list[dict[str, Any]] = list(response.get("allowed_transitions") or [])
        if not transitions:
            self.pending_flow = None
            self._set_prompt_hint()
            self._write_dailybot("This response has no allowed workflow transitions.")
            return
        self.pending_flow = {
            "type": "form_transition_select",
            "form": form,
            "response": response,
            "items": transitions,
        }
        self._write_dailybot(
            self._format_numbered_menu(
                f"Select the next state for response **{self._form_response_id(response)}**:",
                transitions,
                self._transition_label,
            )
        )
        self._set_prompt_hint("Type a number, or `cancel`.")

    async def _select_form_transition(self, raw_value: str) -> None:
        selected: dict[str, Any] | None = self._select_numbered_item(raw_value)
        if selected is None:
            return
        assert self.pending_flow is not None
        self.pending_flow["transition"] = selected
        self.pending_flow["type"] = "form_transition_note"
        self._write_dailybot("Optional: type a transition note, or press Enter to skip.")
        self._set_prompt_hint("Type a note, press Enter to skip, or `cancel`.")

    async def _set_form_transition_note(self, raw_value: str) -> None:
        assert self.pending_flow is not None
        form: dict[str, Any] = self.pending_flow["form"]
        response: dict[str, Any] = self.pending_flow["response"]
        transition: dict[str, Any] = self.pending_flow["transition"]
        note: str | None = raw_value.strip() or None
        to_state: str = str(transition.get("to_state") or transition.get("key") or "")
        self.pending_flow = None
        self._set_prompt_hint()
        self._set_loading(True)
        try:
            await asyncio.to_thread(
                self.client.transition_form_response,
                str(form.get("id") or form.get("uuid") or ""),
                str(response.get("id") or response.get("uuid") or ""),
                to_state,
                note,
            )
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        self._write_dailybot(
            f"Done — moved response **{self._form_response_id(response)}** to **{self._transition_label(transition)}**."
        )

    def _start_form_delete_flow(self, form: dict[str, Any], response: dict[str, Any]) -> None:
        self.pending_flow = {
            "type": "form_delete_confirm",
            "form": form,
            "response": response,
        }
        self._write_dailybot(
            f"Delete response **{self._form_response_id(response)}** from **{self._form_label(form)}**?\n"
            "1. Delete\n2. Cancel"
        )
        self._set_prompt_hint("Type 1 to delete, 2 to cancel.")

    async def _confirm_form_delete(self, raw_value: str) -> None:
        assert self.pending_flow is not None
        decision: bool | None = _parse_confirmation(raw_value, extra_yes=frozenset({"delete"}))
        if decision is None:
            self._write_error("Type 1 to delete or 2 to cancel.")
            return
        if not decision:
            self.pending_flow = None
            self._set_prompt_hint()
            self._write_system("Delete cancelled.")
            return
        form: dict[str, Any] = self.pending_flow["form"]
        response: dict[str, Any] = self.pending_flow["response"]
        form_uuid: str = str(form.get("id") or form.get("uuid") or "")
        response_uuid: str = str(response.get("id") or response.get("uuid") or "")
        self.pending_flow = None
        self._set_prompt_hint()
        self._set_loading(True)
        try:
            await asyncio.to_thread(self.client.delete_form_response, form_uuid, response_uuid)
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        self._write_dailybot(f"Done — deleted response **{response_uuid}**.")

    async def _load_form_detail(self, form: dict[str, Any]) -> dict[str, Any] | None:
        form_uuid: str = str(form.get("id") or form.get("uuid") or "")
        if not form_uuid:
            self._write_error("Selected form has no UUID.")
            return None
        if self._form_questions(form):
            return form
        self._set_loading(True)
        try:
            return await asyncio.to_thread(self.client.get_form, form_uuid)
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return None
        finally:
            self._set_loading(False)

    def _ask_current_form_question(self) -> None:
        assert self.pending_flow is not None
        questions: list[dict[str, Any]] = self.pending_flow["questions"]
        index: int = int(self.pending_flow["index"])
        question: dict[str, Any] = questions[index]
        lines: list[str] = [
            f"Question {index + 1}/{len(questions)}: {self._question_label(question, index)}"
        ]
        choices: list[str] = self._question_choices(question)
        if self._question_type(question) == "boolean":
            lines.extend(["1. Yes", "2. No"])
            self._set_prompt_hint("Type 1 for yes, 2 for no, or `cancel`.")
        elif choices:
            for choice_index, choice in enumerate(choices, start=1):
                lines.append(f"{choice_index}. {choice}")
            self._set_prompt_hint("Type a number, or `cancel`.")
        else:
            self._set_prompt_hint("Type your answer, or `cancel`.")
        self._write_dailybot("\n".join(lines))

    def _ask_current_form_update_question(self) -> None:
        assert self.pending_flow is not None
        questions: list[dict[str, Any]] = self.pending_flow["questions"]
        index: int = int(self.pending_flow["index"])
        question: dict[str, Any] = questions[index]
        existing_value: Any = self._existing_form_response_value(question)
        lines: list[str] = [
            f"Question {index + 1}/{len(questions)}: {self._question_label(question, index)}",
            f"Current answer: {self._format_answer(existing_value)}",
        ]
        choices: list[str] = self._question_choices(question)
        if self._question_type(question) == "boolean":
            lines.extend(["1. Yes", "2. No"])
            self._set_prompt_hint("Type 1/2, Enter to keep, or `cancel`.")
        elif choices:
            for choice_index, choice in enumerate(choices, start=1):
                lines.append(f"{choice_index}. {choice}")
            self._set_prompt_hint("Type a number, Enter to keep, or `cancel`.")
        else:
            self._set_prompt_hint("Type a replacement, Enter to keep, or `cancel`.")
        self._write_dailybot("\n".join(lines))

    def _existing_form_response_value(self, question: dict[str, Any]) -> Any:
        assert self.pending_flow is not None
        response: dict[str, Any] = self.pending_flow.get("response") or {}
        raw_content: Any = response.get("content")
        content: dict[str, Any] = raw_content if isinstance(raw_content, dict) else {}
        question_uuid: str = str(question.get("uuid") or question.get("id") or "")
        return content.get(question_uuid, "")

    @staticmethod
    def _form_questions(form: dict[str, Any]) -> list[dict[str, Any]]:
        questions: Any = form.get("questions") or []
        if isinstance(questions, dict):
            fields: Any = questions.get("fields") or []
            return list(fields) if isinstance(fields, list) else []
        return list(questions) if isinstance(questions, list) else []

    @staticmethod
    def _build_form_content(
        questions: list[dict[str, Any]],
        answers: list[Any],
    ) -> dict[str, Any]:
        content: dict[str, Any] = {}
        for question, answer in zip(questions, answers, strict=True):
            question_uuid: str = str(question.get("uuid") or question.get("id") or "")
            if question_uuid:
                content[question_uuid] = answer
        return content

    @classmethod
    def _form_label(cls, form: dict[str, Any]) -> str:
        questions_count: int = len(cls._form_questions(form))
        suffix: str = f" ({questions_count} question{'s' if questions_count != 1 else ''})"
        return (
            str(
                form.get("name")
                or form.get("title")
                or form.get("uuid")
                or form.get("id")
                or "Form"
            )
            + suffix
        )

    @classmethod
    def _form_response_label(cls, response: dict[str, Any]) -> str:
        response_id: str = cls._form_response_id(response)
        state: str = str(response.get("current_state") or "no state")
        created_at: str = str(response.get("created_at") or response.get("updated_at") or "")
        suffix: str = f" — {created_at[:10]}" if created_at else ""
        return f"{response_id} ({state}){suffix}"

    @staticmethod
    def _form_response_id(response: dict[str, Any]) -> str:
        return str(response.get("id") or response.get("uuid") or "response")

    @staticmethod
    def _transition_label(transition: dict[str, Any]) -> str:
        return str(
            transition.get("label")
            or transition.get("to_state")
            or transition.get("key")
            or "Next state"
        )

    def _form_response_detail_text(
        self,
        response: dict[str, Any],
        form: dict[str, Any],
    ) -> str:
        lines: list[str] = [
            f"**Response {self._form_response_id(response)}**",
            f"- Form: {self._form_label(form)}",
            f"- Current state: {response.get('current_state') or 'None'}",
        ]
        content: Any = response.get("content")
        if isinstance(content, dict) and content:
            lines.append("\n**Answers**")
            for question_uuid, answer in content.items():
                lines.append(f"- {question_uuid}: {self._format_answer(answer)}")
        transitions: list[dict[str, Any]] = list(response.get("allowed_transitions") or [])
        if transitions:
            lines.append("\n**Allowed transitions**")
            for transition in transitions:
                lines.append(f"- {self._transition_label(transition)}")
        return "\n".join(lines)

    async def _show_users(self) -> None:
        self._set_loading(True)
        try:
            users = await asyncio.to_thread(self.client.list_users)
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        if not users:
            self._write_dailybot("No users are visible to you.")
            return
        self._write_dailybot(
            self._format_numbered_menu(
                f"Organization members ({len(users)}):",
                users[:25],
                self._user_label,
            )
        )

    async def _show_teams(self) -> None:
        self._set_loading(True)
        try:
            teams = await asyncio.to_thread(self.client.list_teams)
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        if not teams:
            self._write_dailybot("No teams are visible to you.")
            return
        self._write_dailybot(
            self._format_numbered_menu(f"Teams ({len(teams)}):", teams[:25], self._team_label)
        )

    async def _start_team_detail_flow(self, query: str = "") -> None:
        self._set_loading(True)
        try:
            teams = await asyncio.to_thread(self.client.list_teams)
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        candidates: list[dict[str, Any]] = matching_teams(teams, query) if query else teams
        if not candidates:
            self._write_error(f"No team matching `{query}` is visible to you.")
            return
        self.pending_flow = {"type": "team_detail_select", "items": candidates}
        self._write_dailybot(
            self._format_numbered_menu("Select a team to inspect:", candidates, self._team_label)
        )
        self._set_prompt_hint("Type a number, or `cancel`.")

    async def _select_team_detail(self, raw_value: str) -> None:
        selected: dict[str, Any] | None = self._select_numbered_item(raw_value)
        if selected is None:
            return
        team_uuid: str = str(selected.get("uuid") or selected.get("id") or "")
        self.pending_flow = None
        self._set_prompt_hint()
        self._set_loading(True)
        try:
            team, members = await asyncio.gather(
                asyncio.to_thread(self.client.get_team, team_uuid),
                asyncio.to_thread(self.client.list_team_members, team_uuid),
            )
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        member_lines: list[str] = [f"- {self._user_label(member)}" for member in members[:25]]
        members_text: str = "\n".join(member_lines) if member_lines else "- No members returned"
        self._write_dailybot(
            f"**{self._team_label(team)}**\n\n"
            f"- UUID: {team_uuid}\n"
            f"- Members: {len(members)}\n\n"
            f"**Members**\n{members_text}"
        )

    @staticmethod
    def _web_base_url(api_url: str) -> str:
        """Map the API host to the web app host (api.dailybot.com -> app.dailybot.com).

        Custom/local hosts (no "://api.") are left unchanged. A previous substring
        replace of "/api" corrupted the default host into "https:/.dailybot.com".
        """
        return api_url.replace("://api.", "://app.").rstrip("/")

    def _show_dashboard(self) -> None:
        dashboard_url: str = f"{self._web_base_url(self.client.api_url)}/home"
        self._write_dailybot(f"Open your Dailybot dashboard: {dashboard_url}")

    async def _start_mood_flow(self) -> None:
        self.pending_flow = {"type": "mood_select"}
        self._write_dailybot(
            "How is your mood today?\n1. Very low\n2. Low\n3. Okay\n4. Good\n5. Great"
        )
        self._set_prompt_hint("Type a number from 1 to 5, or `cancel`.")

    async def _select_mood(self, raw_value: str) -> None:
        try:
            score: int = int(raw_value.strip())
        except ValueError:
            self._write_error("Type a number from 1 to 5.")
            return
        if score < 1 or score > 5:
            self._write_error("Type a number from 1 to 5.")
            return
        self.pending_flow = None
        self._set_prompt_hint()
        self._set_loading(True)
        try:
            await asyncio.to_thread(self.client.track_mood, score)
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        self._write_dailybot("Done — your mood was tracked for today.")

    async def _start_checkin_reset_flow(self) -> None:
        self._set_loading(True)
        try:
            candidates = await asyncio.to_thread(self._load_editable_checkin_candidates)
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        if not candidates:
            self._write_dailybot("No submitted check-ins found for today.")
            return
        self.pending_flow = {"type": "checkin_reset_select", "items": candidates}
        self._write_dailybot(
            self._format_numbered_menu(
                "Select a submitted check-in to delete:",
                candidates,
                self._checkin_edit_label,
            )
        )
        self._set_prompt_hint("Type a number, or `cancel`.")

    async def _select_checkin_to_reset(self, raw_value: str) -> None:
        selected: dict[str, Any] | None = self._select_numbered_item(raw_value)
        if selected is None:
            return
        self.pending_flow = {"type": "checkin_reset_confirm", "candidate": selected}
        self._write_dailybot(
            f"Delete today's response for **{self._checkin_edit_label(selected)}**?\n"
            "1. Delete\n2. Cancel"
        )
        self._set_prompt_hint("Type 1 to delete, 2 to cancel.")

    async def _confirm_checkin_reset(self, raw_value: str) -> None:
        assert self.pending_flow is not None
        decision: bool | None = _parse_confirmation(raw_value, extra_yes=frozenset({"delete"}))
        if decision is None:
            self._write_error("Type 1 to delete or 2 to cancel.")
            return
        if not decision:
            self.pending_flow = None
            self._set_prompt_hint()
            self._write_system("Check-in delete cancelled.")
            return
        candidate: dict[str, Any] = self.pending_flow["candidate"]
        checkin: dict[str, Any] = candidate.get("checkin") or {}
        followup_uuid: str = str(checkin.get("id") or checkin.get("followup_uuid") or "")
        self.pending_flow = None
        self._set_prompt_hint()
        self._set_loading(True)
        try:
            await asyncio.to_thread(
                self.client.delete_checkin_response,
                followup_uuid,
                response_date=date.today().isoformat(),
            )
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        self._write_dailybot(
            f"Done — deleted today's response for **{self._checkin_name(checkin)}**."
        )

    async def _handle_terminal_action_intent(self, intent: TerminalActionIntent) -> None:
        await self._start_terminal_flow_by_name(intent.action, {"args": list(intent.args)})

    async def _handle_chat_actions(self, actions: list[dict[str, Any]]) -> None:
        for action in actions:
            action_type: str = str(action.get("type") or "")
            flow_name: str = str(action.get("flow") or action.get("name") or "")
            if action_type == "terminal_flow" and flow_name:
                self.pending_flow = {
                    "type": "terminal_action_confirm",
                    "flow": flow_name,
                    "params": action.get("params") or {},
                }
                self._write_dailybot(f"Start the **{flow_name}** terminal flow?\n1. Yes\n2. No")
                self._set_prompt_hint("Type 1 to start, 2 to skip.")
                return
        action_names: str = ", ".join(str(action.get("name", "action")) for action in actions)
        self._write_system(f"Suggested action: {action_names}")

    async def _confirm_terminal_action(self, raw_value: str) -> None:
        assert self.pending_flow is not None
        decision: bool | None = _parse_confirmation(raw_value)
        if decision is None:
            self._write_error("Type 1 to start or 2 to skip.")
            return
        flow_name: str = str(self.pending_flow.get("flow") or "")
        params: dict[str, Any] = self.pending_flow.get("params") or {}
        self.pending_flow = None
        self._set_prompt_hint()
        if not decision:
            self._write_system("Skipped suggested action.")
            return
        await self._start_terminal_flow_by_name(flow_name, params)

    async def _start_terminal_flow_by_name(self, flow_name: str, params: dict[str, Any]) -> None:
        normalized: str = flow_name.strip().lower().replace("-", "_")
        if normalized in {"checkins", "checkin", "complete_checkin", "form_checkin"}:
            await self._start_checkins_flow()
            return
        if normalized in {"checkin_edit", "edit_checkin"}:
            await self._start_checkin_edit_flow()
            return
        if normalized in {"checkin_reset", "reset_checkin", "checkin_delete"}:
            await self._start_checkin_reset_flow()
            return
        if normalized in {"kudos", "send_kudos"}:
            receiver_query: str = str(params.get("receiver_query") or params.get("receivers") or "")
            message: str = str(params.get("message") or "")
            if receiver_query:
                await self._start_kudos_flow(
                    KudosIntent(receiver_query=receiver_query, message=message)
                )
            else:
                await self._start_kudos_menu()
            return
        if normalized in {"forms", "form"}:
            await self._start_forms_flow()
            return
        if normalized.startswith("form_"):
            await self._start_forms_flow(normalized.removeprefix("form_"))
            return
        if normalized == "users":
            await self._show_users()
            return
        if normalized == "teams":
            await self._show_teams()
            return
        if normalized == "team":
            await self._start_team_detail_flow(str(params.get("query") or ""))
            return
        if normalized == "dashboard":
            self._show_dashboard()
            return
        if normalized == "mood":
            await self._start_mood_flow()
            return
        self._write_dailybot("That suggested action is not supported in the terminal yet.")

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
        except (APIError, httpx.HTTPError) as exc:
            self._write_error(self._format_api_error(exc))
            return
        finally:
            self._set_loading(False)
        count = int(result.get("followups_count", 0))
        self._write_dailybot(f"Progress update submitted to {count} check-in(s).")

    def _select_numbered_item(self, raw_value: str) -> dict[str, Any] | None:
        assert self.pending_flow is not None
        items: list[dict[str, Any]] = self.pending_flow.get("items") or []
        try:
            selected_index: int = int(raw_value.strip())
        except ValueError:
            self._write_error(f"Enter a number between 1 and {len(items)}, or `cancel`.")
            return None
        if selected_index < 1 or selected_index > len(items):
            self._write_error(f"Enter a number between 1 and {len(items)}, or `cancel`.")
            return None
        return items[selected_index - 1]

    def _select_numbered_items(self, raw_value: str) -> list[dict[str, Any]] | None:
        assert self.pending_flow is not None
        items: list[dict[str, Any]] = self.pending_flow.get("items") or []
        raw_parts: list[str] = [
            part.strip() for part in raw_value.replace(" ", ",").split(",") if part.strip()
        ]
        if not raw_parts:
            self._write_error(f"Enter a number between 1 and {len(items)}, or `cancel`.")
            return None
        selected: list[dict[str, Any]] = []
        for raw_part in raw_parts:
            try:
                selected_index: int = int(raw_part)
            except ValueError:
                self._write_error(f"Enter numbers between 1 and {len(items)}, separated by commas.")
                return None
            if selected_index < 1 or selected_index > len(items):
                self._write_error(f"Enter numbers between 1 and {len(items)}, separated by commas.")
                return None
            item: dict[str, Any] = items[selected_index - 1]
            if item not in selected:
                selected.append(item)
        return selected

    def _ask_current_checkin_question(self) -> None:
        assert self.pending_flow is not None
        questions: list[dict[str, Any]] = self.pending_flow["questions"]
        index: int = int(self.pending_flow["index"])
        question: dict[str, Any] = questions[index]
        prompt: str = self._question_label(question, index)
        choices: list[str] = self._question_choices(question)
        lines: list[str] = [f"Question {index + 1}/{len(questions)}: {prompt}"]
        if self._question_type(question) == "boolean":
            lines.append("1. Yes")
            lines.append("2. No")
            self._set_prompt_hint("Type 1 for yes, 2 for no, or `cancel`.")
        elif choices:
            for choice_index, choice in enumerate(choices, start=1):
                lines.append(f"{choice_index}. {choice}")
            self._set_prompt_hint("Type a number, or `cancel`.")
        else:
            self._set_prompt_hint("Type your answer, or `cancel`.")
        self._write_dailybot("\n".join(lines))

    def _ask_current_checkin_edit_question(self) -> None:
        assert self.pending_flow is not None
        questions: list[dict[str, Any]] = self.pending_flow["questions"]
        index: int = int(self.pending_flow["index"])
        question: dict[str, Any] = questions[index]
        prompt: str = self._question_label(question, index)
        choices: list[str] = self._question_choices(question)
        existing_value: Any = self._existing_response_value(question, index)
        existing_label: str = self._format_answer(existing_value)
        lines: list[str] = [
            f"Question {index + 1}/{len(questions)}: {prompt}",
            f"Current answer: {existing_label}",
        ]
        if self._question_type(question) == "boolean":
            lines.append("1. Yes")
            lines.append("2. No")
            self._set_prompt_hint("Type 1/2, Enter to keep, or `cancel`.")
        elif choices:
            for choice_index, choice in enumerate(choices, start=1):
                lines.append(f"{choice_index}. {choice}")
            self._set_prompt_hint("Type a number, Enter to keep, or `cancel`.")
        else:
            self._set_prompt_hint("Type a replacement, Enter to keep, or `cancel`.")
        self._write_dailybot("\n".join(lines))

    def _existing_response_value(self, question: dict[str, Any], index: int) -> Any:
        assert self.pending_flow is not None
        existing_responses: list[dict[str, Any]] = self.pending_flow.get("existing_responses") or []
        # Prefer matching by question UUID (the API may return answers out of order
        # or with a different length than the template questions).
        question_uuid: str = str(question.get("uuid") or question.get("id") or "")
        if question_uuid:
            for response in existing_responses:
                response_uuid: str = str(
                    response.get("uuid") or response.get("question_uuid") or ""
                )
                if response_uuid == question_uuid:
                    return response.get("response")
        # Fallback: index-aligned (older responses without per-answer UUIDs).
        if index < len(existing_responses):
            return existing_responses[index].get("response")
        return ""

    @staticmethod
    def _format_answer(value: Any) -> str:
        if value is None or value == "" or value == {} or value == []:
            return "_empty_"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, dict):
            for key in (
                "response",
                "value",
                "text",
                "answer",
                "label",
                "name",
                "title",
                "content",
            ):
                nested_value: Any = value.get(key)
                if nested_value not in (None, "", {}, []):
                    return DailybotChatApp._format_answer(nested_value)
            parts: list[str] = []
            for key, nested_value in value.items():
                formatted_value: str = DailybotChatApp._format_answer(nested_value)
                if formatted_value != "_empty_":
                    parts.append(f"{key}: {formatted_value}")
            return ", ".join(parts) if parts else "_empty_"
        if isinstance(value, list):
            parts = [
                DailybotChatApp._format_answer(item)
                for item in value
                if item not in (None, "", {}, [])
            ]
            return ", ".join(part for part in parts if part != "_empty_") or "_empty_"
        return str(value)

    def _parse_question_answer(self, raw_value: str, question: dict[str, Any]) -> Any:
        value: str = raw_value.strip()
        question_type: str = self._question_type(question)
        choices: list[str] = self._question_choices(question)

        if question_type == "boolean":
            normalized: str = value.lower()
            if normalized in {"1", "yes", "y", "true"}:
                return True
            if normalized in {"2", "no", "n", "false"}:
                return False
            self._write_error("Type 1 for yes or 2 for no.")
            return None

        if choices:
            try:
                selected_index: int = int(value)
            except ValueError:
                self._write_error(f"Enter a number between 1 and {len(choices)}.")
                return None
            if selected_index < 1 or selected_index > len(choices):
                self._write_error(f"Enter a number between 1 and {len(choices)}.")
                return None
            return choices[selected_index - 1]

        if question_type == "numeric":
            try:
                return float(value) if "." in value else int(value)
            except ValueError:
                self._write_error("Enter a valid number.")
                return None

        return value

    @staticmethod
    def _build_checkin_responses(
        questions: list[dict[str, Any]],
        answers: list[Any],
    ) -> list[dict[str, Any]]:
        responses: list[dict[str, Any]] = []
        for index, (question, answer) in enumerate(zip(questions, answers, strict=True)):
            question_uuid: str = str(question.get("uuid") or question.get("id") or "")
            responses.append(
                {
                    "uuid": question_uuid,
                    "index": index,
                    "response": answer,
                }
            )
        return responses

    @staticmethod
    def _format_numbered_menu(
        heading: str,
        items: list[dict[str, Any]],
        label_fn: Any,
    ) -> str:
        lines: list[str] = [heading]
        for index, item in enumerate(items, start=1):
            lines.append(f"{index}. {label_fn(item)}")
        return "\n".join(lines)

    @classmethod
    def _checkin_label(cls, checkin: dict[str, Any]) -> str:
        question_count: int = len(checkin.get("template_questions", []))
        return (
            f"{cls._checkin_name(checkin)} "
            f"({question_count} question{'s' if question_count != 1 else ''})"
        )

    @classmethod
    def _checkin_edit_label(cls, candidate: dict[str, Any]) -> str:
        response: dict[str, Any] = candidate.get("response") or {}
        updated_at: str = str(response.get("updated_at") or response.get("created_at") or "")
        suffix: str = f" — {updated_at[:10]}" if updated_at else ""
        return f"{cls._checkin_name(candidate.get('checkin') or {})}{suffix}"

    @staticmethod
    def _checkin_name(checkin: dict[str, Any]) -> str:
        return str(checkin.get("followup_name") or checkin.get("name") or "Check-in")

    @staticmethod
    def _user_label(user: dict[str, Any]) -> str:
        return str(
            user.get("full_name")
            or user.get("name")
            or user.get("display_name")
            or user.get("email")
            or user.get("uuid")
            or "Unknown user"
        )

    @staticmethod
    def _team_label(team: dict[str, Any]) -> str:
        return str(team.get("name") or team.get("uuid") or team.get("id") or "Unknown team")

    @staticmethod
    def _join_labels(items: list[dict[str, Any]], label_fn: Any) -> str:
        return ", ".join(label_fn(item) for item in items)

    def _kudos_confirmation_text(self, flow: dict[str, Any]) -> str:
        users: list[dict[str, Any]] = flow.get("users") or []
        teams: list[dict[str, Any]] = flow.get("teams") or []
        user_labels: str = self._join_labels(users, self._user_label) if users else "None"
        team_labels: str = self._join_labels(teams, self._team_label) if teams else "None"
        company_value: str = str(flow.get("company_value") or "None")
        return (
            "**Send kudos?**\n\n"
            f"- Users: {user_labels}\n"
            f"- Teams: {team_labels}\n"
            f"- Message: {flow.get('message')}\n"
            f"- Company value: {company_value}\n\n"
            "1. Send\n2. Cancel"
        )

    @staticmethod
    def _question_label(question: dict[str, Any], index: int) -> str:
        for key in ("question", "text", "label", "name", "title"):
            value: Any = question.get(key)
            if value:
                return str(value)
        return f"Question {index + 1}"

    @staticmethod
    def _question_choices(question: dict[str, Any]) -> list[str]:
        raw_choices: Any = question.get("choices") or question.get("options") or []
        if not isinstance(raw_choices, list):
            return []
        choices: list[str] = []
        for choice in raw_choices:
            if isinstance(choice, str):
                choices.append(choice)
            elif isinstance(choice, dict):
                label: Any = choice.get("label") or choice.get("text") or choice.get("value")
                if label:
                    choices.append(str(label))
        return choices

    @staticmethod
    def _question_type(question: dict[str, Any]) -> str:
        raw_type: str = str(question.get("question_type") or question.get("type") or "")
        normalized: str = raw_type.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in {"boolean", "bool", "yes_no", "yes/no", "toggle"}:
            return "boolean"
        if normalized in {"number", "numeric", "integer", "int", "float", "decimal"}:
            return "numeric"
        return "text"

    def _get_current_user_uuid(self) -> str | None:
        data: dict[str, Any] = self.client.auth_status()
        user_raw: Any = data.get("user", {})
        if isinstance(user_raw, dict):
            value: Any = user_raw.get("uuid") or user_raw.get("id")
            return str(value) if value else None
        return None

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

    def _set_prompt_hint(self, hint: str | None = None) -> None:
        prompt = self.query_one("#prompt", Input)
        prompt.placeholder = hint or "> Ask Dailybot anything..."

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

    async def _complete_prompt(self, *, reverse: bool = False) -> None:
        prompt = self.query_one("#prompt", Input)
        value: str = prompt.value
        cursor_position: int = prompt.cursor_position

        if self._can_cycle_completion(value, cursor_position):
            self._cycle_completion(prompt, reverse=reverse)
            return

        command_completion: tuple[str, int] | None = self._command_completion(
            value,
            cursor_position,
            reverse=reverse,
        )
        if command_completion is not None:
            self._apply_completion(prompt, command_completion[0], command_completion[1])
            return

        mention_items: list[str] = await self._load_mention_completion_items()
        mention_completion: tuple[str, int] | None = self._mention_completion(
            value,
            cursor_position,
            mention_items,
            reverse=reverse,
        )
        if mention_completion is not None:
            self._apply_completion(prompt, mention_completion[0], mention_completion[1])
            return
        self.completion_state = None

    def _command_completion(
        self,
        value: str,
        cursor_position: int,
        *,
        reverse: bool = False,
    ) -> tuple[str, int] | None:
        before_cursor: str = value[:cursor_position]
        after_cursor: str = value[cursor_position:]
        if not before_cursor.startswith("/") or "\n" in before_cursor:
            return None
        prefix: str = before_cursor.lower()
        matches: list[str] = [
            command for command in COMMAND_COMPLETIONS if command.lower().startswith(prefix)
        ]
        if not matches:
            return None
        index: int = len(matches) - 1 if reverse else 0
        completed_value: str = matches[index] + after_cursor
        self.completion_state = {
            "matches": matches,
            "index": index,
            "last_value": completed_value,
            "last_cursor": len(matches[index]),
        }
        return completed_value, len(matches[index])

    def _mention_completion(
        self,
        value: str,
        cursor_position: int,
        mention_items: list[str],
        *,
        reverse: bool = False,
    ) -> tuple[str, int] | None:
        before_cursor: str = value[:cursor_position]
        after_cursor: str = value[cursor_position:]
        mention_start: int = before_cursor.rfind("@")
        if mention_start < 0:
            return None
        if mention_start > 0 and not before_cursor[mention_start - 1].isspace():
            return None
        raw_prefix: str = before_cursor[mention_start + 1 :]
        if any(char.isspace() for char in raw_prefix):
            return None
        prefix: str = raw_prefix.lower()
        matches: list[str] = [
            item for item in mention_items if item.removeprefix("@").lower().startswith(prefix)
        ]
        if not matches:
            return None
        index: int = len(matches) - 1 if reverse else 0
        completed_value: str = before_cursor[:mention_start] + matches[index] + after_cursor
        cursor: int = mention_start + len(matches[index])
        self.completion_state = {
            "matches": matches,
            "index": index,
            "last_value": completed_value,
            "last_cursor": cursor,
        }
        return completed_value, cursor

    async def _load_mention_completion_items(self) -> list[str]:
        if self.mention_completion_items is not None:
            return self.mention_completion_items
        try:
            users, teams = await asyncio.gather(
                asyncio.to_thread(self.client.list_users),
                asyncio.to_thread(self.client.list_teams),
            )
        except (APIError, httpx.HTTPError):
            # Autocomplete fires on a keystroke — fail silently and do NOT cache the
            # failure, so completion recovers once the directory is reachable again.
            return []
        user_items: list[str] = [f"@{self._user_label(user)}" for user in users]
        team_items: list[str] = [f"@{self._team_label(team)} team" for team in teams]
        self.mention_completion_items = [*user_items, *team_items]
        return self.mention_completion_items

    def _can_cycle_completion(self, value: str, cursor_position: int) -> bool:
        if self.completion_state is None:
            return False
        return value == self.completion_state.get(
            "last_value"
        ) and cursor_position == self.completion_state.get("last_cursor")

    def _cycle_completion(self, prompt: Input, *, reverse: bool = False) -> None:
        assert self.completion_state is not None
        matches: list[str] = self.completion_state.get("matches") or []
        if not matches:
            self.completion_state = None
            return
        step: int = -1 if reverse else 1
        index: int = (int(self.completion_state.get("index") or 0) + step) % len(matches)
        value: str = prompt.value
        cursor_position: int = prompt.cursor_position
        current_match: str = str(matches[int(self.completion_state.get("index") or 0)])
        replacement: str = matches[index]
        start: int = max(0, cursor_position - len(current_match))
        completed_value: str = value[:start] + replacement + value[cursor_position:]
        self.completion_state["index"] = index
        self.completion_state["last_value"] = completed_value
        self.completion_state["last_cursor"] = start + len(replacement)
        self._set_prompt_completion(prompt, completed_value, start + len(replacement))

    def _apply_completion(self, prompt: Input, value: str, cursor_position: int) -> None:
        if self.completion_state is None:
            self.completion_state = {
                "matches": [value],
                "index": 0,
                "last_value": value,
                "last_cursor": cursor_position,
            }
        else:
            self.completion_state["last_value"] = value
            self.completion_state["last_cursor"] = cursor_position
        self._set_prompt_completion(prompt, value, cursor_position)

    @staticmethod
    def _set_prompt_completion(prompt: Input, value: str, cursor_position: int) -> None:
        prompt.value = value
        prompt.cursor_position = cursor_position

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
            words = [
                word for word in local_part.replace("_", ".").replace("-", ".").split(".") if word
            ]
            if words:
                return " ".join(word.capitalize() for word in words)
        return None

    @staticmethod
    def _format_api_error(exc: APIError | httpx.HTTPError) -> str:
        if isinstance(exc, APIError):
            if exc.status_code in (401, 403):
                return "Session expired or missing. Run: dailybot login"
            if exc.status_code == 429:
                return "Rate limit exceeded. Wait a moment and try again."
            return exc.detail
        if isinstance(exc, httpx.TimeoutException):
            return "Dailybot took too long to respond. Please try again."
        return "Couldn't reach Dailybot. Check your connection and try again."


def run_chat_app(client: DailyBotClient) -> None:
    """Run the Textual chat app."""
    DailybotChatApp(client).run()
