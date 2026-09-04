import pytest
from click.testing import CliRunner

from satori_cli.commands.playbook import playbook
from satori_cli.exceptions import SatoriError
from satori_cli.models import Playbook


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_variables_extracts_from_cmd(tmp_path):
    playbook_path = tmp_path / "playbook.yml"
    playbook_path.write_text('cmd: ["echo ${{MY_VAR}}"]\n')
    playbook_model = Playbook(str(playbook_path))
    assert "MY_VAR" in playbook_model.variables


def test_monitor_expression_rate(tmp_path):
    playbook_path = tmp_path / "playbook.yml"
    playbook_path.write_text('settings:\n  rate: "5 minutes"\n')
    playbook_model = Playbook(str(playbook_path))
    assert playbook_model.monitor_expression == "rate(5 minutes)"


def test_monitor_expression_cron(tmp_path):
    playbook_path = tmp_path / "playbook.yml"
    playbook_path.write_text('settings:\n  cron: "0 12 * * ? *"\n')
    playbook_model = Playbook(str(playbook_path))
    assert playbook_model.monitor_expression == "cron(0 12 * * ? *)"


def test_invalid_yaml_raises(tmp_path):
    playbook_path = tmp_path / "playbook.yml"
    playbook_path.write_bytes(b"{{not valid yaml")
    with pytest.raises(SatoriError, match="invalid format"):
        Playbook(str(playbook_path))


def test_playbook_from_execution_id_fetches_public(monkeypatch):
    api_calls = []
    playbooks_calls = []
    detail = {
        "id": "code/semgrep.yml",
        "name": "Semgrep",
        "uri": "satori://code/semgrep.yml",
        "category": "code",
        "content": "cmd: []\n",
    }

    def api_get(path, **kwargs):
        api_calls.append(path)
        return _FakeResponse(
            {
                "id": 42,
                "job": {"playbook_source": "satori://code/semgrep.yml"},
            }
        )

    def playbooks_get(path, **kwargs):
        playbooks_calls.append(path)
        return _FakeResponse(detail)

    printed = []

    monkeypatch.setattr("satori_cli.commands.playbook.client.get", api_get)
    monkeypatch.setattr(
        "satori_cli.commands.playbook.playbooks_client.get", playbooks_get
    )
    monkeypatch.setattr(
        "satori_cli.commands.playbook.stdout.print",
        lambda *args, **kwargs: printed.append(args[0]),
    )

    result = CliRunner().invoke(playbook, ["42"])

    assert result.exit_code == 0, result.output
    assert api_calls == ["/executions/42"]
    assert playbooks_calls == ["/playbooks/code/semgrep.yml"]
    assert printed[0].obj == detail


def test_playbook_from_execution_id_rejects_bundle(monkeypatch):
    monkeypatch.setattr(
        "satori_cli.commands.playbook.client.get",
        lambda *args, **kwargs: _FakeResponse(
            {"id": 42, "job": {"playbook_source": "bundle://abc123"}}
        ),
    )

    result = CliRunner().invoke(playbook, ["42"])

    assert result.exit_code != 0
    assert isinstance(result.exception, SatoriError)
    assert "not a public playbook" in str(result.exception)


def test_playbook_from_uri_fetches_directly(monkeypatch):
    playbooks_calls = []
    detail = {
        "id": "code/semgrep.yml",
        "name": "Semgrep",
        "uri": "satori://code/semgrep.yml",
        "category": "code",
    }

    def playbooks_get(path, **kwargs):
        playbooks_calls.append(path)
        return _FakeResponse(detail)

    printed = []

    monkeypatch.setattr(
        "satori_cli.commands.playbook.playbooks_client.get", playbooks_get
    )
    monkeypatch.setattr(
        "satori_cli.commands.playbook.stdout.print",
        lambda *args, **kwargs: printed.append(args[0]),
    )

    result = CliRunner().invoke(playbook, ["satori://code/semgrep.yml"])

    assert result.exit_code == 0, result.output
    assert playbooks_calls == ["/playbooks/code/semgrep.yml"]
    assert printed[0].obj == detail
