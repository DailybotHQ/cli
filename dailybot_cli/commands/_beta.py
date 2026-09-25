"""The Tasks Beta notice, shared by every Tasks command group.

The facts are fixed product copy (the same words ship in the README, the agent
skill and the web app). Terminal help cannot render Markdown, so the help block
carries the canonical words with the Markdown emphasis removed — never reworded.
Nothing here is ever added to `--json` output: machine shapes stay stable.
"""

import click

BETA_SUPPORT_EMAIL: str = "support@dailybot.com"

# `\b` keeps Click from reflowing the block into the paragraph that follows.
BETA_HELP_BLOCK: str = (
    "\b\n"
    "Beta — Tasks is in beta. Everything under /tasks in the web app, the CLI and\n"
    "agent skill commands for projects, goals, boards and tasks, and the /v1/tasks/\n"
    "public API may change before general availability. Want to try it with your\n"
    f"team? Write to {BETA_SUPPORT_EMAIL}."
)

# One line for human output (`tasks status`), never for `--json`.
BETA_STATUS_LINE: str = (
    "Beta — Tasks is in beta and may change before general availability. "
    f"Want to try it with your team? Write to {BETA_SUPPORT_EMAIL}."
)


def mark_beta(group: click.Group) -> click.Group:
    """Put the Beta notice at the top of a Tasks group's `--help`.

    The one-line summary shown in `dailybot --help` stays the group's own first
    line, so the root listing does not read "Beta —" five times.
    """
    own_help: str = group.help or ""
    if group.short_help is None:
        group.short_help = own_help.split("\n", 1)[0].strip()
    group.help = f"{BETA_HELP_BLOCK}\n\n{own_help}"
    return group
