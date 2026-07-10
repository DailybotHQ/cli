"""Tests for resource_uuid — the single reader of a payload's identifier.

The API exposes three shapes at once:
  * forms and form responses    -> only ``uuid``
  * agent reports / messages    -> both ``id`` and ``uuid`` (same value)
  * check-ins / kudos/ workflows -> only ``id``
"""

from dailybot_cli.api_client import resource_uuid

UUID_A: str = "76174afc-490b-489b-b5cf-e9f84e000001"
UUID_B: str = "76174afc-490b-489b-b5cf-e9f84e000002"


def test_reads_uuid_when_only_uuid_is_present() -> None:
    assert resource_uuid({"uuid": UUID_A, "name": "Vendor Request"}) == UUID_A


def test_reads_id_when_only_id_is_present() -> None:
    assert resource_uuid({"id": UUID_A, "name": "Daily Stand-up"}) == UUID_A


def test_prefers_uuid_when_both_are_present() -> None:
    assert resource_uuid({"id": UUID_B, "uuid": UUID_A}) == UUID_A


def test_returns_empty_string_when_neither_is_present() -> None:
    assert resource_uuid({"name": "orphan"}) == ""


def test_ignores_empty_uuid_and_falls_back_to_id() -> None:
    assert resource_uuid({"uuid": "", "id": UUID_A}) == UUID_A


def test_coerces_non_string_identifier() -> None:
    assert resource_uuid({"id": 42}) == "42"
