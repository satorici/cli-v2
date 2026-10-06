from click.testing import CliRunner
from rich.console import Console

from satori_cli.commands.advisory import advisories, advisory
from satori_cli.config import config
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
        "repository": "org/repo",
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
        "repository": "acme/widget",
    },
]

HISTORY = [
    {
        "kind": "event",
        "id": 2,
        "created_at": "2026-09-21T00:01:00Z",
        "finding_id": 10,
        "type": "STATUS_CHANGED",
        "payload": {"from": "OPEN", "to": "TP"},
        "display_name": "alice",
    },
]


class _FakeResponse:
    def __init__(self, data=None):
        self._data = data if data is not None else {"total": 2, "items": ITEMS}

    def json(self):
        return self._data


def _clear_output_flags():
    # always_merger mutates profile dicts, so clear there too.
    config._current_config.pop("json", None)
    config._current_config.pop("format", None)
    for profile in config._config.values():
        if isinstance(profile, dict):
            profile.pop("json", None)
            profile.pop("format", None)


def _patch(monkeypatch):
    _clear_output_flags()
    request = {}
    requests = []
    printed = []

    def get(path, params=None):
        entry = {"method": "GET", "path": path, "params": params}
        request.update(entry)
        requests.append(entry)
        if path.endswith("/timeline"):
            return _FakeResponse(HISTORY)
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
    return request, requests, printed


def test_advisories_defaults(monkeypatch):
    request, _, printed = _patch(monkeypatch)

    result = CliRunner().invoke(advisories)

    assert result.exit_code == 0, result.output
    assert request["path"] == "/external_issues"
    assert request["params"] == {"page": 1, "quantity": 10}
    assert len(printed) == 1
    wrapper = printed[0]
    assert isinstance(wrapper, PagedWrapper)
    assert wrapper._wrapper is ExternalIssueListWrapper


def test_advisories_filters_are_uppercased(monkeypatch):
    request, _, _ = _patch(monkeypatch)

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
    _, requests, printed = _patch(monkeypatch)

    result = CliRunner().invoke(advisory, ["1"])

    assert result.exit_code == 0, result.output
    assert [r["path"] for r in requests] == [
        "/external_issues/1",
        "/findings/10/timeline",
    ]
    assert len(printed) == 1
    assert isinstance(printed[0], ExternalIssueWrapper)
    assert printed[0].obj["id"] == 1
    assert printed[0].obj["history"] == HISTORY


def test_advisory_missing_id():
    result = CliRunner().invoke(advisory, [])

    assert result.exit_code != 0
    assert "ADVISORY-ID" in result.output


def test_advisory_visibility(monkeypatch):
    request, _, printed = _patch(monkeypatch)

    result = CliRunner().invoke(advisory, ["1", "visibility", "public"])

    assert result.exit_code == 0, result.output
    assert request["method"] == "PATCH"
    assert request["path"] == "/external_issues/1"
    assert request["json"] == {"visibility": "PUBLIC"}
    assert printed == ["Advisory visibility set to PUBLIC"]


def test_external_issue_list_wrapper_renders():
    _clear_output_flags()
    console = Console(record=True, width=200)
    console.print(ExternalIssueListWrapper(ITEMS))
    text = console.export_text()

    assert "SQL" in text
    assert "injection" in text
    assert "Failed" in text
    assert "advisory" in text
    assert "org/repo" in text
    assert "acme/" in text
    assert "Published" in text
    assert "Unpublish" in text
    assert "High" in text
    assert "N/A" in text
    assert "2026-09-01" in text
    assert "10:00:00" in text
    assert "Security advisory" not in text
    assert "https://github.com" not in text


def test_external_issue_wrapper_renders():
    _clear_output_flags()
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
    assert "History" not in text
