from click.testing import CliRunner

from satori_cli.commands.issue import issues
from satori_cli.commands.report import report
from tests.ids import pid

EXECUTION_ID = pid("exec", 222717)

FINDINGS = {
    "items": [
        {
            "id": pid("fnd", 1),
            "title": "example",
            "status": "OPEN",
            "source": "TOOL",
            "severity": 2,
            "execution_id": EXECUTION_ID,
            "created_at": "2024-01-01T00:00:00Z",
        }
    ],
    "total": 1,
}


class _FakeResponse:
    def __init__(self, data=None):
        self._data = data if data is not None else FINDINGS

    def json(self):
        return self._data


def _patch_get(monkeypatch):
    request = {}
    printed = []

    def get(path, params=None, timeout=None):
        request["method"] = "GET"
        request["path"] = path
        request["params"] = params
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.issue.client.get", get)
    monkeypatch.setattr(
        "satori_cli.commands.issue.stdout.print",
        lambda *args: printed.extend(args),
    )
    return request, printed


def test_issues_severity_alias_maps_to_list(monkeypatch):
    request, _ = _patch_get(monkeypatch)

    result = CliRunner().invoke(issues, ["--severity", "high"])

    assert result.exit_code == 0, result.output
    assert request["path"] == "/findings"
    assert request["params"]["severity"] == [2]


def test_issues_filters_exploitability(monkeypatch):
    request, _ = _patch_get(monkeypatch)

    result = CliRunner().invoke(issues, ["--exploitability", "exploitable"])

    assert result.exit_code == 0, result.output
    assert request["params"]["exploitability"] == "EXPLOITABLE"


def test_issues_severity_csv_maps_to_ints(monkeypatch):
    request, _ = _patch_get(monkeypatch)

    result = CliRunner().invoke(issues, ["--severity", "high,low,medium"])

    assert result.exit_code == 0, result.output
    assert request["params"]["severity"] == [2, 4, 3]


def test_issues_severity_csv_dedupes(monkeypatch):
    request, _ = _patch_get(monkeypatch)

    result = CliRunner().invoke(issues, ["--severity", "high,HIGH,low"])

    assert result.exit_code == 0, result.output
    assert request["params"]["severity"] == [2, 4]


def test_report_issues_severity_csv_and_execution_id(monkeypatch):
    request, _ = _patch_get(monkeypatch)

    result = CliRunner().invoke(
        report, [EXECUTION_ID, "issues", "--severity", "medium,info"]
    )

    assert result.exit_code == 0, result.output
    assert request["path"] == "/findings"
    assert request["params"]["severity"] == [3, 5]
    assert request["params"]["execution_id"] == EXECUTION_ID


def test_issues_rejects_invalid_severity_token(monkeypatch):
    request, _ = _patch_get(monkeypatch)

    result = CliRunner().invoke(issues, ["--severity", "high,nope"])

    assert result.exit_code != 0
    assert "Invalid severity" in result.output
    assert request == {}


def test_issues_rejects_numeric_severity(monkeypatch):
    request, _ = _patch_get(monkeypatch)

    result = CliRunner().invoke(issues, ["--severity", "3"])

    assert result.exit_code != 0
    assert "Invalid severity" in result.output
    assert request == {}
