import pytest
from click.testing import CliRunner

from satori_cli import cli
from satori_cli.api import client
from satori_cli.config import config
from satori_cli.utils import verify_issue as verify_mod
from satori_cli.utils.public_id import EXAMPLE_ID, is_public_id

ID = EXAMPLE_ID


class _FakeResponse:
    text = "{}"

    def __init__(self, payload=None):
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


@pytest.fixture
def calls(monkeypatch) -> list:
    for attr in ("_config", "_env_config", "_current_config"):
        monkeypatch.setattr(config, attr, {})
    calls = []

    def record(method):
        def call(path, *args, **kwargs):
            calls.append((method, path))
            return _FakeResponse()

        return call

    for method in ("get", "patch", "post", "delete"):
        monkeypatch.setattr(client, method, record(method))
    return calls


@pytest.mark.parametrize("value", [ID, "0" * 21, "a" * 21, "AbC123" + "x" * 15])
def test_valid_public_ids(value):
    assert is_public_id(value)


@pytest.mark.parametrize(
    "value",
    ["42", "a" * 20, "a" * 22, ID[:-1] + "-", ID[:-1] + "_", ID + "\n", "", "ñ" * 21],
)
def test_invalid_public_ids(value):
    assert not is_public_id(value)


@pytest.mark.parametrize(
    "args",
    [
        ["report", "42", "output"],
        ["report", "42"],
        ["reports", "42"],
        ["monitor", "5", "pause"],
        ["execution", "get", "42"],
        ["execution", "list", "--job-id", "7"],
        ["job", "7"],
        ["stop", "run", "7"],
        ["output", "42"],
        ["issues", "42"],
        ["issues", "--execution-id", "42"],
        ["advisories", "--execution-id", "42"],
        ["search", "--id-gt", "42"],
        ["reports", "search", "--job-id", "7"],
    ],
)
def test_integer_ids_are_rejected_before_any_request(calls, args):
    result = CliRunner().invoke(cli, args)

    words = " ".join(result.output.replace("│", " ").split())
    assert result.exit_code == 2, result.output
    assert "is not a valid" in words and "21 letters and digits" in words
    assert calls == []


def test_id_before_the_subcommand(calls):
    result = CliRunner().invoke(cli, ["issue", ID, "status", "TP"])

    assert result.exit_code == 0, result.output
    assert calls == [("patch", f"/findings/{ID}")]


def test_subcommand_argument_is_not_read_as_the_id(calls):
    result = CliRunner().invoke(cli, ["advisory", "visibility", "PUBLIC"])

    assert result.exit_code != 0
    assert "Missing argument 'ADVISORY-ID'" in result.output
    assert calls == []


def test_organization_ids_stay_integers(monkeypatch, calls):
    monkeypatch.setattr(
        "satori_cli.commands.organization._organizations_table", lambda orgs: ""
    )
    result = CliRunner().invoke(cli, ["organization", "7"])

    assert result.exit_code == 0, result.output
    assert calls == [("get", "/organizations/7")]


def test_scan_id_manages_the_scan(calls):
    result = CliRunner().invoke(cli, ["scan", ID, "stop"])

    assert result.exit_code == 0, result.output
    assert calls == [("patch", f"/jobs/scans/{ID}")]


def test_playbook_takes_an_execution_id(calls):
    result = CliRunner().invoke(cli, ["playbook", ID])

    assert result.exit_code == 0, result.output
    assert calls == [("get", f"/executions/{ID}/playbook")]


def test_playbook_rejects_an_integer(calls):
    result = CliRunner().invoke(cli, ["playbook", "42"])

    assert result.exit_code != 0
    assert calls == []


def test_verdicts_keyed_by_public_id():
    other = "Z" * 21
    assert verify_mod._verdicts(f'[{{"id": "{ID}", "verdict": "tp"}}]') == {
        ID: {"verdict": "TP", "evidence": ""}
    }
    broken = f'[{{"id": "{ID}", "verdict": "FP", "x": "a"b"}}, {{"verdict":"TP","id":{other}}}]'
    assert verify_mod._verdicts(broken) == {
        ID: {"verdict": "FP", "evidence": ""}, other: {"verdict": "TP", "evidence": ""}
    }


# TEMPORARY: legacy integer IDs for findings and advisories. Remove with `allow_legacy_int`.
def test_legacy_int_finding_id_is_sent_as_is(calls):
    result = CliRunner().invoke(cli, ["issue", "10", "status", "TP"])

    assert result.exit_code == 0, result.output
    assert calls == [("patch", "/findings/10")]


def test_legacy_int_advisory_id_is_sent_as_is(calls):
    CliRunner().invoke(cli, ["advisory", "1"])

    assert calls and calls[0] == ("get", "/external_issues/1")


def test_legacy_int_finding_id_creates_an_advisory(calls):
    CliRunner().invoke(cli, ["issue", "125333", "advisory"])

    assert calls and calls[0] == ("post", "/external_issues/security_advisory")


def test_oversized_int_finding_id_is_rejected(calls):
    result = CliRunner().invoke(cli, ["issue", "9" * 19, "status", "TP"])

    assert result.exit_code == 2, result.output
    assert calls == []
