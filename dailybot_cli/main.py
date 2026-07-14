"""Dailybot CLI entry point."""

import platform

import click

from dailybot_cli import __version__
from dailybot_cli.commands.agent import agent
from dailybot_cli.commands.ask import ask
from dailybot_cli.commands.auth import login, logout
from dailybot_cli.commands.channels import channels
from dailybot_cli.commands.chat import chat
from dailybot_cli.commands.checkin import checkin
from dailybot_cli.commands.config import config
from dailybot_cli.commands.conversation import conversation
from dailybot_cli.commands.env import env
from dailybot_cli.commands.form import form
from dailybot_cli.commands.hook import hook
from dailybot_cli.commands.identity import me, org
from dailybot_cli.commands.interactive import run_interactive
from dailybot_cli.commands.interactive_chat import interactive
from dailybot_cli.commands.kudos import kudos
from dailybot_cli.commands.status import status
from dailybot_cli.commands.team import team
from dailybot_cli.commands.uninstall import uninstall
from dailybot_cli.commands.update import update
from dailybot_cli.commands.upgrade import upgrade
from dailybot_cli.commands.user import user
from dailybot_cli.commands.version import version
from dailybot_cli.commands.workflow import workflow
from dailybot_cli.config import (
    RepoEnvError,
    load_repo_env,
    set_api_url_override,
    set_app_url_override,
)
from dailybot_cli.display import print_error

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
@click.option(
    "--app-url",
    default=None,
    envvar="DAILYBOT_APP_URL",
    help="Override the webapp/dashboard base URL (default: https://app.dailybot.com).",
)
@click.pass_context
def cli(ctx: click.Context, api_url: str | None, app_url: str | None) -> None:
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
    # Fatal safety check: if `.dailybot/env.json` exists in the current tree
    # AND it is tracked by git, refuse to run ANY command. Silently swallowing
    # this in `_safe_active_env_profile()` (as the resilient per-getter path
    # does) would mean the CLI happily continues with global auth while the
    # user's org API keys leak in git history — precisely the disaster the
    # gitignore + guard combo is meant to prevent. Blocking here is the
    # correct security posture: force the user to `git rm --cached` (and
    # rotate the exposed key) before the CLI does anything else.
    #
    # Single exemption: the `hook` group. Its contract (docs/AGENT_HOOKS.md)
    # is "always exit 0, never break the developer's agent harness, never
    # call the network" — hooks never consume env.json auth, so the guard
    # degrades to a stderr warning there instead of aborting every agent
    # session in the repo.
    try:
        load_repo_env()
    except RepoEnvError as exc:
        print_error(str(exc))
        if ctx.invoked_subcommand != "hook":
            raise SystemExit(1) from exc

    if api_url:
        set_api_url_override(api_url)
    if app_url:
        set_app_url_override(app_url)
    if ctx.invoked_subcommand is None:
        run_interactive()


cli.add_command(login)
cli.add_command(logout)
cli.add_command(update)
cli.add_command(status)
cli.add_command(checkin)
cli.add_command(form)
cli.add_command(channels)
cli.add_command(kudos)
cli.add_command(team)
cli.add_command(user)
cli.add_command(me)
cli.add_command(org)
cli.add_command(workflow)
cli.add_command(agent)
cli.add_command(chat)
cli.add_command(conversation)
cli.add_command(ask)
cli.add_command(interactive)
cli.add_command(config)
cli.add_command(env)
cli.add_command(hook)
cli.add_command(version)
cli.add_command(upgrade)
cli.add_command(uninstall)


if __name__ == "__main__":
    cli()
