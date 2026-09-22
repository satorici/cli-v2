from click.testing import CliRunner
from rich.console import Console

from satori_cli.commands.issue import issue
from satori_cli.config import config
from satori_cli.utils.wrappers import IssueWrapper

FINDING = {
    "id": 333,
    "created_at": "2026-09-21T00:00:00.123456Z",
    "execution_id": 42,
    "source": "PLAYBOOK",
    "identity": {"tool": "semgrep"},
    "fingerprint": "abc",
    "title": "SQL Injection",
    "status": "CONFIRMED",
    "severity": 3,
    "snapshot": {"cwe": "CWE-89"},
    "assignee_id": None,
    "user_id": 7,
}

HISTORY = [
    {
        "kind": "comment",
        "id": 1,
        "body": "esta vulnerabilidad esta confirmada por cierta razon",
        "created_at": "2026-09-21T00:00:00Z",
        "edited_at": None,
        "user_id": 7,
        "display_name": "alice",
    },
    {
        "kind": "event",
        "id": 2,
        "created_at": "2026-09-21T00:01:00Z",
        "finding_id": 333,
        "type": "STATUS_CHANGED",
        "payload": {"from": "OPEN", "to": "CONFIRMED"},
        "display_name": "alice",
    },
]


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def _clear_output_flags():
    config._current_config.pop("json", None)
    config._current_config.pop("format", None)


def _patch_view(monkeypatch, history=None):
    _clear_output_flags()
    requests = []
    printed = []

    def get(path, params=None):
        requests.append({"path": path, "params": params})
        if path.endswith("/timeline"):
            return _FakeResponse(history if history is not None else HISTORY)
        return _FakeResponse(FINDING)

    monkeypatch.setattr("satori_cli.commands.issue.client.get", get)
    monkeypatch.setattr(
        "satori_cli.commands.issue.stdout.print",
        lambda *args: printed.extend(args),
    )
    return requests, printed


def test_issue_view_fetches_timeline(monkeypatch):
    requests, printed = _patch_view(monkeypatch)

    result = CliRunner().invoke(issue, ["333"])

    assert result.exit_code == 0, result.output
    assert [r["path"] for r in requests] == [
        "/findings/333",
        "/findings/333/timeline",
    ]
    assert len(printed) == 1
    wrapper = printed[0]
    assert isinstance(wrapper, IssueWrapper)
    assert wrapper.obj["history"] == HISTORY


def test_issue_view_json_includes_history(monkeypatch):
    requests, printed = _patch_view(monkeypatch)

    result = CliRunner().invoke(issue, ["333", "--json"])

    assert result.exit_code == 0, result.output
    assert [r["path"] for r in requests] == [
        "/findings/333",
        "/findings/333/timeline",
    ]
    wrapper = printed[0]
    assert isinstance(wrapper, IssueWrapper)
    assert wrapper.obj["id"] == 333
    assert wrapper.obj["history"] == HISTORY


def test_issue_history_renders():
    _clear_output_flags()
    console = Console(record=True, width=200, soft_wrap=True)
    console.print(IssueWrapper(FINDING, history=HISTORY))
    text = console.export_text()

    assert "History" in text
    assert 'alice said "esta vulnerabilidad' in text
    assert "alice changed the status to confirmed" in text
    assert "2026-09-21 00:00" in text
    assert "2026-09-21 00:01" in text


def test_issue_history_created_event():
    _clear_output_flags()
    history = [
        {
            "kind": "comment",
            "id": 1,
            "body": "hello",
            "created_at": "2026-09-21T00:00:00Z",
            "edited_at": None,
            "user_id": 7,
        },
        {
            "kind": "event",
            "id": 2,
            "created_at": "2026-09-21T00:01:00Z",
            "finding_id": 333,
            "type": "CREATED",
            "payload": {},
        },
    ]
    console = Console(record=True, width=200)
    console.print(IssueWrapper(FINDING, history=history))
    text = console.export_text()

    assert '2026-09-21 00:00 said "hello"' in text
    assert "2026-09-21 00:01 created the issue" in text


def test_issue_history_hidden_when_empty():
    _clear_output_flags()
    console = Console(record=True, width=200)
    console.print(IssueWrapper(FINDING, history=[]))
    text = console.export_text()

    assert "History" not in text
