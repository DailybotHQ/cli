"""`dailybot plan`: the product's own name for the Tasks command groups.

The product formerly called Tasks is now **Dailybot Plan** (public API root ``/v1/plan/``). Every existing
group keeps its name (``tasks``, ``task``, ``board``, ``project``, ``goal``) so no script or agent breaks;
this root mounts the very same group objects, so ``dailybot plan tasks routes list`` and
``dailybot tasks routes list`` are one command.
"""

import click

from dailybot_cli.commands.board import board
from dailybot_cli.commands.goal import goal
from dailybot_cli.commands.project import project
from dailybot_cli.commands.task import task
from dailybot_cli.commands.tasks import tasks


@click.group("plan")
def plan() -> None:
    """Dailybot Plan (formerly Tasks): tasks, boards, projects, goals and their notifications.

    \b
    `dailybot plan <group> ...` is the same as `dailybot <group> ...`; both keep working:
      dailybot plan tasks status      = dailybot tasks status
      dailybot plan task get ENG-142  = dailybot task get ENG-142
      dailybot plan board | project | goal ...
    Notifications, routes, reports and the briefing live under the tasks group:
      dailybot plan tasks notifications get
    """


for _group in (tasks, task, board, project, goal):
    plan.add_command(_group)
