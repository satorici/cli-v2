from click.testing import CliRunner

from satori_cli.commands.scan import scan
from satori_cli.utils.wrappers import command_generator


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _scan_response(playbook_source: str, quantity: int | None = 1):
    return {
        "id": 99,
        "type": "SCAN",
        "playbook_source": playbook_source,
        "visibility": "PRIVATE",
        "created_at": "2026-01-01T00:00:00Z",
        "repository_data": {"repository": "satorici/satori-cli"},
        "criteria": {"quantity": quantity},
        "status": "FETCHING_DATA",
    }


def test_scan_with_playbook_option(monkeypatch):
    request = {}

    def post(path, json):
        request["path"] = path
        request["body"] = json
        return _FakeResponse(
            _scan_response("satori://code/python/pyspector_v2.yml")
        )

    monkeypatch.setattr("satori_cli.commands.scan.client.post", post)
    monkeypatch.setattr("satori_cli.commands.scan.stdout.print", lambda *args: None)

    result = CliRunner().invoke(
        scan,
        [
            "satorici/satori-cli",
            "--playbook",
            "satori://code/python/pyspector_v2.yml",
            "-q",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert request["path"] == "/jobs/scans"
    assert request["body"]["playbook_source"] == "satori://code/python/pyspector_v2.yml"
    assert request["body"]["repository_data"] == {"repository": "satorici/satori-cli"}
    assert request["body"]["criteria"] == {"quantity": 1}


def test_scan_with_positional_source(monkeypatch):
    request = {}

    def post(path, json):
        request["path"] = path
        request["body"] = json
        return _FakeResponse(
            _scan_response("satori://code/python/pyspector_v2.yml")
        )

    monkeypatch.setattr("satori_cli.commands.scan.client.post", post)
    monkeypatch.setattr("satori_cli.commands.scan.stdout.print", lambda *args: None)

    result = CliRunner().invoke(
        scan,
        [
            "satorici/satori-cli",
            "satori://code/python/pyspector_v2.yml",
            "-q",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert request["path"] == "/jobs/scans"
    assert request["body"]["playbook_source"] == "satori://code/python/pyspector_v2.yml"
    assert request["body"]["criteria"] == {"quantity": 1}


def test_scan_playbook_overrides_positional_source(monkeypatch):
    request = {}

    def post(path, json):
        request["body"] = json
        return _FakeResponse(_scan_response("satori://preferred.yml"))

    monkeypatch.setattr("satori_cli.commands.scan.client.post", post)
    monkeypatch.setattr("satori_cli.commands.scan.stdout.print", lambda *args: None)

    result = CliRunner().invoke(
        scan,
        [
            "satorici/satori-cli",
            "satori://ignored.yml",
            "--playbook",
            "satori://preferred.yml",
            "-q",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert request["body"]["playbook_source"] == "satori://preferred.yml"


def test_scan_requires_source_or_playbook():
    result = CliRunner().invoke(scan, ["satorici/satori-cli"])

    assert result.exit_code != 0
    assert "SOURCE or --playbook is required" in result.output


def test_command_generator_scan_order():
    cmd = command_generator(
        {
            "type": "SCAN",
            "playbook_source": "satori://code/python/pyspector_v2.yml",
            "repository_data": {"repository": "satorici/satori-cli"},
            "criteria": {"quantity": 1},
        }
    )

    assert (
        cmd
        == "satori-v2 scan satorici/satori-cli satori://code/python/pyspector_v2.yml -q 1"
    )


def test_command_generator_scan_without_quantity():
    cmd = command_generator(
        {
            "type": "SCAN",
            "playbook_source": "satori://code/semgrep.yml",
            "repository_data": {"repository": "satorici/satori-cli"},
            "criteria": {},
        }
    )

    assert cmd == "satori-v2 scan satorici/satori-cli satori://code/semgrep.yml"
