"""Load the recorded device-flow and standalone wire fixtures.

Every fixture under ``tests/fixtures/device_flow/`` is one recorded response:
``{"door", "status", "headers", "body"}``. Tests build mocked ``httpx``
responses from these files so a wire body has exactly one source.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

FIXTURES_DIR: Path = Path(__file__).parent / "fixtures" / "device_flow"


def load_fixture(name: str) -> dict[str, Any]:
    """Return the whole recorded fixture (door, status, headers, body)."""
    data: dict[str, Any] = json.loads((FIXTURES_DIR / f"{name}.json").read_text())
    return data


def fixture_body(name: str) -> dict[str, Any]:
    """Return only the recorded JSON body."""
    body: dict[str, Any] = load_fixture(name)["body"]
    return body


def fixture_response(name: str) -> MagicMock:
    """Build a mocked ``httpx.Response`` that replays the recorded fixture."""
    recorded: dict[str, Any] = load_fixture(name)
    response: MagicMock = MagicMock()
    response.status_code = recorded["status"]
    response.is_success = 200 <= recorded["status"] < 300
    response.headers = dict(recorded["headers"])
    response.json.return_value = recorded["body"]
    response.text = json.dumps(recorded["body"])
    return response
