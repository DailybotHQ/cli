"""Detection of how the current `dailybot` CLI was installed.

Used by both ``dailybot upgrade`` and ``dailybot uninstall`` so the two
commands stay in lock-step on what they call each method, where it lives
on disk, and which subset can be safely driven from inside a subprocess.

Design notes
------------

The heuristics here are *deliberately conservative*. We inspect the
on-disk path of the running ``dailybot_cli`` package and its parent
directories — never the package manager itself, never the network — so
the detection is fast, offline, and side-effect free. When a path
doesn't match any known shape, we fall back to ``"pip"`` because
``python -m pip install --upgrade`` / ``python -m pip uninstall`` are
always safe to attempt.

The module is intentionally small and free of external imports beyond
the stdlib, so command callbacks can use it without paying for any
heavier modules at import time.
"""

import sys
from pathlib import Path

PACKAGE: str = "dailybot-cli"

# Method tag → human-facing label. Keep the tag stable; callers branch
# on it. The label is for messages.
METHOD_LABELS: dict[str, str] = {
    "pipx": "pipx",
    "uv-tool": "uv tool",
    "pip": "pip",
    "homebrew": "Homebrew",
    "binary": "PyInstaller binary",
    "editable": "editable install (development)",
    "unknown": "unknown",
}


def resolve_install_path() -> Path:
    """Return the on-disk path of the running ``dailybot_cli`` package."""
    import dailybot_cli

    return Path(dailybot_cli.__file__).resolve().parent


def detect_install_method() -> str:
    """Best-effort detection of how this CLI was installed.

    Returns one of ``pipx``, ``uv-tool``, ``pip``, ``homebrew``,
    ``binary``, ``editable``, or ``unknown``.

    Heuristics inspect the install path's directory components only; in
    doubt, the function returns ``"pip"``, which is always a safe
    target for upgrade/uninstall.
    """
    # PyInstaller frozen build → can't trivially auto-replace itself.
    if getattr(sys, "frozen", False):
        return "binary"

    path: Path = resolve_install_path()
    parts_lower: list[str] = [p.lower() for p in path.parts]

    # Editable install: pyproject.toml lives next to the package source.
    if (path.parent / "pyproject.toml").exists():
        return "editable"

    # Homebrew formulas live under .../Cellar/<formula>/<version>/...
    if "cellar" in parts_lower and any("dailybot" in p for p in parts_lower):
        return "homebrew"

    # pipx isolated venvs live under .../pipx/venvs/<package>/...
    if "pipx" in parts_lower:
        return "pipx"

    # uv tool installs live under .../uv/tools/<package>/...
    if "uv" in parts_lower and "tools" in parts_lower:
        return "uv-tool"

    # Generic pip install (system, user-site, or a regular venv).
    return "pip"
