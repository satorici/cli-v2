import pytest

from satori_cli.exceptions import SatoriError
from satori_cli.models import Playbook


def test_variables_extracts_from_cmd(tmp_path):
    playbook_path = tmp_path / "playbook.yml"
    playbook_path.write_text('cmd: ["echo ${{MY_VAR}}"]\n')
    playbook = Playbook(str(playbook_path))
    assert "MY_VAR" in playbook.variables


def test_monitor_expression_rate(tmp_path):
    playbook_path = tmp_path / "playbook.yml"
    playbook_path.write_text('settings:\n  rate: "5 minutes"\n')
    playbook = Playbook(str(playbook_path))
    assert playbook.monitor_expression == "rate(5 minutes)"


def test_monitor_expression_cron(tmp_path):
    playbook_path = tmp_path / "playbook.yml"
    playbook_path.write_text('settings:\n  cron: "0 12 * * ? *"\n')
    playbook = Playbook(str(playbook_path))
    assert playbook.monitor_expression == "cron(0 12 * * ? *)"


def test_invalid_yaml_raises(tmp_path):
    playbook_path = tmp_path / "playbook.yml"
    playbook_path.write_bytes(b"{{not valid yaml")
    with pytest.raises(SatoriError, match="invalid format"):
        Playbook(str(playbook_path))
