"""``dailybot uninstall`` subcommand — remove the installed CLI.

Mirrors :mod:`dailybot_cli.commands.upgrade`: auto-detects the
installation method and either runs the right uninstall command in a
subprocess (pipx / uv tool / pip) or prints the command the user
should run themselves (Homebrew / PyInstaller binary / editable
install).

Best-practice notes
-------------------

This command is *destructive*, so the UX has to be deliberately
conservative:

  - Confirmation prompt by default. ``--yes`` / ``-y`` skips it for
    scripted usage.
  - ``--dry-run`` prints what would happen without doing anything.
  - ``~/.config/dailybot/`` is **preserved** by default — credentials
    and agent profiles are easy to lose by accident. ``--purge``
    opts in to removing the whole config directory.
  - Methods that imply a package manager we don't own (``homebrew``,
    ``binary``, ``editable``) print a manual command rather than
    invoking ``brew``, ``rm``, or ``git`` automatically — same
    safety stance ``upgrade`` takes.

Pattern alignment
-----------------

Follows the five-step CLI pattern from
``docs/CLI_COMMAND_BEST_PRACTICES.md``:

  1. Validate flags (mutually exclusive ``--dry-run`` + ``--yes``
     would be confusing — we let ``--dry-run`` win silently).
  2. Resolve detection context (install method + path).
  3. Confirm.
  4. Execute (subprocess for managed installs; print-only for the
     rest).
  5. Render result via ``display.py`` helpers.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import click

from dailybot_cli.config import CONFIG_DIR
from dailybot_cli.display import (
    print_error,
    print_info,
    print_success,
    print_warning,
)
from dailybot_cli.install_method import (
    METHOD_LABELS,
    PACKAGE,
    detect_install_method,
    resolve_install_path,
)


def _build_uninstall_argv(method: str) -> list[str] | None:
    """Return argv for ``subprocess.run`` to perform the uninstall, or ``None``.

    ``None`` signals "we don't auto-run for this method — print the
    command instead". Same safety reasoning as
    :func:`dailybot_cli.commands.upgrade._build_upgrade_argv`.
    """
    if method == "pipx":
        if shutil.which("pipx"):
            return ["pipx", "uninstall", PACKAGE]
        return [sys.executable, "-m", "pipx", "uninstall", PACKAGE]

    if method == "uv-tool":
        if shutil.which("uv"):
            return ["uv", "tool", "uninstall", PACKAGE]
        return None

    if method == "pip":
        # ``pip uninstall`` itself prompts for confirmation — ``-y`` here
        # is pip's own flag, not the user-facing one. Our own confirmation
        # has already happened by the time we get here.
        return [sys.executable, "-m", "pip", "uninstall", "-y", PACKAGE]

    return None  # homebrew, binary, editable, unknown


def _manual_command_hint(method: str, install_path: Path) -> str:
    """Human-readable uninstall command for methods we don't auto-run."""
    if method == "homebrew":
        return "brew uninstall dailybothq/tap/dailybot"
    if method == "binary":
        # Best-effort: the running argv[0] is the canonical binary path
        # if we're a frozen build. Fall back to the resolved package path.
        binary_path: str = sys.argv[0] if getattr(sys, "frozen", False) else str(install_path)
        return f"rm {binary_path}"
    if method == "editable":
        return f"{sys.executable} -m pip uninstall {PACKAGE}  # then remove the source clone"
    if method == "uv-tool":
        return f"uv tool uninstall {PACKAGE}"
    return f"{sys.executable} -m pip uninstall {PACKAGE}"


def _purge_config_dir() -> Path | None:
    """Remove ``~/.config/dailybot/`` if it exists. Returns the deleted path or ``None``."""
    if not CONFIG_DIR.exists():
        return None
    shutil.rmtree(CONFIG_DIR)
    return CONFIG_DIR


@click.command(name="uninstall")
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt (for scripts and CI).",
)
@click.option(
    "--purge",
    is_flag=True,
    default=False,
    help="Also delete ~/.config/dailybot/ (credentials, agent profiles, cached settings).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print the uninstall plan without executing it.",
)
def uninstall(assume_yes: bool, purge: bool, dry_run: bool) -> None:
    """Uninstall the Dailybot CLI from this machine.

    \b
    Auto-detects how the CLI was installed and runs the matching
    uninstall command (pipx / uv tool / pip). For installs managed by
    an external tool (Homebrew, PyInstaller binary, editable dev
    install), the command you should run is printed instead.

    \b
    Your local credentials and agent profiles in ~/.config/dailybot/
    are kept by default so you can reinstall later without re-doing
    `dailybot login` or `dailybot agent configure`. Pass --purge to
    remove that directory as well.

    \b
    Examples:
      dailybot uninstall              # confirm, then uninstall (keeps config)
      dailybot uninstall --yes        # uninstall without prompting
      dailybot uninstall --purge      # also wipe ~/.config/dailybot/
      dailybot uninstall --dry-run    # show the plan, do nothing
    """
    # 1. Resolve detection context.
    method: str = detect_install_method()
    label: str = METHOD_LABELS.get(method, method)
    install_path: Path = resolve_install_path()
    print_info(f"Install method:  {label}  ({install_path})")

    # 2. Editable installs deserve an early bail-out — we don't want to
    #    pip-uninstall someone's working clone out from under them.
    if method == "editable":
        print_warning(
            "This is an editable (development) install. "
            "Refusing to auto-uninstall — manage it with git/pip yourself:"
        )
        click.echo(f"\n  {_manual_command_hint(method, install_path)}\n")
        return

    argv: list[str] | None = _build_uninstall_argv(method)

    # 3. Build a single human-readable plan we can show before running.
    plan_lines: list[str] = []
    if argv is not None:
        plan_lines.append(f"  - run: {' '.join(argv)}")
    else:
        plan_lines.append(f"  - run (manually): {_manual_command_hint(method, install_path)}")

    if purge:
        if CONFIG_DIR.exists():
            plan_lines.append(f"  - delete: {CONFIG_DIR}")
        else:
            plan_lines.append(f"  - delete: {CONFIG_DIR}  (already absent)")
    else:
        plan_lines.append(f"  - keep:   {CONFIG_DIR}  (use --purge to remove)")

    click.echo("\nUninstall plan:")
    for line in plan_lines:
        click.echo(line)
    click.echo()

    # 4. Honor --dry-run before any side effects.
    if dry_run:
        print_info("Dry run — no changes made.")
        return

    # 5. Confirm unless --yes.
    if not assume_yes and not click.confirm("Proceed?", default=False):
        print_info("Aborted. Nothing was changed.")
        return

    # 6. Methods we don't auto-run: print the manual command and stop.
    if argv is None:
        print_warning(
            f"This is a {label} install. We don't run the package manager "
            "automatically; run this command yourself:"
        )
        click.echo(f"\n  {_manual_command_hint(method, install_path)}\n")
        if purge:
            _do_purge()
        return

    # 7. Run the uninstall subprocess.
    pretty_cmd: str = " ".join(argv)
    print_info(f"Running: {pretty_cmd}")
    click.echo()
    try:
        subprocess.run(argv, check=True)
    except subprocess.CalledProcessError as exc:
        print_error(
            f"Uninstall command failed with exit code {exc.returncode}. "
            f"You can try running it manually:\n  {pretty_cmd}"
        )
        raise SystemExit(exc.returncode)
    except FileNotFoundError:
        print_error(
            f"Could not find the executable for {label}. "
            f"Try the manual command:\n  {_manual_command_hint(method, install_path)}"
        )
        raise SystemExit(1)

    if purge:
        _do_purge()

    click.echo()
    print_success("Uninstall complete.")


def _do_purge() -> None:
    """Run the ``--purge`` step and report the outcome."""
    deleted: Path | None = _purge_config_dir()
    if deleted is None:
        print_info(f"Config directory {CONFIG_DIR} did not exist; nothing to delete.")
    else:
        print_success(f"Removed {deleted}")
