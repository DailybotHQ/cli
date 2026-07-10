"""The kudos `--filter` value must reach the API in the form it accepts.

The API accepts only lowercase `kudos_received` / `kudos_given`. The CLI (and its
docs) advertise `KUDOS_RECEIVED` / `KUDOS_GIVEN`, and used to pass them verbatim,
which the API rejected with `400 "Not valid kudos filter"`. The normalizer maps
the friendly forms to the accepted values.
"""

import pytest

from dailybot_cli.commands.kudos import normalize_kudos_filter


@pytest.mark.parametrize(
    "raw",
    ["KUDOS_RECEIVED", "kudos_received", "received", "RECEIVED", "Received", " kudos_received "],
)
def test_received_variants_map_to_kudos_received(raw: str) -> None:
    assert normalize_kudos_filter(raw) == "kudos_received"


@pytest.mark.parametrize("raw", ["KUDOS_GIVEN", "kudos_given", "given", "GIVEN"])
def test_given_variants_map_to_kudos_given(raw: str) -> None:
    assert normalize_kudos_filter(raw) == "kudos_given"


def test_none_passes_through() -> None:
    assert normalize_kudos_filter(None) is None


def test_unknown_value_is_left_untouched() -> None:
    # Forward an unrecognized value as-is; let the server be the source of truth.
    assert normalize_kudos_filter("something_else") == "something_else"
