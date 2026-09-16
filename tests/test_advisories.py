from click.testing import CliRunner
from rich.console import Console

from satori_cli.commands.advisory import advisories, advisory
from satori_cli.utils.wrappers import (
    ExternalIssueListWrapper,
    ExternalIssueWrapper,
    PagedWrapper,
)

ITEMS = [
    {
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
    },
    {
        "id": 2,
        "created_at": "2026-09-02T11:00:00Z",
        "execution_id": 43,
        "finding_id": 11,
        "provider": "GITHUB",
        "kind": "SECURITY_ADVISORY",
        "title": "Failed advisory",
        "description": "desc",
        "severity": None,
        "vulnerabilities": [],
        "external_url": None,
        "external_id": None,
        "user_id": 7,
        "visibility": "PUBLIC",
    },
]


class _FakeResponse:
    def __init__(self, data=None):
        self._data = data if data is not None else {"total": 2, "items": ITEMS}

    def json(self):
        return self._data


def _patch(monkeypatch):
    request = {}
    printed = []

    def get(path, params=None):
        request["method"] = "GET"
        request["path"] = path
        request["params"] = params
        if path.startswith("/external_issues/") and path != "/external_issues":
            return _FakeResponse(ITEMS[0])
        return _FakeResponse()

    def patch(path, json=None):
        request["method"] = "PATCH"
        request["path"] = path
        request["json"] = json
        return _FakeResponse({})

    monkeypatch.setattr("satori_cli.commands.advisory.client.get", get)
    monkeypatch.setattr("satori_cli.commands.advisory.client.patch", patch)
    monkeypatch.setattr(
        "satori_cli.commands.advisory.stdout.print",
        lambda *args: printed.extend(args),
    )
    return request, printed


def test_advisories_defaults(monkeypatch):
    request, printed = _patch(monkeypatch)

    result = CliRunner().invoke(advisories)

    assert result.exit_code == 0, result.output
    assert request["path"] == "/external_issues"
    assert request["params"] == {"page": 1, "quantity": 10}
    assert len(printed) == 1
    wrapper = printed[0]
    assert isinstance(wrapper, PagedWrapper)
    assert wrapper._wrapper is ExternalIssueListWrapper


def test_advisories_filters_are_uppercased(monkeypatch):
    request, _ = _patch(monkeypatch)

    result = CliRunner().invoke(
        advisories,
        [
            "--kind",
            "security_advisory",
            "--provider",
            "github",
            "--order",
            "asc",
            "--execution-id",
            "42",
            "--page",
            "2",
            "-q",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    assert request["params"] == {
        "page": 2,
        "quantity": 5,
        "execution_id": 42,
        "kind": "SECURITY_ADVISORY",
        "provider": "GITHUB",
        "order": "ASC",
    }


def test_advisory_get(monkeypatch):
    request, printed = _patch(monkeypatch)

    result = CliRunner().invoke(advisory, ["1"])

    assert result.exit_code == 0, result.output
    assert request["method"] == "GET"
    assert request["path"] == "/external_issues/1"
    assert len(printed) == 1
    assert isinstance(printed[0], ExternalIssueWrapper)
    assert printed[0].obj["id"] == 1


def test_advisory_missing_id():
    result = CliRunner().invoke(advisory, [])

    assert result.exit_code != 0
    assert "ADVISORY-ID" in result.output


def test_advisory_visibility(monkeypatch):
    request, printed = _patch(monkeypatch)

    result = CliRunner().invoke(advisory, ["1", "visibility", "public"])

    assert result.exit_code == 0, result.output
    assert request["method"] == "PATCH"
    assert request["path"] == "/external_issues/1"
    assert request["json"] == {"visibility": "PUBLIC"}
    assert printed == ["Advisory visibility set to PUBLIC"]


def test_external_issue_list_wrapper_renders():
    console = Console(record=True, width=200)
    console.print(ExternalIssueListWrapper(ITEMS))
    text = console.export_text()

    assert "SQL" in text
    assert "injection" in text
    assert "Failed" in text
    assert "advisory" in text
    assert "Security" in text
    assert "High" in text
    assert "N/A" in text
    assert "2026-09-01" in text
    assert "10:00:00" in text


def test_external_issue_wrapper_renders():
    console = Console(record=True, width=200)
    console.print(ExternalIssueWrapper(ITEMS[0]))
    text = console.export_text()

    assert "Advisory 1" in text
    assert "SQL injection in login" in text
    assert "Security advisory" in text
    assert "Github" in text
    assert "High" in text
    assert "Private" in text
    assert "42" in text
    assert "10" in text
    assert "GHSA-x" in text
    assert "desc" in text
    assert "2026-09-01 10:00:00" in text
