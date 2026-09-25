"""Shared roll-up rendering for projects and goals.

AD-01 is the reason this module exists. The goals list and the goal detail once
disagreed for the same goal at the same moment — `project_count` 0 vs 3,
`projects` [] vs three cards, `progress` null vs a real number. The server-side
fix was to **omit** a field it had not computed, because:

* **zero is a real value** — a goal genuinely can have no projects, so a falsy
  default is indistinguishable from the truth;
* **null was already taken** — `progress` is legitimately null for a goal with
  nothing to measure;
* **absence is the only answer a client can act on.**

So three states must stay three states all the way to the terminal. A client that
renders absence as `0` reintroduces the exact defect the server fixed.
"""

from typing import Any

NOT_REQUESTED: str = "not requested"
NOTHING_TO_MEASURE: str = "nothing to measure"


def render_rollup(row: dict[str, Any], field: str) -> str:
    """Render one roll-up field, preserving absent / null / value as three answers."""
    if field not in row:
        return NOT_REQUESTED
    value: Any = row[field]
    if value is None:
        return NOTHING_TO_MEASURE
    if isinstance(value, dict) and "percent_complete" in value:
        # A progress object (ProjectProgress / GoalProgress): say it as a person
        # would read it, not as a Python dict.
        text: str = f"{value.get('percent_complete')}%"
        if "completed" in value and "total" in value:
            text += f" ({value.get('completed')} of {value.get('total')} done)"
        if value.get("is_partial"):
            text += " — partial: some linked projects are not visible to you"
        return text
    return str(value)
