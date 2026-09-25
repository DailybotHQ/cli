"""Shared attachment flows for tasks, comments, projects and goals.

Four parents own an `attachments/` collection with the same row shape, so the
commands share one implementation of each step: read the local file under a
hard limit, upload, list, download to a path that is never overwritten by
surprise, and delete with a stated consequence. Each command supplies only the
client call for its parent.
"""

import contextlib
import mimetypes
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from dailybot_cli.api_client import APIError
from dailybot_cli.commands._destructive import confirm_without_preview
from dailybot_cli.commands.public_api_helpers import (
    EXIT_USAGE_ERROR,
    emit_json,
    exit_for_tasks_error,
    rows_of,
)
from dailybot_cli.display import console, print_error, print_success, print_tasks_rows

ATTACHMENT_COLUMNS: list[tuple[str, str, bool]] = [
    ("File", "filename", False),
    ("Type", "content_type", False),
    ("Bytes", "size", True),
    ("Status", "status", True),
    ("UUID", "uuid", True),
]
MIB: int = 1024 * 1024
DEFAULT_CONTENT_TYPE: str = "application/octet-stream"
# Downloaded files are created owner-writable, world-readable, like any saved file.
DOWNLOAD_FILE_MODE: int = 0o644


def guess_content_type(path: Path) -> str:
    """The file's MIME type from its name; `application/octet-stream` when unknown."""
    guessed, _encoding = mimetypes.guess_type(path.name)
    return guessed or DEFAULT_CONTENT_TYPE


def read_upload(file_path: Path, limit: int, *, where: str) -> bytes:
    """Read a file to upload, refusing an empty one or one over `limit` before any request.

    The file is read at most one byte past the limit, so a file that grows after
    the size check (a log still being written) is refused instead of read in full.
    """
    size: int = file_path.stat().st_size
    if size == 0:
        raise click.UsageError(f"{file_path.name} is empty; there is nothing to attach.")
    if size > limit:
        raise click.UsageError(
            f"{file_path.name} is {size / MIB:.1f} MiB; the limit {where} is "
            f"{limit // MIB} MiB. Nothing was uploaded."
        )
    with file_path.open("rb") as source:
        data: bytes = source.read(limit + 1)
    if len(data) > limit:
        raise click.UsageError(
            f"{file_path.name} grew past the {limit // MIB} MiB limit while it was being "
            "read. Nothing was uploaded."
        )
    return data


def run_attach(
    upload: Callable[..., dict[str, Any]],
    file_path: Path,
    *,
    caption: str | None,
    limit: int,
    where: str,
    json_mode: bool,
    require_auth: Callable[[], Any],
) -> None:
    """Upload one file through a single multipart request and report it.

    `upload(client, filename=, content_type=, data=, caption=)` is the parent's door.
    The file is checked before any credential is resolved.
    """
    data: bytes = read_upload(file_path, limit, where=where)
    client: Any = require_auth()
    try:
        with console.status("Uploading the file..."):
            result: dict[str, Any] = upload(
                client,
                filename=file_path.name,
                content_type=guess_content_type(file_path),
                data=data,
                caption=caption,
            )
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(result)
        return
    print_success(f"Attached {file_path.name} ({len(data)} bytes).")


def run_list(
    read: Callable[[Any], Any], *, json_mode: bool, require_auth: Callable[[], Any]
) -> None:
    """List attachments as a table, or the raw document under --json."""
    client: Any = require_auth()
    try:
        with console.status("Reading the attachments..."):
            data: Any = read(client)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json(data)
        return
    print_tasks_rows("Attachments", rows_of(data), ATTACHMENT_COLUMNS, empty="No attachments.")


def write_download(output: Path, content: bytes, *, force: bool, json_mode: bool) -> None:
    """Write downloaded bytes to `output` without surprises.

    Without --force the file is created exclusively and a symlink is never
    followed, so a file (or link) that appeared during the download is left alone.
    A path that cannot be written is an actionable error, not a crash.
    """
    flags: int = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    flags |= os.O_TRUNC if force else os.O_EXCL
    created: bool = False
    try:
        descriptor: int = os.open(output, flags, DOWNLOAD_FILE_MODE)
        created = not force
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise click.UsageError(
            f"{output} already exists. Pass --force to overwrite it. Nothing was written."
        ) from exc
    except OSError as exc:
        if created:
            # This call made the file, so a half-written one is ours to remove: left
            # behind, it would make the next attempt refuse without --force.
            with contextlib.suppress(OSError):
                os.unlink(output)
        message: str = f"Could not write {output}: {exc.strerror or exc}. Nothing was saved."
        if json_mode:
            emit_json(
                {
                    "status": "error",
                    "code": "output_not_writable",
                    "detail": str(exc),
                    "message": message,
                }
            )
        else:
            print_error(message)
        raise SystemExit(EXIT_USAGE_ERROR) from exc


def run_get(
    download: Callable[[Any], bytes],
    output: Path,
    *,
    attachment_uuid: str,
    force: bool,
    json_mode: bool,
    require_auth: Callable[[], Any],
) -> None:
    """Download one attachment to `output`. Never overwrites without --force."""
    if output.exists() and not force:
        raise click.UsageError(f"{output} already exists. Pass --force to overwrite it.")
    client: Any = require_auth()
    try:
        with console.status("Downloading..."):
            content: bytes = download(client)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    write_download(output, content, force=force, json_mode=json_mode)
    if json_mode:
        emit_json({"path": str(output), "bytes": len(content), "attachment": attachment_uuid})
        return
    print_success(f"Saved {len(content)} bytes to {output}.")


def run_delete(
    delete: Callable[[Any], Any],
    consequence: str,
    *,
    receipt: dict[str, Any],
    dry_run: bool,
    assume_yes: bool,
    json_mode: bool,
    require_auth: Callable[[], Any],
) -> None:
    """Delete one attachment after stating the act. Its `--dry-run` sends nothing.

    `require_auth` runs only after the confirmation, so a dry run needs no
    credential and spends no request.
    """
    if not confirm_without_preview(
        consequence, assume_yes=assume_yes, dry_run=dry_run, json_mode=json_mode
    ):
        return
    client: Any = require_auth()
    try:
        with console.status("Deleting the attachment..."):
            delete(client)
    except APIError as exc:
        exit_for_tasks_error(exc, json_mode)
    if json_mode:
        emit_json({"deleted": True, **receipt})
        return
    print_success("Attachment deleted.")
