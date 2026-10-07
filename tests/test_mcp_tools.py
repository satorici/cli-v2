import httpx2

from satori_cli.mcp_server import server


class _Resp:
    def __init__(self, data=None, text=""):
        self._data, self.text = data, text

    def json(self):
        return self._data


def test_run_playbook_requires_exactly_one_source():
    assert "exactly one" in server.run_playbook()["error"]
    assert (
        "exactly one"
        in server.run_playbook(playbook_path="a.yml", playbook_yaml="x")["error"]
    )


def test_run_playbook_rejects_non_yml_path(tmp_path):
    f = tmp_path / "x.sh"
    f.write_text("echo")
    assert (
        "must be an existing .yml" in server.run_playbook(playbook_path=str(f))["error"]
    )


def test_run_playbook_inline_waits_and_summarizes(monkeypatch):
    posts = []

    def post(url, **kw):
        posts.append(url)
        if url == "/bundles":
            return _Resp(text="b1")
        return _Resp({"id": 7, "status": "QUEUED"})

    def get(url, **kw):
        if url == "/executions":
            return _Resp({"items": [{"id": 99}]})
        if url == "/jobs/7":
            return _Resp({"status": "FINISHED"})
        return _Resp(
            {"id": 99, "status": "FINISHED", "report": {"total_fails": 0, "detail": []}}
        )

    monkeypatch.setattr(
        server.BundleCache, "get_bundle_id", classmethod(lambda c, s: None)
    )
    monkeypatch.setattr(
        server.BundleCache, "set_bundle_id", classmethod(lambda c, s, b: None)
    )
    monkeypatch.setattr(server.client, "post", post)
    monkeypatch.setattr(server.client, "get", get)
    monkeypatch.setattr(server.time, "sleep", lambda s: None)

    result = server.run_playbook(playbook_yaml="test:\n  assertStdoutContains: x\n")
    assert posts == ["/bundles", "/jobs/runs"]
    assert result["execution_id"] == 99
    assert result["execution"]["total_fails"] == 0


def test_http_error_becomes_error_dict(monkeypatch):
    request = httpx2.Request("GET", "http://x")
    response = httpx2.Response(403, text="plan", request=request)

    def boom(*a, **k):
        raise httpx2.HTTPStatusError("e", request=request, response=response)

    monkeypatch.setattr(server.client, "get", boom)
    result = server.get_execution(1)
    assert result["status"] == 403 and "PRO" in result["hint"]


def test_output_without_test_returns_index_only(monkeypatch):
    monkeypatch.setattr(
        server,
        "load_execution_outputs",
        lambda i: [{"path": "cmd.0", "output": {"stdout": "a\nb"}}],
    )
    result = server.get_execution_output(1)
    assert result["tests"] == [{"path": "cmd.0", "stdout_lines": 2}]
    assert "text" not in result


def test_output_with_test_tails(monkeypatch):
    monkeypatch.setattr(
        server,
        "load_execution_outputs",
        lambda i: [
            {"path": "cmd.0", "output": {"stdout": "\n".join(map(str, range(50)))}}
        ],
    )
    result = server.get_execution_output(1, test="cmd.0", tail_lines=5)
    assert result["text"].splitlines() == ["45", "46", "47", "48", "49"]
    assert result["next_offset_from_end"] == 5
    stderr = server.get_execution_output(1, test="cmd.0.stderr")
    assert stderr["text"] == ""
