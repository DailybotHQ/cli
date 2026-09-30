"""`dailybot plan`: the one root of the Dailybot Plan command groups.

The product formerly called Tasks is **Dailybot Plan** (public API root ``/v1/plan/``). Its groups
(``tasks``, ``task``, ``board``, ``project``, ``goal``) are reachable only under this root, e.g.
``dailybot plan tasks routes list``; there are no top-level aliases.
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
    Every command lives under `dailybot plan`:
      dailybot plan tasks status
      dailybot plan task get ENG-142
      dailybot plan board | project | goal ...
    Notifications, routes, reports and the briefing live under the tasks group:
      dailybot plan tasks notifications get
    """


for _group in (tasks, task, board, project, goal):
    plan.add_command(_group)
