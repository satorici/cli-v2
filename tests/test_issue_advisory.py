from click.testing import CliRunner

from satori_cli.commands.issue import issue
from satori_cli.constants import advisory_url
from satori_cli.utils.wrappers import ExternalIssueWrapper

ADVISORY = {
    "id": 1,
    "created_at": "2026-09-01T10:00:00.123456Z",
    "execution_id": 42,
    "finding_id": 10,
    "provider": "GITHUB",
    "kind": "SECURITY_ADVISORY",
    "title": "SQL injection in login",
    "description": "desc",
    "severity": "HIGH",
    "vulnerabilities": [],
    "external_url": "https://github.com/org/repo/security/advisories/GHSA-x",
    "external_id": "GHSA-x",
    "user_id": 7,
    "visibility": "PRIVATE",
}


class _FakeResponse:
    def __init__(self, data=None):
        self._data = data if data is not None else ADVISORY

    def json(self):
        return self._data


def _patch(monkeypatch):
    request = {}
    printed = []
    warnings = []

    def post(path, json=None, timeout=None):
        request["method"] = "POST"
        request["path"] = path
        request["json"] = json
        request["timeout"] = timeout
        return _FakeResponse()

    def req(method, path, json=None):
        request["method"] = method
        request["path"] = path
        request["json"] = json
        return _FakeResponse({})

    monkeypatch.setattr("satori_cli.commands.issue.client.post", post)
    monkeypatch.setattr("satori_cli.commands.issue.client.request", req)
    monkeypatch.setattr(
        "satori_cli.commands.issue.stdout.print",
        lambda *args: printed.extend(args),
    )
    monkeypatch.setattr(
        "satori_cli.commands.issue.stdout.print_json",
        lambda data: printed.append(data),
    )
    monkeypatch.setattr(
        "satori_cli.commands.issue.stderr.print",
        lambda *args: warnings.extend(args),
    )
    return request, printed, warnings


def test_issue_advisory_create(monkeypatch):
    request, printed, warnings = _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "advisory"])

    assert result.exit_code == 0, result.output
    assert request["method"] == "POST"
    assert request["path"] == "/external_issues/security_advisory"
    assert request["json"] == {"finding_id": 10}
    assert request["timeout"] == 10
    assert len(printed) == 2
    assert isinstance(printed[0], ExternalIssueWrapper)
    assert printed[0].obj == ADVISORY
    assert printed[1] == f"View on web: {advisory_url(ADVISORY['id'])}"
    assert warnings == [
        "WARNING: Draft is not published yet. "
        "Publish with: satori-v2 issue 10 advisory --publish"
    ]


def test_issue_advisory_publish(monkeypatch):
    request, printed, _ = _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "advisory", "--publish"])

    assert result.exit_code == 0, result.output
    assert request["method"] == "POST"
    assert request["path"] == "/external_issues/security_advisory/publish"
    assert request["json"] == {"finding_id": 10}
    assert request["timeout"] == 30
    assert printed == [ADVISORY["external_url"]]


def test_issue_advisory_delete(monkeypatch):
    request, printed, _ = _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "advisory", "--delete"])

    assert result.exit_code == 0, result.output
    assert request["method"] == "DELETE"
    assert request["path"] == "/external_issues/security_advisory"
    assert request["json"] == {"finding_id": 10}
    assert printed == ["Advisory deleted"]


def test_issue_advisory_publish_and_delete_mutex(monkeypatch):
    _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "advisory", "--publish", "--delete"])

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()
