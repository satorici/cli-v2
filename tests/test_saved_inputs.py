import pytest
from click.testing import CliRunner

from satori_cli.commands.parameters import parameters
from satori_cli.commands.secrets import secrets


class _FakeResponse:
    def __init__(self, payload=None):
        self._payload = payload

    def json(self):
        return self._payload


params: list = []


def _record(monkeypatch, module: str, method: str, payload=None) -> list:
    requests = []
    params.clear()

    def call(path, **kwargs):
        requests.append((path, kwargs.get("json")))
        params.append(kwargs.get("params"))
        return _FakeResponse(payload)

    monkeypatch.setattr(f"satori_cli.commands.{module}.client.{method}", call)
    return requests


def _printed(monkeypatch, module: str) -> list:
    printed = []
    monkeypatch.setattr(
        f"satori_cli.commands.{module}.stdout.print",
        lambda *args, **kwargs: printed.append(args[0] if args else None),
    )
    return printed


def test_parameters_list(monkeypatch):
    _record(monkeypatch, "parameters", "get", [{"name": "HOST", "values": ["a", "b"]}])
    printed = _printed(monkeypatch, "parameters")

    result = CliRunner().invoke(parameters, ["list"])

    assert result.exit_code == 0, result.output
    table = printed[0]
    assert list(table.columns[0]._cells) == ["HOST"]
    assert list(table.columns[1]._cells) == ["a,b"]


def test_parameters_set_sends_all_values(monkeypatch):
    requests = _record(monkeypatch, "parameters", "put")
    _printed(monkeypatch, "parameters")

    result = CliRunner().invoke(parameters, ["set", "HOST", "a", "b"])

    assert result.exit_code == 0, result.output
    assert requests == [("/settings/parameters/HOST", {"values": ("a", "b")})]


def test_parameters_set_requires_a_value(monkeypatch):
    requests = _record(monkeypatch, "parameters", "put")

    result = CliRunner().invoke(parameters, ["set", "HOST"])

    assert result.exit_code != 0
    assert requests == []


def test_parameters_unset(monkeypatch):
    requests = _record(monkeypatch, "parameters", "delete")
    _printed(monkeypatch, "parameters")

    result = CliRunner().invoke(parameters, ["unset", "HOST"])

    assert result.exit_code == 0, result.output
    assert requests == [("/settings/parameters/HOST", None)]


def test_secrets_list_shows_names_only(monkeypatch):
    _record(
        monkeypatch,
        "secrets",
        "get",
        [{"name": "TOKEN", "created_at": "2026-01-01T00:00:00"}],
    )
    printed = _printed(monkeypatch, "secrets")

    result = CliRunner().invoke(secrets, ["list"])

    assert result.exit_code == 0, result.output
    assert list(printed[0].columns[0]._cells) == ["TOKEN"]


def test_secrets_set_reads_stdin(monkeypatch):
    requests = _record(monkeypatch, "secrets", "put")
    _printed(monkeypatch, "secrets")

    result = CliRunner().invoke(secrets, ["set", "TOKEN"], input="s3cret\n")

    assert result.exit_code == 0, result.output
    assert requests == [("/settings/secrets/TOKEN", {"value": "s3cret"})]


def test_secrets_set_prompts_hidden_on_a_terminal(monkeypatch):
    requests = _record(monkeypatch, "secrets", "put")
    _printed(monkeypatch, "secrets")
    monkeypatch.setattr("satori_cli.commands.secrets._stdin_is_tty", lambda: True)
    prompts = []

    def prompt(text, hide_input):
        prompts.append(hide_input)
        return "s3cret"

    monkeypatch.setattr("satori_cli.commands.secrets.click.prompt", prompt)

    result = CliRunner().invoke(secrets, ["set", "TOKEN"])

    assert result.exit_code == 0, result.output
    assert prompts == [True]
    assert requests == [("/settings/secrets/TOKEN", {"value": "s3cret"})]


def test_secrets_set_rejects_empty_value(monkeypatch):
    requests = _record(monkeypatch, "secrets", "put")

    result = CliRunner().invoke(secrets, ["set", "TOKEN"], input="")

    assert result.exit_code != 0
    assert requests == []


def test_secrets_unset(monkeypatch):
    requests = _record(monkeypatch, "secrets", "delete")
    _printed(monkeypatch, "secrets")

    result = CliRunner().invoke(secrets, ["unset", "TOKEN"])

    assert result.exit_code == 0, result.output
    assert requests == [("/settings/secrets/TOKEN", None)]


def test_parameters_set_for_a_repository(monkeypatch):
    requests = _record(monkeypatch, "parameters", "put")
    _printed(monkeypatch, "parameters")

    result = CliRunner().invoke(parameters, ["set", "HOST", "a", "--repo", "acme/app"])

    assert result.exit_code == 0, result.output
    assert requests == [("/settings/parameters/HOST", {"values": ("a",)})]
    assert params == [{"repository": "acme/app"}]


def test_user_wide_sends_no_repository(monkeypatch):
    _record(monkeypatch, "secrets", "delete")
    _printed(monkeypatch, "secrets")

    result = CliRunner().invoke(secrets, ["unset", "TOKEN"])

    assert result.exit_code == 0, result.output
    assert params == [{}]


def test_secrets_set_for_a_repository(monkeypatch):
    requests = _record(monkeypatch, "secrets", "put")
    _printed(monkeypatch, "secrets")

    result = CliRunner().invoke(
        secrets, ["set", "TOKEN", "--repo", "acme/app"], input="s3cret"
    )

    assert result.exit_code == 0, result.output
    assert requests == [("/settings/secrets/TOKEN", {"value": "s3cret"})]
    assert params == [{"repository": "acme/app"}]


@pytest.mark.parametrize("repo", ["acme/*", "acme", "a/b/c"])
def test_wildcard_repo_is_rejected(monkeypatch, repo):
    requests = _record(monkeypatch, "secrets", "get", [])

    result = CliRunner().invoke(secrets, ["list", "--repo", repo])

    assert result.exit_code != 0
    assert requests == []
