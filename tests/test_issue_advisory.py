from click.testing import CliRunner
from httpx2 import HTTPStatusError, Request, Response
from rich.console import Console

from satori_cli.commands.issue import issue
from satori_cli.config import config
from satori_cli.constants import advisory_url
from satori_cli.utils.wrappers import ExternalIssueWrapper

DRAFT_ADVISORY = {
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
    "external_url": None,
    "external_id": None,
    "user_id": 7,
    "visibility": "PRIVATE",
}

ADVISORY = {
    **DRAFT_ADVISORY,
    "external_url": "https://github.com/org/repo/security/advisories/GHSA-x",
    "external_id": "GHSA-x",
}

STATUS = {"status": "triage"}

HISTORY = [
    {
        "kind": "comment",
        "id": 1,
        "body": "confirmed SSRF via httpx",
        "created_at": "2026-09-21T00:00:00Z",
        "edited_at": None,
        "user_id": 7,
        "display_name": "alice",
    },
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
        self._data = data if data is not None else ADVISORY

    def json(self):
        return self._data


def _conflict():
    request = Request("POST", "https://api-v2.satori.ci/external_issues/security_advisory")
    response = Response(409, request=request)
    return HTTPStatusError(
        "A security advisory already exists for this finding",
        request=request,
        response=response,
    )


def _clear_output_flags():
    # always_merger mutates profile dicts, so clear there too.
    config._current_config.pop("json", None)
    config._current_config.pop("format", None)
    for profile in config._config.values():
        if isinstance(profile, dict):
            profile.pop("json", None)
            profile.pop("format", None)


def _patch(monkeypatch, *, list_items=None, post_response=None, post_error=None):
    _clear_output_flags()
    request = {}
    requests = []
    printed = []
    warnings = []

    def post(path, json=None, timeout=None):
        entry = {
            "method": "POST",
            "path": path,
            "json": json,
            "timeout": timeout,
        }
        request.update(entry)
        requests.append(entry)
        if post_error is not None:
            raise post_error
        return _FakeResponse(post_response)

    def req(method, path, json=None):
        entry = {"method": method, "path": path, "json": json}
        request.update(entry)
        requests.append(entry)
        return _FakeResponse({})

    def get(path, params=None):
        entry = {"method": "GET", "path": path, "params": params}
        request.update(entry)
        requests.append(entry)
        if path == "/external_issues":
            items = list_items if list_items is not None else [ADVISORY]
            return _FakeResponse({"total": len(items), "items": items})
        if path.endswith("/status"):
            return _FakeResponse(STATUS)
        if path.endswith("/timeline"):
            return _FakeResponse(HISTORY)
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.issue.client.post", post)
    monkeypatch.setattr("satori_cli.commands.issue.client.request", req)
    monkeypatch.setattr("satori_cli.commands.issue.client.get", get)
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
    return request, requests, printed, warnings


def test_issue_advisory_create(monkeypatch):
    _, requests, printed, warnings = _patch(
        monkeypatch, post_response=DRAFT_ADVISORY
    )

    result = CliRunner().invoke(issue, ["10", "advisory"])

    assert result.exit_code == 0, result.output
    assert requests[0]["method"] == "POST"
    assert requests[0]["path"] == "/external_issues/security_advisory"
    assert requests[0]["json"] == {"finding_id": 10}
    assert requests[0]["timeout"] == 10
    assert requests[1]["method"] == "GET"
    assert requests[1]["path"] == "/findings/10/timeline"
    assert len(printed) == 2
    assert isinstance(printed[0], ExternalIssueWrapper)
    assert printed[0].obj["id"] == DRAFT_ADVISORY["id"]
    assert printed[0].obj["history"] == HISTORY
    assert printed[1] == f"View on web: {advisory_url(DRAFT_ADVISORY['id'])}"
    assert warnings == [
        "WARNING: Draft is not published yet. "
        "Publish with: satori-v2 issue 10 advisory --publish"
    ]


def test_issue_advisory_already_exists_published(monkeypatch):
    _, requests, printed, warnings = _patch(
        monkeypatch, post_error=_conflict(), list_items=[ADVISORY]
    )

    result = CliRunner().invoke(issue, ["10", "advisory"])

    assert result.exit_code == 0, result.output
    assert requests[0]["method"] == "POST"
    assert requests[0]["path"] == "/external_issues/security_advisory"
    assert requests[1]["method"] == "GET"
    assert requests[1]["path"] == "/external_issues"
    assert requests[1]["params"] == {
        "finding_id": 10,
        "kind": "SECURITY_ADVISORY",
        "quantity": 1,
    }
    assert requests[2]["path"] == "/findings/10/timeline"
    assert len(printed) == 2
    assert isinstance(printed[0], ExternalIssueWrapper)
    assert printed[0].obj["id"] == ADVISORY["id"]
    assert printed[0].obj["history"] == HISTORY
    assert printed[1] == f"View on web: {advisory_url(ADVISORY['id'])}"
    assert warnings == []


def test_issue_advisory_already_exists_draft(monkeypatch):
    _, requests, printed, warnings = _patch(
        monkeypatch, post_error=_conflict(), list_items=[DRAFT_ADVISORY]
    )

    result = CliRunner().invoke(issue, ["10", "advisory"])

    assert result.exit_code == 0, result.output
    assert requests[1]["path"] == "/external_issues"
    assert requests[2]["path"] == "/findings/10/timeline"
    assert isinstance(printed[0], ExternalIssueWrapper)
    assert printed[0].obj["id"] == DRAFT_ADVISORY["id"]
    assert printed[0].obj["history"] == HISTORY
    assert warnings == [
        "WARNING: Draft is not published yet. "
        "Publish with: satori-v2 issue 10 advisory --publish"
    ]


def test_issue_advisory_publish(monkeypatch):
    request, requests, printed, _ = _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "advisory", "--publish"])

    assert result.exit_code == 0, result.output
    assert request["method"] == "POST"
    assert request["path"] == "/external_issues/security_advisory/publish"
    assert request["json"] == {"finding_id": 10}
    assert request["timeout"] == 30
    assert printed == [ADVISORY["external_url"]]
    assert not any(r["path"].endswith("/timeline") for r in requests)


def test_issue_advisory_delete(monkeypatch):
    request, requests, printed, _ = _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "advisory", "--delete"])

    assert result.exit_code == 0, result.output
    assert request["method"] == "DELETE"
    assert request["path"] == "/external_issues/security_advisory"
    assert request["json"] == {"finding_id": 10}
    assert printed == ["Advisory deleted"]
    assert not any(r["path"].endswith("/timeline") for r in requests)


def test_issue_advisory_status(monkeypatch):
    _, requests, printed, _ = _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "advisory", "--status"])

    assert result.exit_code == 0, result.output
    assert requests[0]["method"] == "GET"
    assert requests[0]["path"] == "/external_issues"
    assert requests[0]["params"] == {
        "finding_id": 10,
        "kind": "SECURITY_ADVISORY",
        "quantity": 1,
    }
    assert requests[1]["method"] == "GET"
    assert requests[1]["path"] == "/external_issues/1/status"
    assert printed == ["triage"]
    assert not any(r["path"].endswith("/timeline") for r in requests)


def test_issue_advisory_status_json(monkeypatch):
    _, requests, printed, _ = _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "advisory", "--status", "--json"])

    assert result.exit_code == 0, result.output
    assert requests[1]["path"] == "/external_issues/1/status"
    assert printed == [STATUS]


def test_issue_advisory_status_missing(monkeypatch):
    _patch(monkeypatch, list_items=[])

    result = CliRunner().invoke(issue, ["10", "advisory", "--status"])

    assert result.exit_code != 0
    assert "No security advisory found for this issue." in result.output


def test_issue_advisory_publish_and_delete_mutex(monkeypatch):
    _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "advisory", "--publish", "--delete"])

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()


def test_issue_advisory_status_and_publish_mutex(monkeypatch):
    _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "advisory", "--status", "--publish"])

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()


def test_issue_advisory_status_and_delete_mutex(monkeypatch):
    _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "advisory", "--status", "--delete"])

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()


def test_external_issue_wrapper_history_renders():
    _clear_output_flags()
    console = Console(record=True, width=200, soft_wrap=True)
    console.print(ExternalIssueWrapper(ADVISORY, history=HISTORY))
    text = console.export_text()

    assert "Description" in text
    assert "History" in text
    assert text.index("desc") < text.index("History")
    assert 'alice said "confirmed SSRF via httpx"' in text
    assert "alice changed the status to tp" in text


def test_external_issue_wrapper_history_hidden_when_empty():
    _clear_output_flags()
    console = Console(record=True, width=200)
    console.print(ExternalIssueWrapper(ADVISORY, history=[]))
    text = console.export_text()

    assert "History" not in text
