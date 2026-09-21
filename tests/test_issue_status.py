from click.testing import CliRunner

from satori_cli.commands.issue import issue

FINDING = {
    "id": 10,
    "status": "TP",
    "title": "example",
}


class _FakeResponse:
    def __init__(self, data=None):
        self._data = data if data is not None else FINDING

    def json(self):
        return self._data


def _patch(monkeypatch):
    request = {}
    printed = []

    def patch(path, json=None, timeout=None):
        request["method"] = "PATCH"
        request["path"] = path
        request["json"] = json
        request["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.issue.client.patch", patch)
    monkeypatch.setattr(
        "satori_cli.commands.issue.stdout.print",
        lambda *args: printed.extend(args),
    )
    monkeypatch.setattr(
        "satori_cli.commands.issue.stdout.print_json",
        lambda data: printed.append(data),
    )
    return request, printed


def test_issue_status_tp(monkeypatch):
    request, printed = _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "status", "TP"])

    assert result.exit_code == 0, result.output
    assert request["method"] == "PATCH"
    assert request["path"] == "/findings/10"
    assert request["json"] == {"status": "TP"}
    assert printed == ["Issue 10 status set to TP"]


def test_issue_status_json(monkeypatch):
    request, printed = _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "status", "fp", "--json"])

    assert result.exit_code == 0, result.output
    assert request["path"] == "/findings/10"
    assert request["json"] == {"status": "FP"}
    assert printed == [FINDING]


def test_issue_status_rejects_old_names(monkeypatch):
    request, _ = _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "status", "CONFIRMED"])

    assert result.exit_code != 0
    assert "Invalid value" in result.output
    assert request == {}
