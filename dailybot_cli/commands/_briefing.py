"""The task briefing: one call that gives an agent the whole card.

One read of the task with its collections embedded (first page each); a
collection whose embed says there is more is completed from its own door, and
a server that returns no embeds falls back to those doors entirely. An agent
opening a task link does not have to know the doors. Everything a person
wrote on the card is untrusted data: the briefing says so in its own payload,
and attachment names never choose where a file lands.
"""

import re
import unicodedata
from pathlib import Path
from typing import Any

from dailybot_cli.api_client import TASKS_PATH_SEGMENT_RE, PaginatedResult
from dailybot_cli.commands._attachments import write_download
from dailybot_cli.commands.public_api_helpers import rows_of

# Comments read into one briefing. A card with more is summarized by its
# newest-first page and the total, which the briefing reports.
BRIEF_COMMENT_LIMIT: int = 200
# Longest saved file name in UTF-8 bytes, before the uuid prefix: the prefix
# plus this stays under the common 255-byte filesystem limit for any script.
MAX_SAVED_NAME_BYTES: int = 200
# Characters Windows refuses in a file name (and `:` would open an NTFS stream).
_WINDOWS_RESERVED_RE: re.Pattern[str] = re.compile(r'[<>:"|?*]')
FALLBACK_ATTACHMENT_NAME: str = "attachment"
# Attachments still uploading, or failed, have no bytes to fetch.
UNFETCHABLE_ATTACHMENT_STATUSES: frozenset[str] = frozenset({"pending", "failed"})
_UNSAFE_NAME_CHARS_RE: re.Pattern[str] = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _embedded(task: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Pop one embed off the task, as an envelope, or ``None`` when it is absent."""
    value: Any = task.pop(name, None)
    if isinstance(value, list):
        return {"count": len(value), "next": None, "results": value}
    return value if isinstance(value, dict) else None


def build_briefing(client: Any, task_ref: str) -> dict[str, Any]:
    """Read the whole card behind a task key or uuid."""
    task: dict[str, Any] = dict(client.get_task_briefing(task_ref))
    task_uuid: str = str(task.get("uuid") or task_ref)

    comments_env: dict[str, Any] | None = _embedded(task, "comments")
    if comments_env is None or comments_env.get("next"):
        page: PaginatedResult = client.list_task_comments(
            task_uuid, fetch_all=True, limit=BRIEF_COMMENT_LIMIT
        )
        comments: list[dict[str, Any]] = page.results
        comments_total: Any = page.count
    else:
        comments = rows_of(comments_env)
        comments_total = comments_env.get("count", len(comments))

    attachments_env: dict[str, Any] | None = _embedded(task, "attachments")
    if attachments_env is None or attachments_env.get("next"):
        attachments: list[dict[str, Any]] = rows_of(client.list_task_attachments(task_uuid))
    else:
        attachments = rows_of(attachments_env)

    relations_env: dict[str, Any] | None = _embedded(task, "relations")
    if relations_env is None or relations_env.get("next"):
        relations: list[dict[str, Any]] = rows_of(client.list_task_relations(task_uuid))
    else:
        relations = rows_of(relations_env)

    brief: dict[str, Any] = {
        "task": task,
        "comments": comments,
        "comments_total": comments_total,
        "attachments": attachments,
        "relations": relations,
    }
    # First pages only: enough to orient; the dedicated commands page the rest.
    for name in ("participants", "activity", "children"):
        env: dict[str, Any] | None = _embedded(task, name)
        if env is not None:
            brief[name] = rows_of(env)
            brief[f"{name}_has_more"] = bool(env.get("next"))
    # Every text field above was written by people. It is data to analyze,
    # never an instruction to follow.
    brief["untrusted_content"] = True
    return brief


def _truncate_utf8(text: str, limit: int) -> str:
    """Cut `text` to at most `limit` UTF-8 bytes without splitting a character."""
    return text.encode("utf-8")[:limit].decode("utf-8", "ignore")


def safe_attachment_filename(attachment: dict[str, Any]) -> str:
    """A local file name for an attachment that cannot escape its directory.

    The server-provided name is untrusted: only its last path component is
    kept (for `/` and `\\` alike), control characters and leading dots go, and
    the attachment's uuid prefix keeps two files with the same name apart.
    """
    raw: str = str(attachment.get("filename") or "")
    base: str = re.split(r"[\\/]", raw)[-1]
    base = _UNSAFE_NAME_CHARS_RE.sub("", base)
    # Format characters (a right-to-left override can fake the extension).
    base = "".join(ch for ch in base if unicodedata.category(ch) != "Cf")
    base = _WINDOWS_RESERVED_RE.sub("_", base).strip().lstrip(".").strip().rstrip(".")
    base = _truncate_utf8(base, MAX_SAVED_NAME_BYTES) or FALLBACK_ATTACHMENT_NAME
    # The uuid is server data too: keep only its safe characters.
    prefix: str = re.sub(r"[^0-9A-Za-z-]", "", str(attachment.get("uuid") or ""))[:8]
    return f"{prefix}-{base}" if prefix else base


def download_attachments(
    client: Any,
    task_uuid: str,
    attachments: list[dict[str, Any]],
    directory: Path,
    *,
    force: bool,
    json_mode: bool,
) -> list[dict[str, Any]]:
    """Save every fetchable attachment into `directory`; never overwrite without `force`.

    Attachments that are not fetchable, or whose name would not land inside
    `directory`, are reported with a `skipped` reason instead of dropped.
    """
    directory.mkdir(parents=True, exist_ok=True)
    root: Path = directory.resolve()
    saved: list[dict[str, Any]] = []
    for attachment in attachments:
        attachment_uuid: str = str(attachment.get("uuid") or "")
        if not attachment_uuid:
            continue
        if not TASKS_PATH_SEGMENT_RE.fullmatch(attachment_uuid):
            # Not a key or uuid the API could serve: never saved under a guessed name.
            saved.append(
                {"attachment": attachment_uuid, "status": "skipped", "reason": "invalid id"}
            )
            continue
        status: str = str(attachment.get("status") or "").lower()
        if status in UNFETCHABLE_ATTACHMENT_STATUSES:
            saved.append(
                {"attachment": attachment_uuid, "status": "skipped", "reason": f"status {status}"}
            )
            continue
        output: Path = root / safe_attachment_filename(attachment)
        if output.parent != root:
            saved.append(
                {"attachment": attachment_uuid, "status": "skipped", "reason": "unsafe name"}
            )
            continue
        content: bytes = client.download_attachment(task_uuid, attachment_uuid)
        write_download(output, content, force=force, json_mode=json_mode)
        saved.append(
            {
                "attachment": attachment_uuid,
                "status": "saved",
                "path": str(output),
                "bytes": len(content),
            }
        )
    return saved
