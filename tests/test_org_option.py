import click
import pytest
from click.testing import CliRunner

from satori_cli import cli
from satori_cli.config import config

ORGANIZATIONS = [
    {"id": 7, "name": "Acme"},
    {"id": 8, "name": "Dup"},
    {"id": 9, "name": "dup"},
]


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def requests(monkeypatch) -> list:
    for attr in ("_config", "_env_config", "_current_config"):
        monkeypatch.setattr(config, attr, {})
    requests = []

    def get(path, **kwargs):
        requests.append((path, config.get("organization")))
        if path == "/organizations":
            return _FakeResponse(ORGANIZATIONS)
        return _FakeResponse({"items": [], "total": 0})

    monkeypatch.setattr("satori_cli.commands.report.client.get", get)
    monkeypatch.setattr("satori_cli.commands.report.stdout.print", lambda *a: None)
    return requests


def test_org_at_the_end_of_a_command(requests):
    result = CliRunner().invoke(cli, ["reports", "--org", "7"])

    assert result.exit_code == 0, result.output
    assert requests == [("/executions", 7)]


@pytest.mark.parametrize(
    "args",
    [
        ["report", "5", "output", "--org", "7"],
        ["report", "--org", "7", "5", "output"],
        ["report", "--org", "Acme", "5", "output"],
    ],
)
def test_org_is_not_read_as_the_id(monkeypatch, requests, args):
    shown = []
    monkeypatch.setattr(
        "satori_cli.commands.report.show_execution_output",
        lambda execution_id, **kwargs: shown.append(
            (execution_id, config.get("organization"))
        ),
    )

    result = CliRunner().invoke(cli, args)

    assert result.exit_code == 0, result.output
    assert shown == [(5, 7)]


def test_org_by_name(requests):
    result = CliRunner().invoke(cli, ["reports", "--org", "acme"])

    assert result.exit_code == 0, result.output
    assert requests == [("/organizations", None), ("/executions", 7)]


def test_org_by_unknown_name(requests):
    result = CliRunner().invoke(cli, ["reports", "--org", "Nope"])

    assert result.exit_code == 2
    assert "no organization named 'Nope'" in result.output
    assert requests == [("/organizations", None)]


def test_org_by_ambiguous_name(requests):
    result = CliRunner().invoke(cli, ["reports", "--org", "dup"])

    assert result.exit_code == 2
    assert "(8, 9)" in result.output


def test_org_is_not_a_global_option(requests):
    result = CliRunner().invoke(cli, ["--org", "7", "reports"])

    assert result.exit_code == 2
    assert requests == []


def test_every_subcommand_has_one_org_option():
    def walk(group: click.Group):
        for command in group.commands.values():
            yield command
            if isinstance(command, click.Group):
                yield from walk(command)

    assert not any(p.name == "org" for p in cli.params)
    for command in walk(cli):
        assert [p.name for p in command.params].count("org") == 1, command.name


def test_org_by_name_is_listed_on_your_own_account(monkeypatch, requests):
    monkeypatch.setattr(config, "_config", {"default": {"organization": 3}})

    result = CliRunner().invoke(cli, ["reports", "--org", "Acme"])

    assert result.exit_code == 0, result.output
    assert requests == [("/organizations", None), ("/executions", 7)]
