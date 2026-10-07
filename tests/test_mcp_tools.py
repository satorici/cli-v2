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
    assert (
        "earlier"
        in server.list_executions(from_="2026-02-01", to="2026-01-01")["error"]
    )


def test_list_reports_aliases_list_executions(monkeypatch):
    seen = {}

    def get(url, params=None, **kw):
        seen.update(params or {})
        return _Resp(
            {"items": [{"id": 1, "status": "FINISHED", "report": {}}], "total": 1}
        )

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


def test_update_finding_status_rejects_invalid_without_calling_api(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("API must not be called")

    monkeypatch.setattr(server.client, "patch", boom)
    assert "status must be" in server.update_finding_status(1, "DONE")["error"]


def test_update_finding_status_sends_only_status_then_comment(monkeypatch):
    calls = []

    def patch(url, **kw):
        calls.append(("patch", url, kw["json"]))
        return _Resp({"status": "TP"})

    def post(url, **kw):
        calls.append(("post", url, kw["json"]))
        return _Resp({"id": 5})

    monkeypatch.setattr(server.client, "patch", patch)
    monkeypatch.setattr(server.client, "post", post)
    result = server.update_finding_status(3, "tp", comment="confirmed")
    assert calls == [
        ("patch", "/findings/3", {"status": "TP"}),
        ("post", "/findings/3/comments", {"body": "confirmed"}),
    ]
    assert result == {"id": 3, "status": "TP", "comment_id": 5}


def test_update_finding_status_comment_failure_keeps_status(monkeypatch):
    request = httpx2.Request("POST", "http://x")
    response = httpx2.Response(500, text="nope", request=request)

    def post(*a, **k):
        raise httpx2.HTTPStatusError("e", request=request, response=response)

    monkeypatch.setattr(server.client, "patch", lambda u, **k: _Resp({"status": "FP"}))
    monkeypatch.setattr(server.client, "post", post)
    result = server.update_finding_status(3, "FP", comment="x")
    assert result["status"] == "FP" and result["comment_error"] == "nope"


def test_get_finding_includes_capped_timeline(monkeypatch):
    def get(url, **kw):
        if url.endswith("/timeline"):
            return _Resp([{"kind": "event", "type": "T", "payload": {}}] * 100)
        return _Resp({"id": 1, "title": "t"})

    monkeypatch.setattr(server.client, "get", get)
    result = server.get_finding(1)
    assert len(result["timeline"]) == 20 and result["timeline_truncated"]
    assert "timeline" not in server.get_finding(1, include_timeline=False)


def test_list_jobs_caps_quantity_and_validates_type(monkeypatch):
    seen = {}

    def get(url, params=None, **kw):
        seen.update(params)
        return _Resp({"total": 100, "items": [{"id": 1, "type": "RUN"}]})

    monkeypatch.setattr(server.client, "get", get)
    result = server.list_jobs(type="RUN", quantity=500)
    assert seen["quantity"] == 25 and seen["type"] == "RUN"
    assert result["next_page"] == 2
    assert "type must be" in server.list_jobs(type="LOCAL")["error"]


def test_get_job_combines_job_and_recent_executions(monkeypatch):
    def get(url, **kw):
        if url == "/executions":
            return _Resp({"items": [{"id": 9, "status": "FINISHED"}]})
        return _Resp({"id": 4, "type": "SCAN", "status": "FINISHED"})

    monkeypatch.setattr(server.client, "get", get)
    result = server.get_job(4)
    assert result["type"] == "SCAN" and result["executions"][0]["id"] == 9


def test_run_playbook_accepts_catalog_uri_without_bundling(monkeypatch):
    posts = []

    def post(url, **kw):
        posts.append((url, kw["json"]["playbook_source"]))
        return _Resp({"id": 1, "status": "QUEUED"})

    monkeypatch.setattr(server.client, "post", post)
    monkeypatch.setattr(server.client, "get", lambda u, **k: _Resp({"items": []}))
    monkeypatch.setattr(server.time, "sleep", lambda s: None)
    server.run_playbook(playbook_uri="satori://code/x.yml", wait=False)
    assert posts == [("/jobs/runs", "satori://code/x.yml")]
    assert "satori://" in server.run_playbook(playbook_uri="https://evil/x")["error"]


def test_scan_repository_validates_and_caps(monkeypatch):
    assert (
        "owner/repo"
        in server.scan_repository("nope", playbook_uri="satori://a.yml")["error"]
    )
    assert "exactly one" in server.scan_repository("o/r")["error"]

    seen = {}

    def post(url, **kw):
        seen["url"], seen["body"] = url, kw["json"]
        return _Resp({"id": 3, "status": "QUEUED"})

    monkeypatch.setattr(server.client, "post", post)
    result = server.scan_repository("o/r", playbook_uri="satori://a.yml", quantity=99)
    assert seen["url"] == "/jobs/scans"
    assert seen["body"]["repository_data"] == {"repository": "o/r"}
    assert seen["body"]["criteria"] == {"quantity": 10}
    assert result["job_id"] == 3


def test_list_playbooks_filters_and_pages(monkeypatch):
    catalog = [
        {
            "uri": f"satori://api/p{i}.yml",
            "id": f"api/p{i}.yml",
            "name": f"P{i}",
            "category": "api",
            "description": "openapi" if i % 2 else "other",
        }
        for i in range(10)
    ] + [
        {
            "uri": "satori://code/c.yml",
            "id": "code/c.yml",
            "name": "C",
            "category": "code",
            "description": "",
        }
    ]
    monkeypatch.setattr(
        server.playbooks_client, "get", lambda u, **k: _Resp({"playbooks": catalog})
    )
    result = server.list_playbooks(q="OpenAPI", category="api", quantity=2)
    assert (
        result["total"] == 5 and len(result["items"]) == 2 and result["next_page"] == 2
    )
    assert "content" not in result["items"][0]


def test_get_playbook_clips_yaml(monkeypatch):
    data = {"uri": "satori://a.yml", "name": "A", "content": "x" * 100_000}
    monkeypatch.setattr(server.playbooks_client, "get", lambda u, **k: _Resp(data))
    result = server.get_playbook("satori://a.yml")
    assert result["truncated"] and len(result["yaml"]) < 20_100


def test_list_findings_source_and_order(monkeypatch):
    seen = {}

    def get(url, params=None, **kw):
        seen.update(params)
        return _Resp({"total": 0, "items": []})

    monkeypatch.setattr(server.client, "get", get)
    server.list_findings(source="tool", order="asc")
    assert seen["source"] == "TOOL" and seen["order"] == "ASC"
    assert "source must be" in server.list_findings(source="X")["error"]
    assert "order must be" in server.list_findings(order="up")["error"]


def test_list_advisories_validates_and_omits_long_text(monkeypatch):
    seen = {}

    def get(url, params=None, **kw):
        seen.update(url=url, **params)
        return _Resp(
            {
                "total": 1,
                "items": [
                    {"id": 1, "kind": "ISSUE", "title": "t", "description": "d" * 9999}
                ],
            }
        )

    monkeypatch.setattr(server.client, "get", get)
    result = server.list_advisories(kind="issue", execution_id=5, quantity=99)
    assert seen["url"] == "/external_issues" and seen["kind"] == "ISSUE"
    assert seen["quantity"] == 25 and seen["execution_id"] == 5
    assert "description" not in result["items"][0]
    assert "kind must be" in server.list_advisories(kind="PR")["error"]


def test_list_monitors_filters_monitor_jobs(monkeypatch):
    seen = {}

    def get(url, params=None, **kw):
        seen.update(params)
        return _Resp(
            {
                "total": 1,
                "items": [{"id": 1, "type": "MONITOR", "expression": "rate(1 hours)"}],
            }
        )

    monkeypatch.setattr(server.client, "get", get)
    result = server.list_monitors()
    assert seen["type"] == "MONITOR"
    assert result["items"][0]["expression"] == "rate(1 hours)"
