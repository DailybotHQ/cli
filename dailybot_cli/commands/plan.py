"""`dailybot plan`: the one root of the Dailybot Plan command groups.

Dailybot Plan (public API root ``/v1/plan/``). Its groups (``tasks``, ``task``, ``board``,
``project``, ``goal``, ``label``, ``views``) are reachable only under this root,
e.g. ``dailybot plan tasks routes list``.
"""

import click

from dailybot_cli.commands.board import board
from dailybot_cli.commands.goal import goal
from dailybot_cli.commands.plan_label import label
from dailybot_cli.commands.plan_views import views
from dailybot_cli.commands.project import project
from dailybot_cli.commands.task import task
from dailybot_cli.commands.tasks import tasks


@click.group("plan")
def plan() -> None:
    """Dailybot Plan: tasks, boards, projects, goals and their notifications.

    \b
    Every command lives under `dailybot plan`:
      dailybot plan tasks status
      dailybot plan task get ENG-142
      dailybot plan board | project | goal | label | views ...
    Notifications, routes, reports and the briefing live under the tasks group:
      dailybot plan tasks notifications get
    """


for _group in (tasks, task, board, project, goal, label, views):
    plan.add_command(_group)
