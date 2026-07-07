"""Local report ledger backing the `dailybot hook` lifecycle commands.

Tracks, per repository, when the last agent report was sent and which work
signals (commits, file activity, agent turns) have accumulated since. Agent
harness hooks call into this module on every lifecycle event to decide
whether the model should be reminded to send a progress report.

Design constraints:

- **No network access.** These functions run inside lifecycle hooks that fire
  on every agent turn — they must complete in milliseconds and never depend
  on the Dailybot API being reachable.
- **Best-effort.** Any internal failure degrades to "no nudge", never to an
  error that could break the developer's agent session.
- **Recoverable cache, not a database.** Git history is the source of truth
  for commit signals; losing a ledger file costs at most one extra or one
  missed reminder.

Files live under ``<config dir>/ledger/`` (one JSON file per repository plus
``_global.json`` for cross-repo state) with owner-only permissions, following
the same conventions as the rest of ``~/.config/dailybot/``.
"""

import contextlib
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dailybot_cli.config import find_repo_profile_path, get_agent_auth, get_config_dir

LEDGER_DIRNAME: str = "ledger"
GLOBAL_STATE_FILENAME: str = "_global.json"

# Nudge policy defaults. `min_interval_minutes` is overridable per repo via
# the `report` block in `.dailybot/profile.json`.
DEFAULT_MIN_INTERVAL_MINUTES: int = 30
DEFAULT_CONTINUOUS_MIN_INTERVAL_MINUTES: int = 20
NUDGE_COOLDOWN_MINUTES: int = 15
DEFAULT_SNOOZE_MINUTES: int = 60
SOFT_NUDGE_TURN_THRESHOLD: int = 8
DEFAULT_CONTINUOUS_SOFT_TURN_THRESHOLD: int = 5
VALID_REPORT_MODES: frozenset[str] = frozenset({"balanced", "continuous"})
LOGIN_NUDGE_INTERVAL_HOURS: int = 24
GIT_TIMEOUT_SECS: float = 5.0

_SLUG_UNSAFE_RE: re.Pattern[str] = re.compile(r"[^A-Za-z0-9._-]")
_LOCAL_HASH_LENGTH: int = 8


def _now() -> datetime:
    """Current UTC time. Module-level so tests can freeze the clock."""
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed: datetime = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


# --- Git helpers ---


def _run_git(args: list[str], cwd: Path) -> str | None:
    """Run a git command; return stripped stdout or None on any failure."""
    try:
        proc: subprocess.CompletedProcess[str] = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _git_head(cwd: Path) -> str | None:
    return _run_git(["rev-parse", "HEAD"], cwd)


def _normalize_remote(remote: str) -> str:
    """Normalize a git remote URL to a stable `host/owner/name` identity."""
    identity: str = remote.strip()
    identity = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", identity)  # scheme
    identity = re.sub(r"^[^@/]+@", "", identity)  # user@
    identity = identity.replace(":", "/")
    identity = re.sub(r"\.git$", "", identity)
    return identity.strip("/")


def _sanitize(fragment: str) -> str:
    return _SLUG_UNSAFE_RE.sub("_", fragment)


def repo_slug(cwd: Path | None = None) -> str | None:
    """Stable per-repository ledger key, or None outside a git work tree.

    Derived from the `origin` remote when present (so all clones of a repo
    share one ledger entry), falling back to the repo root name plus a short
    path hash for remote-less repos.
    """
    base: Path = cwd or Path.cwd()
    root: str | None = _run_git(["rev-parse", "--show-toplevel"], base)
    if not root:
        return None
    remote: str | None = _run_git(["remote", "get-url", "origin"], base)
    if remote:
        return _sanitize(_normalize_remote(remote).replace("/", "__"))
    root_path: Path = Path(root)
    digest: str = hashlib.sha1(str(root_path).encode()).hexdigest()[:_LOCAL_HASH_LENGTH]
    return f"local__{_sanitize(root_path.name)}__{digest}"


def _repo_identity(cwd: Path) -> str | None:
    """Human-readable repo identity stored inside the ledger entry."""
    remote: str | None = _run_git(["remote", "get-url", "origin"], cwd)
    if remote:
        return _normalize_remote(remote)
    root: str | None = _run_git(["rev-parse", "--show-toplevel"], cwd)
    return Path(root).name if root else None


def is_disabled(cwd: Path | None = None) -> bool:
    """True when `.dailybot/disabled` exists in *cwd* or any ancestor."""
    start: Path = (cwd or Path.cwd()).resolve()
    for ancestor in [start, *start.parents]:
        if (ancestor / ".dailybot" / "disabled").is_file():
            return True
    return False


# --- Entry storage ---


def get_ledger_dir() -> Path:
    """Return the ledger directory, creating it with owner-only access."""
    path: Path = get_config_dir() / LEDGER_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _entry_path(slug: str) -> Path:
    return get_ledger_dir() / f"{slug}.json"


def _default_entry(repo_identity: str | None = None) -> dict[str, Any]:
    return {
        "repo": repo_identity,
        "first_seen_at": None,
        "last_report_at": None,
        "last_reported_commit": None,
        "last_nudge_at": None,
        "last_activity_at": None,
        "work_pending": False,
        "snoozed_until": None,
        "turns_since_report": 0,
        "reported_by": None,
    }


def load_entry(slug: str) -> dict[str, Any]:
    """Load a ledger entry, returning defaults when missing or corrupt."""
    entry: dict[str, Any] = _default_entry()
    path: Path = _entry_path(slug)
    if not path.exists():
        return entry
    try:
        data: Any = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return entry
    if isinstance(data, dict):
        entry.update(data)
    return entry


def save_entry(slug: str, entry: dict[str, Any]) -> None:
    """Atomically persist a ledger entry with owner-only permissions."""
    _atomic_write_json(_entry_path(slug), entry)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    fd: int
    tmp_name: str
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _load_global_state() -> dict[str, Any]:
    path: Path = get_ledger_dir() / GLOBAL_STATE_FILENAME
    if not path.exists():
        return {}
    try:
        data: Any = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_global_state(data: dict[str, Any]) -> None:
    _atomic_write_json(get_ledger_dir() / GLOBAL_STATE_FILENAME, data)


# --- Repo report policy (.dailybot/profile.json `report` block) ---


def _repo_policy(cwd: Path) -> dict[str, Any]:
    """Read the optional `report` policy from the repo profile, silently."""
    policy: dict[str, Any] = {
        "min_interval_minutes": DEFAULT_MIN_INTERVAL_MINUTES,
        "nudge": True,
        "mode": "balanced",
        "soft_turn_threshold": SOFT_NUDGE_TURN_THRESHOLD,
    }
    path: Path | None = find_repo_profile_path(cwd)
    if not path:
        return policy
    try:
        data: Any = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return policy
    report: Any = data.get("report") if isinstance(data, dict) else None
    if not isinstance(report, dict):
        return policy
    if isinstance(report.get("nudge"), bool):
        policy["nudge"] = report["nudge"]
    mode_raw: Any = report.get("mode")
    if isinstance(mode_raw, str) and mode_raw in VALID_REPORT_MODES:
        policy["mode"] = mode_raw
    interval_explicit: bool = False
    interval: Any = report.get("min_interval_minutes")
    if isinstance(interval, int) and not isinstance(interval, bool) and interval > 0:
        policy["min_interval_minutes"] = interval
        interval_explicit = True
    threshold_explicit: bool = False
    threshold: Any = report.get("soft_turn_threshold")
    if isinstance(threshold, int) and not isinstance(threshold, bool) and threshold > 0:
        policy["soft_turn_threshold"] = threshold
        threshold_explicit = True
    if policy["mode"] == "continuous":
        if not interval_explicit:
            policy["min_interval_minutes"] = DEFAULT_CONTINUOUS_MIN_INTERVAL_MINUTES
        if not threshold_explicit:
            policy["soft_turn_threshold"] = DEFAULT_CONTINUOUS_SOFT_TURN_THRESHOLD
    return policy


# --- Signal recording ---


def _ensure_entry(slug: str, cwd: Path, baseline_parent: bool = False) -> dict[str, Any]:
    """Load the entry, initializing the commit baseline on first sight.

    The baseline prevents nudging about history that predates the ledger.
    `baseline_parent=True` (used by post-commit) anchors at HEAD~1 so the
    commit that triggered the hook still counts as unreported.
    """
    if _entry_path(slug).exists():
        return load_entry(slug)
    entry: dict[str, Any] = _default_entry(_repo_identity(cwd))
    entry["first_seen_at"] = _iso(_now())
    if baseline_parent:
        entry["last_reported_commit"] = _run_git(["rev-parse", "HEAD~1"], cwd)
    else:
        entry["last_reported_commit"] = _git_head(cwd)
    return entry


def record_commit(cwd: Path | None = None) -> None:
    """Record a commit signal (strong evidence of completed work)."""
    base: Path = cwd or Path.cwd()
    slug: str | None = repo_slug(base)
    if not slug:
        return
    entry: dict[str, Any] = _ensure_entry(slug, base, baseline_parent=True)
    entry["work_pending"] = True
    entry["last_activity_at"] = _iso(_now())
    save_entry(slug, entry)


def record_activity(cwd: Path | None = None) -> None:
    """Record an activity signal (file edits — work that may lack commits)."""
    base: Path = cwd or Path.cwd()
    slug: str | None = repo_slug(base)
    if not slug:
        return
    entry: dict[str, Any] = _ensure_entry(slug, base)
    entry["work_pending"] = True
    entry["last_activity_at"] = _iso(_now())
    save_entry(slug, entry)


def dismiss(cwd: Path | None = None, minutes: int = DEFAULT_SNOOZE_MINUTES) -> None:
    """Snooze reminders for *minutes* (the model judged nothing significant)."""
    base: Path = cwd or Path.cwd()
    slug: str | None = repo_slug(base)
    if not slug:
        return
    entry: dict[str, Any] = _ensure_entry(slug, base)
    entry["snoozed_until"] = _iso(_now() + timedelta(minutes=minutes))
    entry["work_pending"] = False
    entry["turns_since_report"] = 0
    save_entry(slug, entry)


def mark_reported(cwd: Path | None = None, reported_by: str | None = None) -> None:
    """Reset all signals after a successful `dailybot agent update`."""
    base: Path = cwd or Path.cwd()
    slug: str | None = repo_slug(base)
    if not slug:
        return
    entry: dict[str, Any] = _ensure_entry(slug, base)
    entry["last_report_at"] = _iso(_now())
    entry["last_reported_commit"] = _git_head(base)
    entry["work_pending"] = False
    entry["snoozed_until"] = None
    entry["turns_since_report"] = 0
    if reported_by:
        entry["reported_by"] = reported_by
    save_entry(slug, entry)


# --- Nudge decisions ---


def _unreported_commit_count(cwd: Path, entry: dict[str, Any]) -> int:
    """Count commits since the last report; git is the source of truth."""
    sha: Any = entry.get("last_reported_commit")
    if sha:
        out: str | None = _run_git(["rev-list", "--count", f"{sha}..HEAD"], cwd)
        if out is not None and out.isdigit():
            return int(out)
    # Baseline sha missing or gone (rebase, gc) — fall back to the timestamp.
    report_at: Any = entry.get("last_report_at")
    if report_at:
        out = _run_git(["rev-list", "--count", "HEAD", f"--since={report_at}"], cwd)
        if out is not None and out.isdigit():
            return int(out)
    return 0


def evaluate_stop(cwd: Path | None = None) -> dict[str, Any] | None:
    """Decide whether the end-of-turn hook should remind the model to report.

    Returns ``{"kind": "commits", "commit_count": N}`` when unreported
    commits exist, ``{"kind": "soft", "commit_count": 0}`` when there is
    sustained non-commit work (file activity or many turns), or ``None``
    when the hook should stay silent. Every call counts as one agent turn.
    """
    base: Path = cwd or Path.cwd()
    if is_disabled(base):
        return None
    slug: str | None = repo_slug(base)
    if not slug:
        return None
    policy: dict[str, Any] = _repo_policy(base)
    if not policy["nudge"]:
        return None

    first_sight: bool = not _entry_path(slug).exists()
    entry: dict[str, Any] = _ensure_entry(slug, base)
    entry["turns_since_report"] = int(entry.get("turns_since_report") or 0) + 1
    if first_sight:
        # Never nudge on the very first turn we see a repo — the baseline
        # was just initialized and pre-existing history is not "unreported".
        save_entry(slug, entry)
        return None

    now: datetime = _now()
    interval: timedelta = timedelta(minutes=policy["min_interval_minutes"])
    snoozed_until: datetime | None = _parse_iso(entry.get("snoozed_until"))
    last_nudge_at: datetime | None = _parse_iso(entry.get("last_nudge_at"))
    last_report_at: datetime | None = _parse_iso(entry.get("last_report_at"))

    decision: dict[str, Any] | None = None
    if snoozed_until and now < snoozed_until:
        pass  # dismissed by the model — stay silent until the snooze expires
    elif last_nudge_at and now - last_nudge_at < timedelta(minutes=NUDGE_COOLDOWN_MINUTES):
        pass  # nudged recently — don't nag every turn
    elif last_report_at and now - last_report_at < interval:
        pass  # reported recently — aggregation beats back-to-back reports
    else:
        commits: int = _unreported_commit_count(base, entry)
        if commits > 0:
            decision = {"kind": "commits", "commit_count": commits}
        else:
            anchor: datetime | None = last_report_at or _parse_iso(entry.get("first_seen_at"))
            interval_ok: bool = anchor is None or now - anchor >= interval
            turn_threshold: int = int(policy.get("soft_turn_threshold") or SOFT_NUDGE_TURN_THRESHOLD)
            has_soft_signal: bool = bool(entry.get("work_pending")) or (
                entry["turns_since_report"] >= turn_threshold
            )
            if interval_ok and has_soft_signal:
                decision = {"kind": "soft", "commit_count": 0}

    if decision:
        entry["last_nudge_at"] = _iso(now)
    save_entry(slug, entry)
    return decision


def evaluate_session_start(cwd: Path | None = None) -> dict[str, Any] | None:
    """Decide what context the session-start hook should inject.

    Returns ``{"login_needed": bool, "unreported_commit_count": int,
    "work_pending": bool}`` or ``None`` when there is nothing to say. The
    login nudge is rate-limited globally to once per
    ``LOGIN_NUDGE_INTERVAL_HOURS``.
    """
    base: Path = cwd or Path.cwd()
    if is_disabled(base):
        return None

    login_needed: bool = False
    if get_agent_auth() is None:
        state: dict[str, Any] = _load_global_state()
        last_nudge: datetime | None = _parse_iso(state.get("last_login_nudge_at"))
        now: datetime = _now()
        if last_nudge is None or now - last_nudge >= timedelta(hours=LOGIN_NUDGE_INTERVAL_HOURS):
            login_needed = True
            state["last_login_nudge_at"] = _iso(now)
            _save_global_state(state)

    unreported: int = 0
    work_pending: bool = False
    slug: str | None = repo_slug(base)
    if slug and _entry_path(slug).exists():
        entry: dict[str, Any] = load_entry(slug)
        unreported = _unreported_commit_count(base, entry)
        work_pending = bool(entry.get("work_pending"))

    if not login_needed and unreported == 0 and not work_pending:
        return None
    return {
        "login_needed": login_needed,
        "unreported_commit_count": unreported,
        "work_pending": work_pending,
    }
