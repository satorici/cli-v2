from click.testing import CliRunner

from satori_cli.commands.issue import issue

COMMENT = {
    "kind": "comment",
    "id": 42,
    "body": "hello",
    "created_at": "2026-09-01T10:00:00.123456Z",
    "edited_at": None,
    "user_id": 7,
}


class _FakeResponse:
    def __init__(self, data=None):
        self._data = data if data is not None else COMMENT

    def json(self):
        return self._data


def _patch(monkeypatch):
    request = {}
    printed = []

    def post(path, json=None, timeout=None):
        request["method"] = "POST"
        request["path"] = path
        request["json"] = json
        request["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("satori_cli.commands.issue.client.post", post)
    monkeypatch.setattr(
        "satori_cli.commands.issue.stdout.print",
        lambda *args: printed.extend(args),
    )
    monkeypatch.setattr(
        "satori_cli.commands.issue.stdout.print_json",
        lambda data: printed.append(data),
    )
    return request, printed


def test_issue_comment_create(monkeypatch):
    request, printed = _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "comment", "hello"])

    assert result.exit_code == 0, result.output
    assert request["method"] == "POST"
    assert request["path"] == "/findings/10/comments"
    assert request["json"] == {"body": "hello"}
    assert printed == ["Comment 42 added to issue 10"]


def test_issue_comment_json(monkeypatch):
    request, printed = _patch(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "comment", "hello", "--json"])

    assert result.exit_code == 0, result.output
    assert request["path"] == "/findings/10/comments"
    assert request["json"] == {"body": "hello"}
    assert printed == [COMMENT]
