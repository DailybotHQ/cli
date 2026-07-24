"""Chat platform messaging commands (``dailybot chat send`` / ``update``).

Sends Dailybot **bot** messages to the organization's connected chat platform
(Slack, Microsoft Teams, Discord, Google Chat) — to user DMs, channels, and
teams — via ``POST /v1/send-message/``. Authenticated with the login Bearer
token (``dailybot login``, sends *as you*, role-scoped) or an org API key
(``dailybot config key=...``, org-wide). The two auth modes are interchangeable
at the call site; the client picks API key first, then falls back to Bearer.

This is distinct from the agent surfaces:

- ``agent update``  → progress reports to the Dailybot dashboard
- ``agent message`` → inter-agent inbox messages
- ``chat send``     → a bot message delivered to the real chat platform

The request body is assembled by :func:`build_chat_payload` (a pure,
well-tested helper) so the CLI command, the interactive TUI, and any future
caller produce identical payloads. Power users and agents can bypass the
flags entirely with ``--payload-json`` for the raw API body, which keeps the
command forward-compatible with every current and future API field.
"""

import json
from typing import Any

import click

from dailybot_cli.api_client import APIError, DailyBotClient
from dailybot_cli.commands.agent import _merge_repo_metadata, _resolve_agent_context
from dailybot_cli.commands.public_api_helpers import (
    EXIT_NOT_AUTHENTICATED,
    EXIT_PERMISSION_DENIED,
    UUID_PATTERN,
    emit_json,
    exit_for_api_error,
    get_current_user_uuid,
)
from dailybot_cli.display import (
    console,
    print_chat_message_result,
    print_error,
    print_warning,
)

CHANNEL_TYPES: tuple[str, ...] = (
    "channel",
    "private_channel",
    "group_chat",
    "direct_message",
)
BUTTON_SEPARATOR: str = "::"
ERGONOMIC_BUTTON_SEPARATOR: str = "="
MAX_BOT_USERNAME_CHARS: int = 80
MAX_THREAD_RESPONSES: int = 10
MAX_BUTTONS_PER_MESSAGE: int = 25
BUTTON_CALLBACK_KEYS: tuple[str, ...] = (
    "callback_url",
    "callback_form",
    "callback_command",
    "callback_prompt",
    "callback_workflow",
)
BUTTON_ERROR_CODES: frozenset[str] = frozenset(
    {
        "button_link_and_callback_conflict",
        "button_callback_conflict",
        "button_callback_url_invalid",
        "button_modal_body_invalid",
        "button_callback_form_not_found",
        "button_callback_command_invalid",
        "button_callback_prompt_invalid",
        "button_callback_workflow_not_found",
        "button_response_invalid",
        "button_callback_auth_invalid",
        "buttons_count_out_of_range",
    }
)


class ChatPayloadError(ValueError):
    """Raised when chat message inputs are invalid (friendly, user-facing)."""


def _parse_button(raw: str, *, kind: str) -> tuple[str, str]:
    """Split a ``"Label::value"`` button spec into ``(label, value)``."""
    label, sep, value = raw.partition(BUTTON_SEPARATOR)
    label = label.strip()
    value = value.strip()
    if not sep or not label or not value:
        target: str = "URL" if kind == "link" else "value"
        raise ChatPayloadError(
            f"Invalid {kind} button '{raw}'. Expected 'Label{BUTTON_SEPARATOR}{target}' "
            f"(e.g. 'Open docs{BUTTON_SEPARATOR}https://example.com')."
        )
    return label, value


def _parse_ergonomic_button(raw: str, *, flag: str) -> tuple[str, str]:
    """Split a ``"Label=value"`` ergonomic button spec into ``(label, value)``."""
    label, sep, value = raw.partition(ERGONOMIC_BUTTON_SEPARATOR)
    label = label.strip()
    value = value.strip()
    if not sep or not label or not value:
        raise ChatPayloadError(
            f"Invalid {flag} '{raw}'. Expected 'Label{ERGONOMIC_BUTTON_SEPARATOR}value' "
            f"(e.g. 'Yes{ERGONOMIC_BUTTON_SEPARATOR}approve')."
        )
    return label, value


def validate_buttons(buttons: list[Any], *, flag_hint: str = "--buttons") -> None:
    """Light client-side checks; never strips unknown keys (API owns the contract).

    Enforces: ≤25 buttons, each entry is an object with a non-empty ``label``,
    and at most one of the five callback fields per button. Richer rules
    (modal size, URL shape, recursive ``response`` trees) stay server-side.
    """
    if len(buttons) > MAX_BUTTONS_PER_MESSAGE:
        raise ChatPayloadError(
            f"At most {MAX_BUTTONS_PER_MESSAGE} buttons are allowed per message ({flag_hint})."
        )
    for index, button in enumerate(buttons, start=1):
        if not isinstance(button, dict):
            raise ChatPayloadError(f"Button #{index} must be a JSON object ({flag_hint}).")
        label_raw: Any = button.get("label")
        label: str = str(label_raw).strip() if label_raw is not None else ""
        if not label:
            raise ChatPayloadError(f"Button #{index} is missing a required 'label' ({flag_hint}).")
        present: list[str] = [
            key for key in BUTTON_CALLBACK_KEYS if button.get(key) not in (None, "")
        ]
        if len(present) > 1:
            raise ChatPayloadError(
                f"Button '{label}' sets more than one callback ({', '.join(present)}). "
                "At most one of callback_url, callback_form, callback_command, "
                "callback_prompt, or callback_workflow is allowed."
            )


def build_chat_payload(
    *,
    text: str | None = None,
    users: list[str] | None = None,
    channels: list[str] | None = None,
    teams: list[str] | None = None,
    image_url: str | None = None,
    link_buttons: list[tuple[str, str]] | None = None,
    action_buttons: list[tuple[str, str]] | None = None,
    extra_buttons: list[dict[str, Any]] | None = None,
    thread: str | None = None,
    channel_type: str | None = None,
    bot_name: str | None = None,
    bot_icon_url: str | None = None,
    bot_icon_emoji: str | None = None,
    send_as_user: str | None = None,
    ephemeral: bool = False,
    skip_time_off: bool = False,
    metadata: dict[str, Any] | None = None,
    bot_message_id: str | None = None,
    thread_responses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble and validate a ``/v1/send-message/`` request body.

    Only set keys are included, so the payload stays minimal. Raises
    :class:`ChatPayloadError` on invalid combinations the API would reject —
    surfacing a friendly message before the network call.

    *extra_buttons* is a list of raw button objects (from ``--buttons`` JSON or
    ergonomic approval/workflow flags). Keys are forwarded untouched — the CLI
    stays forward-compatible with every current and future button field.
    *thread_responses* posts follow-up messages inside the parent's thread in
    the same call (each reply inherits the parent's recipients). The API mints
    one id per reply in the response, so each is independently editable.
    """
    if thread_responses and len(thread_responses) > MAX_THREAD_RESPONSES:
        raise ChatPayloadError(
            f"At most {MAX_THREAD_RESPONSES} thread replies are allowed per message."
        )
    if channel_type is not None and channel_type not in CHANNEL_TYPES:
        raise ChatPayloadError(
            f"Invalid --channel-type '{channel_type}'. Choose one of: {', '.join(CHANNEL_TYPES)}."
        )
    if bot_icon_url and bot_icon_emoji:
        raise ChatPayloadError(
            "Use only one of --bot-icon-url / --bot-icon-emoji (they are mutually exclusive)."
        )
    if bot_name is not None and len(bot_name) > MAX_BOT_USERNAME_CHARS:
        raise ChatPayloadError(f"--bot-name must be at most {MAX_BOT_USERNAME_CHARS} characters.")
    if bot_icon_url and not bot_icon_url.startswith("https://"):
        raise ChatPayloadError("--bot-icon-url must start with 'https://'.")
    if send_as_user is not None:
        if bot_name or bot_icon_url or bot_icon_emoji:
            raise ChatPayloadError(
                "--send-as-user / --send-as-me can't be combined with --bot-name / "
                "--bot-icon-url / --bot-icon-emoji."
            )
        if not UUID_PATTERN.match(send_as_user):
            raise ChatPayloadError("Invalid UUID for --send-as-user.")

    payload: dict[str, Any] = {}

    if text:
        payload["message"] = text
    if image_url:
        payload["image_url"] = image_url

    buttons: list[dict[str, Any]] = []
    for label, url in link_buttons or []:
        buttons.append({"label": label, "button_type": "link", "url": url})
    for label, value in action_buttons or []:
        buttons.append({"label": label, "button_type": "interactive", "value": value})
    if extra_buttons:
        buttons.extend(extra_buttons)
    if buttons:
        validate_buttons(buttons)
        payload["buttons"] = buttons

    if users:
        payload["target_users"] = list(users)
    if channels:
        if thread or channel_type:
            payload["target_channels"] = [
                _channel_object(cid, thread=thread, channel_type=channel_type) for cid in channels
            ]
        else:
            payload["target_channels"] = list(channels)
    if teams:
        payload["target_teams"] = list(teams)

    platform_settings: dict[str, Any] = {}
    if bot_name:
        platform_settings["bot_username"] = bot_name
    if bot_icon_url:
        platform_settings["bot_icon_url"] = bot_icon_url
    if bot_icon_emoji:
        platform_settings["bot_icon_emoji"] = bot_icon_emoji
    if ephemeral:
        platform_settings["is_ephemeral"] = True
    if platform_settings:
        payload["platform_settings"] = platform_settings

    if send_as_user is not None:
        payload["send_as_user"] = send_as_user
    if skip_time_off:
        payload["skip_users_on_time_off"] = True
    if metadata:
        payload["metadata"] = metadata
    if bot_message_id:
        payload["bot_message_id"] = bot_message_id
    if thread_responses:
        payload["thread_responses"] = thread_responses

    _validate_targets(payload)
    return payload


def _channel_object(
    channel_id: str, *, thread: str | None, channel_type: str | None
) -> dict[str, Any]:
    obj: dict[str, Any] = {"id": channel_id}
    if channel_type:
        obj["channel_type"] = channel_type
    if thread:
        obj["thread"] = thread
    return obj


def _validate_targets(payload: dict[str, Any]) -> None:
    """Enforce the API's 'at least one target' rule before sending."""
    if not (
        payload.get("target_users") or payload.get("target_channels") or payload.get("target_teams")
    ):
        raise ChatPayloadError("At least one target is required: --user, --channel, or --team.")


def _resolved_client(profile_flag: str | None) -> tuple[DailyBotClient, dict[str, Any]]:
    """Build an API-key-preferring client and the repo default metadata.

    Reuses the agent context resolver (send-message is org-API-key scoped, the
    same auth surface as agent reports). The agent display name is irrelevant
    here, so it is discarded.
    """
    _agent_name, client, repo_default_metadata = _resolve_agent_context(profile_flag, None)
    return client, repo_default_metadata


def _send(
    client: DailyBotClient, payload: dict[str, Any], *, updated: bool, json_mode: bool
) -> None:
    """Run a single send/update call and render the result (used by `update`)."""
    result: dict[str, Any] = _execute_send(
        client, payload, status="Sending message...", json_mode=json_mode
    )
    if json_mode:
        emit_json(result)
        return
    print_chat_message_result(result, updated=updated)


def _execute_send(
    client: DailyBotClient,
    payload: dict[str, Any],
    *,
    status: str,
    json_mode: bool = False,
) -> dict[str, Any]:
    """Call the API with friendly error translation; return the result or exit."""
    if payload.get("platform_settings", {}).get("is_ephemeral") and not payload.get("target_users"):
        # The API silently skips an ephemeral message with no resolvable user.
        print_warning(
            "Ephemeral messages need a --user target; a channel-only ephemeral send is skipped "
            "by the platform."
        )
    try:
        with console.status(status):
            return client.send_chat_message(payload)
    except APIError as e:
        overrides: dict[str, str] = {
            "org_admin_required": (
                "Sending as another user (--send-as-user / --send-as-me) requires organization "
                "admin privileges. Run it with an admin account or an org admin's API key."
            ),
            "cli_send_message_target_not_allowed": (
                f"{e.detail}\n  Your role can only reach teammates, public channels, and teams "
                "you belong to. Use an allowed target, or an org API key for org-wide reach."
            ),
            "invalid_thread_responses": (
                f"{e.detail}\n  Thread replies allow at most 10 items, one level deep, with no "
                "targeting of their own (they inherit the parent's recipients)."
            ),
        }
        # Button contract errors: surface the server detail verbatim (richest signal).
        if e.code and e.code in BUTTON_ERROR_CODES and e.detail:
            overrides[e.code] = e.detail
        # Auth hint when the server didn't send a more specific code.
        if e.status_code in (401, 403) and e.code not in overrides:
            auth_hint: str = (
                f"{e.detail}\n  Authenticate first: run 'dailybot login' (sends as you) or set an "
                "org API key with 'dailybot config key=<API_KEY>'."
            )
            if e.code:
                overrides[e.code] = auth_hint
            else:
                if json_mode:
                    emit_json({"error": auth_hint, "status": e.status_code, "detail": e.detail})
                else:
                    print_error(auth_hint)
                # Match exit_for_api_error's status→exit-code contract so headless
                # consumers see a stable code whether or not the server sent `code`.
                exit_code: int = (
                    EXIT_NOT_AUTHENTICATED if e.status_code == 401 else EXIT_PERMISSION_DENIED
                )
                raise SystemExit(exit_code)
        if e.status_code == 429 and e.code is None:
            rate_msg: str = "Rate limit exceeded for chat sends. Wait a bit and retry."
            if json_mode:
                emit_json({"error": rate_msg, "status": 429, "detail": e.detail})
            else:
                print_error(rate_msg)
            raise SystemExit(1)
        exit_for_api_error(e, json_mode, code_overrides=overrides)


# --- chat group ---


@click.group(name="chat")
@click.option("--profile", "-p", default=None, help="Agent profile name from agents.json.")
@click.pass_context
def chat(ctx: click.Context, profile: str | None) -> None:
    """Send Dailybot bot messages to your chat platform (Slack/Teams/Discord/Google Chat).

    \b
    Targets users (DM), channels, and teams. Authenticated with your login
    session ('dailybot login' — sends as you, role-scoped) or an org API key
    ('dailybot config key=...', org-wide). Distinct from 'agent message'
    (inter-agent inbox) and 'agent update' (progress reports).
    """
    ctx.ensure_object(dict)
    ctx.obj["profile"] = profile


def _target_options(fn: Any) -> Any:
    """Shared targeting + content + identity options for send and update."""
    decorators = [
        click.option(
            "--user",
            "-u",
            "users",
            multiple=True,
            help="Target user by UUID, email, or external id (repeatable).",
        ),
        click.option(
            "--channel", "-c", "channels", multiple=True, help="Target channel id (repeatable)."
        ),
        click.option(
            "--team",
            "-t",
            "teams",
            multiple=True,
            help="Target team UUID; expanded to members as DMs (repeatable).",
        ),
        click.option("--text", "-m", default=None, help="Message text (markdown where supported)."),
        click.option("--image-url", "-i", default=None, help="Public image URL to attach."),
        click.option(
            "--link-button",
            "link_buttons_raw",
            multiple=True,
            help="Link button 'Label::https://url' (repeatable).",
        ),
        click.option(
            "--button",
            "action_buttons_raw",
            multiple=True,
            help="Interactive button 'Label::value' (repeatable).",
        ),
        click.option(
            "--buttons",
            "buttons_json",
            default=None,
            help=(
                "Raw buttons JSON array — full API contract (callbacks, modals, response, "
                "callback_auth). Keys forwarded untouched; max 25."
            ),
        ),
        click.option(
            "--approve-button",
            "approve_button_raw",
            default=None,
            help="Approval button 'Label=value' (needs --callback-url).",
        ),
        click.option(
            "--reject-button",
            "reject_button_raw",
            default=None,
            help="Reject button 'Label=value' (needs --callback-url).",
        ),
        click.option(
            "--callback-url",
            "callback_url",
            default=None,
            help="HTTPS callback URL for --approve-button / --reject-button.",
        ),
        click.option(
            "--callback-bearer",
            "callback_bearer",
            default=None,
            help=(
                "Optional bearer token for callback_auth on approval buttons. Prefer "
                'passing via an env var (e.g. --callback-bearer "$TOKEN") — a raw '
                "token on the command line lands in shell history and process lists."
            ),
        ),
        click.option(
            "--workflow-button",
            "workflow_buttons_raw",
            multiple=True,
            help="Workflow button 'Label=<workflow-uuid>' (callback_workflow; repeatable).",
        ),
        click.option("--thread", default=None, help="Thread id to reply inside (channels)."),
        click.option(
            "--channel-type",
            default=None,
            help=f"Channel type: {', '.join(CHANNEL_TYPES)} (default channel).",
        ),
        click.option("--bot-name", default=None, help="Custom bot display name (Slack only)."),
        click.option("--bot-icon-url", default=None, help="Custom bot avatar URL, https (Slack)."),
        click.option("--bot-icon-emoji", default=None, help="Custom bot avatar emoji (Slack)."),
        click.option(
            "--ephemeral",
            is_flag=True,
            default=False,
            help="Send ephemerally — only the recipient sees it (Slack; needs --user).",
        ),
        click.option(
            "--skip-time-off",
            is_flag=True,
            default=False,
            help="Skip users flagged as away / on time-off.",
        ),
        click.option("--metadata", "-d", default=None, help="JSON metadata to attach."),
        click.option(
            "--payload-json",
            default=None,
            help="Raw request body JSON (full API control; ignores the building flags).",
        ),
        click.option(
            "--json",
            "json_mode",
            is_flag=True,
            default=False,
            help="Emit the raw API response as JSON to stdout (headless).",
        ),
    ]
    for decorator in reversed(decorators):
        fn = decorator(fn)
    return fn


def _build_extra_buttons(
    *,
    buttons_json: str | None,
    approve_button_raw: str | None,
    reject_button_raw: str | None,
    callback_url: str | None,
    callback_bearer: str | None,
    workflow_buttons_raw: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Assemble raw button objects from --buttons JSON and ergonomic flags."""
    extra: list[dict[str, Any]] = []

    if buttons_json is not None:
        try:
            parsed: Any = json.loads(buttons_json)
        except json.JSONDecodeError:
            raise ChatPayloadError("Invalid JSON in --buttons.") from None
        if not isinstance(parsed, list):
            raise ChatPayloadError("--buttons must be a JSON array of button objects.")
        for item in parsed:
            if not isinstance(item, dict):
                raise ChatPayloadError("--buttons entries must be JSON objects.")
            extra.append(dict(item))  # shallow copy; keys untouched

    if callback_bearer and not callback_url:
        raise ChatPayloadError("--callback-bearer requires --callback-url.")
    if (approve_button_raw or reject_button_raw) and not callback_url:
        raise ChatPayloadError("--approve-button / --reject-button require --callback-url.")
    if callback_url and not (approve_button_raw or reject_button_raw):
        raise ChatPayloadError(
            "--callback-url needs at least one of --approve-button / --reject-button "
            "(or put callback_url inside --buttons JSON)."
        )

    callback_auth: dict[str, Any] | None = None
    if callback_bearer:
        callback_auth = {"type": "bearer", "token": callback_bearer}

    for raw, flag in (
        (approve_button_raw, "--approve-button"),
        (reject_button_raw, "--reject-button"),
    ):
        if not raw:
            continue
        label, value = _parse_ergonomic_button(raw, flag=flag)
        button: dict[str, Any] = {
            "label": label,
            "button_type": "interactive",
            "value": value,
            "callback_url": callback_url,
        }
        if callback_auth is not None:
            button["callback_auth"] = dict(callback_auth)
        extra.append(button)

    for raw in workflow_buttons_raw:
        label, workflow_uuid = _parse_ergonomic_button(raw, flag="--workflow-button")
        extra.append(
            {
                "label": label,
                "button_type": "interactive",
                "value": workflow_uuid,
                "callback_workflow": workflow_uuid,
            }
        )

    return extra


def _assemble_payload(
    *,
    payload_json: str | None,
    metadata: str | None,
    repo_default_metadata: dict[str, Any],
    bot_message_id: str | None,
    json_mode: bool,
    **build_kwargs: Any,
) -> dict[str, Any]:
    """Build the request body from --payload-json (raw) or the structured flags.

    Centralizes the flag→payload mapping and validation so send/update share
    it. Exits with a friendly error on any invalid input.
    """
    metadata_dict: dict[str, Any] | None = None
    if metadata:
        try:
            metadata_dict = json.loads(metadata)
        except json.JSONDecodeError:
            print_error("Invalid JSON in --metadata.")
            raise SystemExit(1)
    metadata_dict = _merge_repo_metadata(metadata_dict, repo_default_metadata)

    if payload_json is not None:
        try:
            raw: Any = json.loads(payload_json)
        except json.JSONDecodeError:
            print_error("Invalid JSON in --payload-json.")
            raise SystemExit(1)
        if not isinstance(raw, dict):
            print_error("--payload-json must be a JSON object.")
            raise SystemExit(1)
        if metadata_dict and "metadata" not in raw:
            raw["metadata"] = metadata_dict
        if bot_message_id:
            raw["bot_message_id"] = bot_message_id
        try:
            _validate_targets(raw)
            raw_buttons: Any = raw.get("buttons")
            if raw_buttons is not None:
                if not isinstance(raw_buttons, list):
                    raise ChatPayloadError("--payload-json 'buttons' must be a JSON array.")
                validate_buttons(raw_buttons, flag_hint="--payload-json buttons")
        except ChatPayloadError as exc:
            print_error(str(exc))
            raise SystemExit(1)
        return raw

    link_buttons: list[tuple[str, str]] = []
    action_buttons: list[tuple[str, str]] = []
    thread_messages: tuple[str, ...] = build_kwargs.pop("thread_messages_raw", ())
    thread_responses: list[dict[str, Any]] = [{"message": t} for t in thread_messages if t]
    buttons_json: str | None = build_kwargs.pop("buttons_json", None)
    approve_button_raw: str | None = build_kwargs.pop("approve_button_raw", None)
    reject_button_raw: str | None = build_kwargs.pop("reject_button_raw", None)
    callback_url: str | None = build_kwargs.pop("callback_url", None)
    callback_bearer: str | None = build_kwargs.pop("callback_bearer", None)
    workflow_buttons_raw: tuple[str, ...] = build_kwargs.pop("workflow_buttons_raw", ())
    try:
        for raw_btn in build_kwargs.pop("link_buttons_raw", ()):
            link_buttons.append(_parse_button(raw_btn, kind="link"))
        for raw_btn in build_kwargs.pop("action_buttons_raw", ()):
            action_buttons.append(_parse_button(raw_btn, kind="interactive"))
        extra_buttons: list[dict[str, Any]] = _build_extra_buttons(
            buttons_json=buttons_json,
            approve_button_raw=approve_button_raw,
            reject_button_raw=reject_button_raw,
            callback_url=callback_url,
            callback_bearer=callback_bearer,
            workflow_buttons_raw=workflow_buttons_raw,
        )
        return build_chat_payload(
            link_buttons=link_buttons,
            action_buttons=action_buttons,
            extra_buttons=extra_buttons or None,
            metadata=metadata_dict,
            bot_message_id=bot_message_id,
            thread_responses=thread_responses or None,
            **build_kwargs,
        )
    except ChatPayloadError as exc:
        print_error(str(exc))
        raise SystemExit(1)


@chat.command(name="send")
@_target_options
@click.option(
    "--thread-message",
    "thread_messages_raw",
    multiple=True,
    help="Reply posted inside the parent message's thread (repeatable; max 10).",
)
@click.option(
    "--send-as-user",
    "send_as_user",
    default=None,
    help=(
        "Send with the identity (name and profile picture) of the given user UUID. "
        "Admin-only. Slack only. Mutually exclusive with --bot-name/--bot-icon-url."
    ),
)
@click.option(
    "--send-as-me",
    "send_as_me",
    is_flag=True,
    default=False,
    help="Shortcut: send as yourself (your name + profile picture). Admin-only. Slack only.",
)
@click.pass_context
def chat_send(
    ctx: click.Context,
    users: tuple[str, ...],
    channels: tuple[str, ...],
    teams: tuple[str, ...],
    text: str | None,
    image_url: str | None,
    link_buttons_raw: tuple[str, ...],
    action_buttons_raw: tuple[str, ...],
    buttons_json: str | None,
    approve_button_raw: str | None,
    reject_button_raw: str | None,
    callback_url: str | None,
    callback_bearer: str | None,
    workflow_buttons_raw: tuple[str, ...],
    thread: str | None,
    channel_type: str | None,
    bot_name: str | None,
    bot_icon_url: str | None,
    bot_icon_emoji: str | None,
    send_as_user: str | None,
    send_as_me: bool,
    ephemeral: bool,
    skip_time_off: bool,
    metadata: str | None,
    payload_json: str | None,
    json_mode: bool,
    thread_messages_raw: tuple[str, ...],
) -> None:
    """Send a bot message to users, channels, or teams.

    \b
      dailybot chat send -c C0123456789 -m "Deploy finished 🚀"
      dailybot chat send -u ana@co.com -u luis@co.com -m "Standup in 10 min"
      dailybot chat send -t <team-uuid> -m "Survey is open until Friday"
      dailybot chat send -c C0123 -m "Build #421 ✅" --bot-name "Release Bot" \\
        --bot-icon-emoji ":rocket:"
      dailybot chat send -c C0123 -m "Actions:" --link-button "Open report::https://app/r"
      dailybot chat send -u ana@co.com -m "Heads up" --ephemeral
      dailybot chat send --payload-json '{"target_channels":["C0"],"messages":[...]}' --json

    \b
    Approval flow (callback_url buttons + optional bearer auth):
      dailybot chat send -u <uuid> -m "Deploy?" \\
        --approve-button "Yes=approve" --reject-button "No=deny" \\
        --callback-url https://hooks.example.com/req42 --callback-bearer "$TOKEN"

    \b
    Workflow button (fires an api_trigger workflow on click):
      dailybot chat send -c C0123 -m "Ready?" \\
        --workflow-button "Run release=<workflow-uuid>"

    \b
    Full button contract via --buttons JSON (modals, response trees, …):
      dailybot chat send -u <uuid> -m "Details?" --buttons '[
        {"label":"Open","button_type":"interactive","value":"open",
         "callback_url":"https://hooks.example.com/x",
         "modal_body":{"title":"Notes","blocks":[
           {"type":"input","name":"notes","label":"Notes","multiline":true}]}}]'

    \b
    Report style — a short headline plus the detail inside its thread:
      dailybot chat send -c C0123 -m "🚀 Release v2.4 shipped" \\
        --thread-message "Changelog: ..." \\
        --thread-message "Rollout: 100% at 14:30 UTC"
    """
    if send_as_user and send_as_me:
        print_error("Use only one of --send-as-user / --send-as-me.")
        raise SystemExit(1)
    profile_flag: str | None = ctx.obj.get("profile")
    client, repo_default_metadata = _resolved_client(profile_flag)
    resolved_send_as: str | None = send_as_user
    if send_as_me:
        resolved_send_as = get_current_user_uuid(client)
        if not resolved_send_as:
            print_error(
                "Couldn't resolve your user UUID for --send-as-me. Use "
                "--send-as-user <uuid> explicitly (this needs a login session)."
            )
            raise SystemExit(1)
    payload: dict[str, Any] = _assemble_payload(
        payload_json=payload_json,
        metadata=metadata,
        repo_default_metadata=repo_default_metadata,
        bot_message_id=None,
        json_mode=json_mode,
        text=text,
        users=list(users),
        channels=list(channels),
        teams=list(teams),
        image_url=image_url,
        link_buttons_raw=link_buttons_raw,
        action_buttons_raw=action_buttons_raw,
        buttons_json=buttons_json,
        approve_button_raw=approve_button_raw,
        reject_button_raw=reject_button_raw,
        callback_url=callback_url,
        callback_bearer=callback_bearer,
        workflow_buttons_raw=workflow_buttons_raw,
        thread_messages_raw=thread_messages_raw,
        thread=thread,
        channel_type=channel_type,
        bot_name=bot_name,
        bot_icon_url=bot_icon_url,
        bot_icon_emoji=bot_icon_emoji,
        send_as_user=resolved_send_as,
        ephemeral=ephemeral,
        skip_time_off=skip_time_off,
    )
    _send(client, payload, updated=False, json_mode=json_mode)


@chat.command(name="update")
@click.argument("bot_message_id")
@_target_options
@click.pass_context
def chat_update(
    ctx: click.Context,
    bot_message_id: str,
    users: tuple[str, ...],
    channels: tuple[str, ...],
    teams: tuple[str, ...],
    text: str | None,
    image_url: str | None,
    link_buttons_raw: tuple[str, ...],
    action_buttons_raw: tuple[str, ...],
    buttons_json: str | None,
    approve_button_raw: str | None,
    reject_button_raw: str | None,
    callback_url: str | None,
    callback_bearer: str | None,
    workflow_buttons_raw: tuple[str, ...],
    thread: str | None,
    channel_type: str | None,
    bot_name: str | None,
    bot_icon_url: str | None,
    bot_icon_emoji: str | None,
    ephemeral: bool,
    skip_time_off: bool,
    metadata: str | None,
    payload_json: str | None,
    json_mode: bool,
) -> None:
    """Edit a previously sent message by its bot_message_id.

    \b
      dailybot chat update <bot_message_id> -c C0123 -m "Status: DONE ✅"

    Buttons round-trip on update the same way as send. Note: the chat platform
    keeps the message's original bot name/avatar on an edit, so identity flags
    are ignored when updating. Re-send within 72h with the same bot_message_id.
    """
    profile_flag: str | None = ctx.obj.get("profile")
    client, repo_default_metadata = _resolved_client(profile_flag)
    payload: dict[str, Any] = _assemble_payload(
        payload_json=payload_json,
        metadata=metadata,
        repo_default_metadata=repo_default_metadata,
        bot_message_id=bot_message_id,
        json_mode=json_mode,
        text=text,
        users=list(users),
        channels=list(channels),
        teams=list(teams),
        image_url=image_url,
        link_buttons_raw=link_buttons_raw,
        action_buttons_raw=action_buttons_raw,
        buttons_json=buttons_json,
        approve_button_raw=approve_button_raw,
        reject_button_raw=reject_button_raw,
        callback_url=callback_url,
        callback_bearer=callback_bearer,
        workflow_buttons_raw=workflow_buttons_raw,
        thread=thread,
        channel_type=channel_type,
        bot_name=bot_name,
        bot_icon_url=bot_icon_url,
        bot_icon_emoji=bot_icon_emoji,
        ephemeral=ephemeral,
        skip_time_off=skip_time_off,
    )
    _send(client, payload, updated=True, json_mode=json_mode)
