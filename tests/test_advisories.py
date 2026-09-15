from click.testing import CliRunner
from rich.console import Console

from satori_cli.commands.advisory import advisories
from satori_cli.utils.wrappers import ExternalIssueListWrapper, PagedWrapper

ITEMS = [
    {
        "id": 1,
        "created_at": "2026-09-01T10:00:00.123456Z",
        "execution_id": 42,
        "provider": "GITHUB",
        "kind": "SECURITY_ADVISORY",
        "title": "SQL injection in login",
        "description": "desc",
        "severity": "HIGH",
        "vulnerabilities": [],
        "external_url": "https://github.com/org/repo/security/advisories/GHSA-x",
        "external_id": "GHSA-x",
        "user_id": 7,
    },
    {
        "id": 2,
        "created_at": "2026-09-02T11:00:00Z",
        "execution_id": 43,
        "provider": "GITHUB",
        "kind": "SECURITY_ADVISORY",
        "title": "Failed advisory",
        "description": "desc",
        "severity": None,
        "vulnerabilities": [],
        "external_url": None,
        "external_id": None,
        "user_id": 7,
    },
]


class _FakeResponse:
    def json(self):
        return {"total": 2, "items": ITEMS}


def _patch(monkeypatch):
    request = {}
    printed = []

    def get(path, params=None):
        request["path"] = path
        request["params"] = params
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.advisory.client.get", get)
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


def test_external_issue_list_wrapper_renders():
    console = Console(record=True, width=200)
    console.print(ExternalIssueListWrapper(ITEMS))
    text = console.export_text()

    assert "SQL injection in login" in text
    assert "Failed advisory" in text
    assert "Security advisory" in text
    assert "High" in text
    assert "N/A" in text
    assert "2026-09-01 10:00:00" in text
