"""Tests for free-plan awareness and the allowlist short-circuit (Task 3)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dailybot_cli.commands.public_api_helpers import enforce_plan_access


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_dir: Path = tmp_path / ".config" / "dailybot"
    config_dir.mkdir(parents=True)
    monkeypatch.setattr("dailybot_cli.config.CONFIG_DIR", config_dir)
    monkeypatch.delenv("DAILYBOT_CONFIG_DIR", raising=False)
    return config_dir


def _set_org(uuid: str) -> None:
    from dailybot_cli.config import save_credentials

    save_credentials(
        token="tok",
        email="me@example.com",
        organization="Org",
        organization_uuid=uuid,
        api_url="http://test",
    )


def _org_read(uuid: str, effective_tier: str) -> MagicMock:
    """`/v1/organization/` as PLAN_002 L37 re-reads it on a cached-free hit."""
    response: MagicMock = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.json.return_value = {
        "uuid": uuid,
        "name": "Org",
        "plan": {"tier": "free", "effective_tier": effective_tier, "is_trial": False},
    }
    return response


def test_known_free_org_short_circuits_non_allowlisted(tmp_config: Path) -> None:
    from dailybot_cli.config import save_org_plan

    _set_org("org-free")
    save_org_plan("org-free", "free")
    with (
        patch("dailybot_cli.api_client.httpx.get", return_value=_org_read("org-free", "free")),
        pytest.raises(SystemExit) as excinfo,
    ):
        enforce_plan_access("form_list")
    assert excinfo.value.code != 0


def test_allowlisted_action_never_short_circuits(tmp_config: Path) -> None:
    from dailybot_cli.config import save_org_plan

    _set_org("org-free")
    save_org_plan("org-free", "free")
    # Should NOT raise — agent-scoped / me / org actions are allowlisted.
    enforce_plan_access("agent_report")
    enforce_plan_access("me")


def test_unknown_plan_never_short_circuits(tmp_config: Path) -> None:
    _set_org("org-unknown")  # no plan cached
    enforce_plan_access("form_list")  # no raise → server stays authoritative


def test_paid_plan_never_short_circuits(tmp_config: Path) -> None:
    from dailybot_cli.config import save_org_plan

    _set_org("org-paid")
    save_org_plan("org-paid", "business")
    enforce_plan_access("form_list")  # no raise


def test_form_list_short_circuits_before_the_forms_request(tmp_config: Path) -> None:
    """A known-free org never issues the `form list` request; only the tier re-read."""
    from dailybot_cli.commands.form import form
    from dailybot_cli.config import save_org_plan

    _set_org("org-free")
    save_org_plan("org-free", "free")
    runner = CliRunner()
    with patch(
        "dailybot_cli.api_client.httpx.get", return_value=_org_read("org-free", "free")
    ) as mock_get:
        result = runner.invoke(form, ["list"])
    # PLAN_002 L37: one tier re-read of /v1/organization/, never the forms roundtrip.
    assert [c.args[0] for c in mock_get.call_args_list] == ["http://test/v1/organization/"]
    assert result.exit_code != 0
    assert "plan" in result.output.lower() or "upgrade" in result.output.lower()


def test_form_list_proceeds_when_plan_unknown(tmp_config: Path) -> None:
    """Unknown plan → the command issues its HTTP call (server authoritative)."""
    from dailybot_cli.commands.form import form

    _set_org("org-unknown")
    envelope: MagicMock = MagicMock()
    envelope.status_code = 200
    envelope.json.return_value = {"count": 0, "next": None, "results": []}
    runner = CliRunner()
    with patch("dailybot_cli.api_client.httpx.get", return_value=envelope) as mock_get:
        runner.invoke(form, ["list"])
    assert mock_get.call_count >= 1
