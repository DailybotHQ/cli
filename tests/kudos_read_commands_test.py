"""Tests for kudos read commands: list / org / wall-of-fame (Task 8)."""

from typing import Any
from unittest.mock import MagicMock

from click.testing import CliRunner

from dailybot_cli.api_client import APIError
from dailybot_cli.main import cli


def _client(monkeypatch: Any) -> MagicMock:
    client = MagicMock()
    monkeypatch.setattr("dailybot_cli.commands.public_api_helpers.get_agent_auth", lambda: "tok")
    monkeypatch.setattr(
        "dailybot_cli.commands.public_api_helpers.DailyBotClient", lambda *a, **k: client
    )
    return client


def test_kudos_list_renders_and_footer(monkeypatch: Any) -> None:
    client = _client(monkeypatch)

    def fake_list(**kwargs: Any) -> list[dict[str, Any]]:
        if kwargs.get("meta") is not None:
            kwargs["meta"]["count"] = 5
            kwargs["meta"]["next"] = None
        return [
            {
                "user": {"full_name": "Alice"},
                "receivers": [{"full_name": "Bob"}],
                "content": "nice work",
                "created_at": "2026-07-01T00:00:00Z",
            }
        ]

    client.list_kudos.side_effect = fake_list
    result = CliRunner().invoke(cli, ["kudos", "list", "--limit", "1"])
    assert result.exit_code == 0
    assert "Alice" in result.output and "Bob" in result.output
    assert "Showing" in result.output


def test_kudos_list_forwards_filter_and_search(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.list_kudos.return_value = []
    result = CliRunner().invoke(
        cli, ["kudos", "list", "--filter", "KUDOS_RECEIVED", "--search", "sprint"]
    )
    assert result.exit_code == 0
    kwargs = client.list_kudos.call_args[1]
    # The friendly KUDOS_RECEIVED is normalized to the token the API accepts.
    assert kwargs["kudos_filter"] == "kudos_received"
    assert kwargs["search"] == "sprint"


def test_kudos_org_json(monkeypatch: Any) -> None:
    """`kudos org` is the org-wide kudos feed, not an aggregate stats object."""
    client = _client(monkeypatch)
    client.list_kudos_organization.return_value = [{"id": "k1", "content": "Nice work"}]
    result = CliRunner().invoke(cli, ["kudos", "org", "--json"])
    assert result.exit_code == 0
    assert "Nice work" in result.output


def test_kudos_org_forwards_filters(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.list_kudos_organization.return_value = []
    result = CliRunner().invoke(
        cli, ["kudos", "org", "--search", "onboarding", "--since", "2026-07-01", "--page-size", "5"]
    )
    assert result.exit_code == 0
    kwargs = client.list_kudos_organization.call_args[1]
    assert kwargs["search"] == "onboarding"
    assert kwargs["start_date"] == "2026-07-01"
    assert kwargs["page_size"] == 5
    assert kwargs["fetch_all"] is False


# Mirrors the real GET /v1/kudos/wall-of-fame/ payload: people are nested under
# "user", the leaderboard is a paginated envelope, and "leaderboard_summary" is
# the caller's own position.
_WALL_OF_FAME_PAYLOAD: dict[str, Any] = {
    "top_receiver": {
        "user": {"uuid": "u-1", "full_name": "Zoe", "image": ""},
        "kudos_received": 11,
        "kudos_given": 5,
        "total_plus_kudos_received": 18,
        "total_plus_kudos_given": 2,
    },
    "top_giver": {
        "user": {"uuid": "u-2", "full_name": "Gus", "image": ""},
        "kudos_given": 14,
        "kudos_received": 3,
        "total_plus_kudos_given": 1,
        "total_plus_kudos_received": 9,
    },
    "dna_distribution": [
        {
            "company_value": {"id": "v-1", "value": "Cares deeply", "emoji": "❤️"},
            "count": 10,
            "percentage": 38.5,
        }
    ],
    "leaderboard": {
        "count": 11,
        "next": False,
        "previous": False,
        "results": [
            {
                "position": 1,
                "user": {"uuid": "u-1", "full_name": "Zoe", "image": ""},
                "score": 11,
                "total_plus_kudos": 18,
            },
            {
                "position": 2,
                "user": {"uuid": "u-3", "full_name": "Sam", "image": ""},
                "score": 7,
                "total_plus_kudos": 8,
            },
        ],
    },
    "leaderboard_summary": {"position": 1, "total": 11},
}


def test_kudos_wall_of_fame_renders_real_payload(monkeypatch: Any) -> None:
    """Top receiver/giver come from the nested ``user`` object, the leaderboard
    from the ``{count, next, previous, results}`` envelope."""
    client = _client(monkeypatch)
    client.get_kudos_wall_of_fame.return_value = _WALL_OF_FAME_PAYLOAD
    result = CliRunner().invoke(cli, ["kudos", "wall-of-fame", "--limit", "5"])
    assert result.exit_code == 0
    assert "Zoe" in result.output  # top receiver (nested user.full_name)
    assert "Gus" in result.output  # top giver (nested user.full_name)
    assert "Sam" in result.output  # leaderboard entry
    assert "1 of 11" in result.output  # caller position from leaderboard_summary
    assert "Showing 2 of 11" in result.output  # envelope count, not dict-key count
    assert client.get_kudos_wall_of_fame.call_args[1]["limit"] == 5


def test_kudos_wall_of_fame_tolerates_partial_payload(monkeypatch: Any) -> None:
    """Missing/flat fields degrade to dashes instead of crashing."""
    client = _client(monkeypatch)
    client.get_kudos_wall_of_fame.return_value = {
        "top_receiver": {"full_name": "Zoe"},
        "leaderboard": [{"position": 1, "user": {"full_name": "Zoe"}, "score": 3}],
    }
    result = CliRunner().invoke(cli, ["kudos", "wall-of-fame"])
    assert result.exit_code == 0
    assert "Zoe" in result.output


def test_kudos_wall_of_fame_json_passthrough(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.get_kudos_wall_of_fame.return_value = _WALL_OF_FAME_PAYLOAD
    result = CliRunner().invoke(cli, ["kudos", "wall-of-fame", "--json"])
    assert result.exit_code == 0
    assert '"leaderboard_summary"' in result.output
    assert '"full_name": "Gus"' in result.output


def test_kudos_org_api_error(monkeypatch: Any) -> None:
    client = _client(monkeypatch)
    client.list_kudos_organization.side_effect = APIError(403, "forbidden")
    result = CliRunner().invoke(cli, ["kudos", "org", "--json"])
    assert result.exit_code == 4
