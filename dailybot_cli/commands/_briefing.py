"""The task briefing: one call that gives an agent the whole card.

One read of the task with its collections embedded (first page each); a
collection whose embed says there is more is completed from its own door, and
a server that returns no embeds falls back to those doors entirely. An agent
opening a task link does not have to know the doors. Everything a person
wrote on the card is untrusted data: the briefing says so in its own payload,
and attachment names never choose where a file lands.
"""

import re
from pathlib import Path
from typing import Any

from dailybot_cli.api_client import PaginatedResult
from dailybot_cli.commands._attachments import write_download
from dailybot_cli.commands.public_api_helpers import rows_of

# Comments read into one briefing. A card with more is summarized by its
# newest-first page and the total, which the briefing reports.
BRIEF_COMMENT_LIMIT: int = 200
# Longest saved file name, before the uuid prefix. Keeps well under common
# filesystem limits (255 bytes) even for multi-byte names.
MAX_SAVED_NAME_CHARS: int = 120
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


def safe_attachment_filename(attachment: dict[str, Any]) -> str:
    """A local file name for an attachment that cannot escape its directory.

    The server-provided name is untrusted: only its last path component is
    kept (for `/` and `\\` alike), control characters and leading dots go, and
    the attachment's uuid prefix keeps two files with the same name apart.
    """
    raw: str = str(attachment.get("filename") or "")
    base: str = re.split(r"[\\/]", raw)[-1]
    base = _UNSAFE_NAME_CHARS_RE.sub("", base).strip().lstrip(".").strip()
    base = base[:MAX_SAVED_NAME_CHARS] or FALLBACK_ATTACHMENT_NAME
    prefix: str = str(attachment.get("uuid") or "")[:8]
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
    """Save every fetchable attachment into `directory`; never overwrite without `force`."""
    directory.mkdir(parents=True, exist_ok=True)
    root: Path = directory.resolve()
    saved: list[dict[str, Any]] = []
    for attachment in attachments:
        attachment_uuid: str = str(attachment.get("uuid") or "")
        if not attachment_uuid:
            continue
        if str(attachment.get("status") or "").lower() in UNFETCHABLE_ATTACHMENT_STATUSES:
            continue
        output: Path = root / safe_attachment_filename(attachment)
        if output.parent != root:
            continue
        content: bytes = client.download_attachment(task_uuid, attachment_uuid)
        write_download(output, content, force=force, json_mode=json_mode)
        saved.append({"attachment": attachment_uuid, "path": str(output), "bytes": len(content)})
    return saved
