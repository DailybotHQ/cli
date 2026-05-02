"""`dailybot version` subcommand — show install info, optionally check PyPI."""

import platform
import sys
from pathlib import Path

import click
import httpx

from dailybot_cli import __version__
from dailybot_cli.display import print_info, print_version_info, print_warning

# How long to wait for PyPI when --check is used. Kept short so an offline user
# isn't blocked by a slow timeout — the CLI still prints local info.
_PYPI_TIMEOUT_SECS: float = 3.0
_PYPI_URL: str = "https://pypi.org/pypi/dailybot-cli/json"


def _resolve_install_path() -> str:
    """Return a user-friendly path describing where the CLI lives.

    For normal Python installs (pip / pipx / Homebrew / editable), this is the
    directory of the running `dailybot_cli` package. For the PyInstaller-built
    Linux binary, the package source lives in an ephemeral `/tmp/_MEIxxxxxx/`
    extraction dir that is meaningless to the user — we surface the binary
    path itself in that case so the value is actionable.
    """
    # PyInstaller sets `sys.frozen = True` and `sys._MEIPASS` to the temp dir
    # where it extracted the bundle. Prefer the executable path the user
    # invoked.
    if getattr(sys, "frozen", False):
        return f"{sys.executable}  (PyInstaller bundle)"

    import dailybot_cli

    return str(Path(dailybot_cli.__file__).resolve().parent)


def _fetch_latest_pypi_version() -> str | None:
    """Query PyPI for the latest released version. Return ``None`` on any error.

    Errors are swallowed on purpose: a missing network or an outage on PyPI
    must never break ``dailybot version``. Callers should treat ``None`` as
    "couldn't check" and degrade gracefully.
    """
    try:
        response: httpx.Response = httpx.get(_PYPI_URL, timeout=_PYPI_TIMEOUT_SECS)
        if response.status_code != 200:
            return None
        info: dict = response.json().get("info", {})
        latest: str | None = info.get("version")
        return latest
    except (httpx.HTTPError, ValueError):
        return None


@click.command(name="version")
@click.option(
    "--check",
    "-c",
    is_flag=True,
    default=False,
    help="Also query PyPI for the latest released version.",
)
def version(check: bool) -> None:
    """Show the installed CLI version, Python runtime, and install path.

    \b
      dailybot version           # Local info only (no network)
      dailybot version --check   # Same, plus a PyPI lookup for updates
    """
    install_path: str = _resolve_install_path()
    python_version: str = platform.python_version()

    latest: str | None = None
    if check:
        print_info("Checking PyPI for latest version...")
        latest = _fetch_latest_pypi_version()
        if latest is None:
            print_warning(
                "Could not reach PyPI (network error or timeout). Showing local info only."
            )

    print_version_info(
        version=__version__,
        python_version=python_version,
        install_path=install_path,
        latest_version=latest,
    )
