"""`--sort` for task lists: friendly aliases over the API's `sort` values.

The API accepts ``rank``, ``priority``, ``due_date``, ``start_date``, ``updated_at``,
``created_at`` and ``completed_at``, each with a leading ``-`` for descending, and refuses anything
else with ``400 invalid_sort`` (``extra.allowed``). The CLI maps the short names people type and
passes every other value through, so the server stays the one judge of what is allowed.
"""

import click

SORT_ALIASES: dict[str, str] = {
    "due": "due_date",
    "start": "start_date",
    "created": "created_at",
    "updated": "updated_at",
    "completed": "completed_at",
}
SORT_HELP: str = (
    "Order by rank, priority (urgent first), due, start, created, updated or completed "
    "(or the API names such as due_date); prefix with - for the reverse."
)
DESCENDING_PREFIX: str = "-"
PRIORITY_NOTE: str = " (urgent first)"
REVERSED_PRIORITY_NOTE: str = " (lowest first)"


def normalize_sort(value: str) -> str:
    """Map an alias (`due`, `-start`) to the API value; leave anything else untouched."""
    text: str = value.strip()
    descending: bool = text.startswith(DESCENDING_PREFIX)
    field: str = text[len(DESCENDING_PREFIX) :] if descending else text
    mapped: str = SORT_ALIASES.get(field.lower(), field)
    return f"{DESCENDING_PREFIX if descending else ''}{mapped}"


def parse_sort(_ctx: click.Context, _param: click.Parameter, value: str | None) -> str | None:
    """Click callback: a blank value is a usage error, the rest is normalized."""
    if value is None:
        return None
    if not value.strip().lstrip(DESCENDING_PREFIX):
        raise click.BadParameter("Give a field, for example priority, due or -updated.")
    return normalize_sort(value)


def describe_sort(value: str) -> str:
    """One human line for the active sort, e.g. `Sorted by priority (urgent first)`."""
    descending: bool = value.startswith(DESCENDING_PREFIX)
    field: str = value[len(DESCENDING_PREFIX) :] if descending else value
    note: str = ""
    if field == "priority":
        note = REVERSED_PRIORITY_NOTE if descending else PRIORITY_NOTE
    direction: str = " descending" if descending and field != "priority" else ""
    return f"Sorted by {field}{direction}{note}"
