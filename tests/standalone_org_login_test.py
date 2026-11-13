"""Email-code login with standalone Dailybot organizations (PLAN_002 T-standalone-org-login).

Frozen marker (W2): a native entry carries `"platform": "dailybot", "standalone": true`;
legacy entries keep exactly `{id, name, uuid}`. HTTP is mocked at the call site.
"""

import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner, Result

from dailybot_cli.commands.auth import org_choice_label
from dailybot_cli.config import load_credentials
from dailybot_cli.main import cli
from tests.wire_fixture_loader import fixture_body

POST: str = "dailybot_cli.api_client.httpx.post"
ORGS: list[dict[str, Any]] = fixture_body("verify_code_org_selection_200")["organizations"]
LEGACY_ORG: dict[str, Any] = next(o for o in ORGS if not o.get("standalone"))
NATIVE_ORG: dict[str, Any] = next(o for o in ORGS if o.get("standalone"))


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DAILYBOT_API_KEY", "DAILYBOT_CLI_TOKEN", "DAILYBOT_API_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def agents_file(_isolated_environment: Path) -> Path:
    _isolated_environment.mkdir(parents=True, exist_ok=True)
    path: Path = _isolated_environment / "agents.json"
    path.write_text(json.dumps({"default": "bot", "profiles": {"bot": {"api_key": "test-key"}}}))
    return path


def _response(status: int, body: dict[str, Any]) -> MagicMock:
    response: MagicMock = MagicMock()
    response.status_code = status
    response.headers = {}
    response.json.return_value = body
    response.text = json.dumps(body)
    return response


def _request_code_multi() -> MagicMock:
    return _response(200, {"is_multi_org": True, "organizations": copy.deepcopy(ORGS)})


def _token_for(org: dict[str, Any]) -> MagicMock:
    body: dict[str, Any] = copy.deepcopy(fixture_body("verify_code_legacy_200"))
    body["organization"] = {"id": org["id"], "name": org["name"], "uuid": org["uuid"]}
    return _response(200, body)


def _selection_required() -> MagicMock:
    return _response(200, copy.deepcopy(fixture_body("verify_code_org_selection_200")))


class TestNonInteractive:
    def test_step_one_lists_the_standalone_org_with_its_uuid(self) -> None:
        with patch(POST, return_value=_request_code_multi()):
            result: Result = CliRunner().invoke(cli, ["login", "--email", "me@example.com"])
        assert result.exit_code == 0, result.output
        assert f"{NATIVE_ORG['name']} (uuid: {NATIVE_ORG['uuid']})" in result.output
        assert f"{LEGACY_ORG['name']} (uuid: {LEGACY_ORG['uuid']})" in result.output

    def test_org_resolves_the_standalone_uuid(self, agents_file: Path) -> None:
        before: bytes = agents_file.read_bytes()
        runner: CliRunner = CliRunner()
        with patch(POST, side_effect=[_request_code_multi(), _token_for(NATIVE_ORG)]) as post:
            runner.invoke(cli, ["login", "--email", "me@example.com"])
            result: Result = runner.invoke(
                cli,
                [
                    "login",
                    "--email",
                    "me@example.com",
                    "--code",
                    "123456",
                    "--org",
                    NATIVE_ORG["uuid"],
                ],
            )
        assert result.exit_code == 0, result.output
        assert post.call_args.kwargs["json"]["organization_id"] == NATIVE_ORG["id"]
        creds: dict[str, Any] | None = load_credentials()
        assert creds is not None
        assert creds["organization"] == NATIVE_ORG["name"]
        assert creds["organization_uuid"] == NATIVE_ORG["uuid"]
        assert agents_file.read_bytes() == before

    def test_a_selection_answer_lists_both_kinds_unchanged(self) -> None:
        with patch(POST, return_value=_selection_required()):
            result: Result = CliRunner().invoke(
                cli, ["login", "--email", "me@example.com", "--code", "123456"]
            )
        assert result.exit_code == 1
        lines: list[str] = [line.strip() for line in result.output.splitlines()]
        assert f"{NATIVE_ORG['name']} (uuid: {NATIVE_ORG['uuid']})" in lines
        assert f"{LEGACY_ORG['name']} (uuid: {LEGACY_ORG['uuid']})" in lines


class TestInteractive:
    def test_the_picker_marks_the_standalone_org_and_selects_it(self, agents_file: Path) -> None:
        before: bytes = agents_file.read_bytes()
        seen: list[str] = []

        def pick(_message: str, choices: list[Any]) -> MagicMock:
            seen.extend(str(c.title) for c in choices)
            question: MagicMock = MagicMock()
            question.ask.return_value = next(c.value for c in choices if c.value.get("standalone"))
            return question

        with (
            patch("dailybot_cli.commands.auth.questionary.select", side_effect=pick),
            patch(POST, side_effect=[_request_code_multi(), _token_for(NATIVE_ORG)]) as post,
        ):
            result: Result = CliRunner().invoke(cli, ["login"], input="me@example.com\n123456\n")
        assert result.exit_code == 0, result.output
        assert org_choice_label(NATIVE_ORG) in seen
        assert org_choice_label(LEGACY_ORG) in seen
        assert post.call_args.kwargs["json"]["organization_id"] == NATIVE_ORG["id"]
        assert agents_file.read_bytes() == before

    def test_the_numbered_fallback_selects_it(self) -> None:
        question: MagicMock = MagicMock()
        question.ask.return_value = None
        native_index: int = ORGS.index(NATIVE_ORG) + 1
        with (
            patch("dailybot_cli.commands.auth.questionary.select", return_value=question),
            patch(POST, side_effect=[_request_code_multi(), _token_for(NATIVE_ORG)]) as post,
        ):
            result: Result = CliRunner().invoke(
                cli, ["login"], input=f"me@example.com\n{native_index}\n123456\n"
            )
        assert result.exit_code == 0, result.output
        assert org_choice_label(NATIVE_ORG) in result.output
        assert post.call_args.kwargs["json"]["organization_id"] == NATIVE_ORG["id"]


class TestLabels:
    def test_a_standalone_org_is_marked(self) -> None:
        assert org_choice_label(NATIVE_ORG) == f"{NATIVE_ORG['name']} (Dailybot)"

    def test_a_legacy_org_keeps_its_name(self) -> None:
        assert org_choice_label(LEGACY_ORG) == LEGACY_ORG["name"]

    def test_an_agent_org_is_not_standalone(self) -> None:
        agent_org: dict[str, Any] = {"id": 3, "name": "Bots", "uuid": "u", "platform": "dailybot"}
        assert org_choice_label(agent_org) == "Bots"
