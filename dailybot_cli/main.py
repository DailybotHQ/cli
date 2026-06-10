"""Dailybot CLI entry point."""

import platform

import click

from dailybot_cli import __version__
from dailybot_cli.commands.agent import agent
from dailybot_cli.commands.auth import login, logout
from dailybot_cli.commands.checkin import checkin
from dailybot_cli.commands.config import config
from dailybot_cli.commands.form import form
from dailybot_cli.commands.hook import hook
from dailybot_cli.commands.interactive import run_interactive
from dailybot_cli.commands.kudos import kudos
from dailybot_cli.commands.status import status
from dailybot_cli.commands.team import team
from dailybot_cli.commands.uninstall import uninstall
from dailybot_cli.commands.update import update
from dailybot_cli.commands.upgrade import upgrade
from dailybot_cli.commands.user import user
from dailybot_cli.commands.version import version
from dailybot_cli.config import set_api_url_override

# Format used by `dailybot --version`. Single line so it's friendly to scripts
# parsing the output. The richer multi-line panel lives in `dailybot version`.
_VERSION_MESSAGE: str = f"dailybot {__version__} (Python {platform.python_version()})"


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="dailybot", message=_VERSION_MESSAGE)
@click.option(
    "--api-url",
    default=None,
    envvar="DAILYBOT_API_URL",
    help="Override the API base URL (e.g. staging).",
)
@click.pass_context
def cli(ctx: click.Context, api_url: str | None) -> None:
    """Dailybot CLI - The command-line bridge between humans and agents.

    \b
    Quick start:
      dailybot login               # Authenticate with email OTP
      dailybot status              # View pending check-ins
      dailybot update "message"    # Submit a free-text update
      dailybot update --done "X" --doing "Y" --blocked "None"

    \b
    Agent mode (API key or login session):
      Progress updates, health reporting, and messaging.
      dailybot config key=<API_KEY>   # Store API key
      dailybot agent update "Deployed v2.1" --name "My Agent"
      dailybot agent --help

    \b
    No Dailybot account? Agents can register autonomously:
      dailybot agent register --org-name "My Org" --agent-name "My Agent"

    Run without arguments for interactive mode.
    """
    if api_url:
        set_api_url_override(api_url)
    if ctx.invoked_subcommand is None:
        run_interactive()


cli.add_command(login)
cli.add_command(logout)
cli.add_command(update)
cli.add_command(status)
cli.add_command(checkin)
cli.add_command(form)
cli.add_command(kudos)
cli.add_command(team)
cli.add_command(user)
cli.add_command(agent)
cli.add_command(config)
cli.add_command(hook)
cli.add_command(version)
cli.add_command(upgrade)
cli.add_command(uninstall)


if __name__ == "__main__":
    cli()
