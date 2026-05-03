"""`dailybot upgrade` subcommand — self-update the installed CLI.

Auto-detects the installation method (pipx / uv tool / pip / Homebrew /
PyInstaller binary / editable) and either:

  - runs the right upgrade command in a subprocess (pipx / uv / pip), or
  - prints the command the user should run themselves (Homebrew / binary /
    editable installs, where invoking the package manager from inside the
    CLI is risky — sudo prompts, locks, dev iteration).

The command is intentionally honest about what it can and cannot do
automatically. Mirrors the design of `bun upgrade` / `deno upgrade` /
`oh-my-posh upgrade` for cases the CLI controls, and falls back to a
"copy this command" hint everywhere else.
"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path

import click

from dailybot_cli import __version__
from dailybot_cli.commands.version import _fetch_latest_pypi_version
from dailybot_cli.display import (
    print_error,
    print_info,
    print_success,
    print_warning,
)
from dailybot_cli.install_method import (
    METHOD_LABELS as _METHOD_LABELS,
    PACKAGE as _PACKAGE,
    detect_install_method as _detect_install_method,
    resolve_install_path as _resolve_install_path,
)


def _build_upgrade_argv(method: str) -> list[str] | None:
    """Return argv for `subprocess.run` to perform the upgrade, or None.

    `None` means "we don't auto-run for this method — print the command
    instead". `homebrew`, `binary`, `editable`, and `unknown` fall in
    that category for safety reasons documented above.
    """
    if method == "pipx":
        # `pipx` itself drives the venv — no need to find it manually.
        if shutil.which("pipx"):
            return ["pipx", "upgrade", _PACKAGE]
        # pipx not on PATH but maybe the package was installed via
        # `python -m pipx`. Try that as a fallback.
        return [sys.executable, "-m", "pipx", "upgrade", _PACKAGE]

    if method == "uv-tool":
        if shutil.which("uv"):
            return ["uv", "tool", "upgrade", _PACKAGE]
        return None  # uv not findable — bail to "manual" path

    if method == "pip":
        # Use the same Python that's running the CLI. Reliable across venvs.
        return [sys.executable, "-m", "pip", "install", "--upgrade", _PACKAGE]

    return None  # homebrew, binary, editable, unknown


def _manual_command_hint(method: str) -> str:
    """Human-readable upgrade command for methods we don't auto-run."""
    if method == "homebrew":
        return "brew update && brew upgrade dailybot"
    if method == "binary":
        if platform.system() == "Windows":
            return "irm https://cli.dailybot.com/install.ps1 | iex"
        return "curl -sSL https://cli.dailybot.com/install.sh | bash"
    if method == "editable":
        return "git pull  # then 'pip install -e .' if dependencies changed"
    if method == "uv-tool":
        return "uv tool upgrade dailybot-cli"
    return f"pip install --upgrade {_PACKAGE}"


def _print_status(current: str, latest: str | None) -> None:
    """Print the version status header common to all paths."""
    print_info(f"Current version: {current}")
    if latest is None:
        print_warning("Could not reach PyPI to check for the latest version.")
        return
    if latest == current:
        print_info(f"Latest version:  {latest}")
        return
    print_info(f"Latest version:  {latest}  (update available)")


@click.command(name="upgrade")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print the upgrade command but do not execute it.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Run the upgrade even when already on the latest version.",
)
def upgrade(dry_run: bool, force: bool) -> None:
    """Upgrade the Dailybot CLI to the latest version on PyPI.

    \b
    Auto-detects how the CLI was installed and runs the right upgrade
    command. For installs managed by an external tool (Homebrew, the
    Linux/Windows binary installers, editable dev installs), the command
    you should run is printed instead — running those automatically is
    risky (sudo prompts, file locks, dev iteration).

    \b
    Examples:
      dailybot upgrade           # check + upgrade if newer is available
      dailybot upgrade --dry-run # show what would happen, do nothing
      dailybot upgrade --force   # reinstall even if already latest
    """
    print_info("Checking PyPI for the latest version...")
    latest: str | None = _fetch_latest_pypi_version()
    _print_status(current=__version__, latest=latest)

    if latest == __version__ and not force:
        print_success("You're already on the latest version. Nothing to do.")
        return

    method: str = _detect_install_method()
    label: str = _METHOD_LABELS.get(method, method)
    install_path: Path = _resolve_install_path()
    print_info(f"Install method:  {label}  ({install_path})")

    if method == "editable":
        print_warning(
            "This is an editable (development) install. "
            "Refusing to auto-upgrade — manage it with git instead:"
        )
        click.echo(f"\n  {_manual_command_hint(method)}\n")
        return

    argv: list[str] | None = _build_upgrade_argv(method)

    if argv is None:
        # Methods we don't auto-run: homebrew, binary, uv-tool-not-found, unknown.
        print_warning(
            f"This is a {label} install. We don't run the package manager "
            "automatically; run this command yourself:"
        )
        click.echo(f"\n  {_manual_command_hint(method)}\n")
        return

    pretty_cmd: str = " ".join(argv)
    if dry_run:
        click.echo(f"\nWould run: {pretty_cmd}\n")
        return

    print_info(f"Running: {pretty_cmd}")
    click.echo()  # blank line so the subprocess output is easy to scan
    try:
        subprocess.run(argv, check=True)
    except subprocess.CalledProcessError as exc:
        print_error(
            f"Upgrade command failed with exit code {exc.returncode}. "
            f"You can try running it manually:\n  {pretty_cmd}"
        )
        raise SystemExit(exc.returncode)
    except FileNotFoundError:
        print_error(
            f"Could not find the executable for {label}. "
            f"Try the manual command:\n  {_manual_command_hint(method)}"
        )
        raise SystemExit(1)

    click.echo()
    print_success("Upgrade complete. Run 'dailybot --version' to confirm.")
