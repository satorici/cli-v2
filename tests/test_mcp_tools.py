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


def test_list_executions_maps_params_and_caps_quantity(monkeypatch):
    seen = {}

    def get(url, params=None, **kw):
        seen.update(params)
        return _Resp(
            {
                "items": [
                    {
                        "id": 5,
                        "status": "FINISHED",
                        "job_id": 2,
                        "job": {"type": "RUN"},
                        "report": {"total_fails": 1},
                    }
                ],
                "total": 60,
            }
        )

    monkeypatch.setattr(server.client, "get", get)
    result = server.list_executions(
        job_id=2, status=["FINISHED"], from_="2026-01-01", to="2026-02-01", quantity=500
    )
    assert seen["quantity"] == 25
    assert seen["from"] == "2026-01-01" and seen["job_id"] == 2
    assert seen["order"] == "DESC"
    assert result["next_page"] == 2
    assert result["items"][0]["total_fails"] == 1
    assert result["items"][0]["job_type"] == "RUN"


def test_list_executions_validates_input():
    assert "report_status" in server.list_executions(report_status="MAYBE")["error"]
    assert "job_type" in server.list_executions(job_type="X")["error"]
    assert "earlier" in server.list_executions(from_="2026-02-01", to="2026-01-01")["error"]


def test_list_reports_aliases_list_executions(monkeypatch):
    seen = {}

    def get(url, params=None, **kw):
        seen.update(params or {})
        return _Resp({"items": [{"id": 1, "status": "FINISHED", "report": {}}], "total": 1})

    monkeypatch.setattr(server.client, "get", get)
    result = server.list_reports(job_id=9, quantity=10)
    assert seen["job_id"] == 9 and seen["quantity"] == 10
    assert result["items"][0]["id"] == 1


def test_stop_execution_only_patches_running(monkeypatch):
    patches = []
    status = {"v": "FINISHED"}
    monkeypatch.setattr(
        server.client, "get", lambda url, **kw: _Resp({"status": status["v"]})
    )
    monkeypatch.setattr(
        server.client, "patch", lambda url, **kw: patches.append((url, kw)) or _Resp()
    )

    assert server.stop_execution(3)["stopped"] is False
    assert patches == []

    status["v"] = "RUNNING"
    assert server.stop_execution(3)["stopped"] is True
    assert patches == [("/executions/3", {"json": {"status": "CANCELED"}})]


def test_get_execution_playbook_truncates(monkeypatch):
    big = "x" * (server.shaping.MAX_PLAYBOOK_CHARS + 10)
    monkeypatch.setattr(server.client, "get", lambda url, **kw: _Resp(text=big))
    result = server.get_execution_playbook(4)
    assert result["truncated"] is True
    assert "truncated" in result["yaml"]

    monkeypatch.setattr(server.client, "get", lambda url, **kw: _Resp(text="a: 1"))
    assert server.get_execution_playbook(4) == {
        "execution_id": 4,
        "yaml": "a: 1",
        "truncated": False,
    }
