import pytest
from click.testing import CliRunner

from satori_cli.commands.run import _require_first_execution_id, run
from satori_cli.exceptions import SatoriError
from satori_cli.models import Source
from satori_cli.utils.arguments import _RunSourceParam


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_require_first_execution_id_returns_id(monkeypatch):
    monkeypatch.setattr(
        "satori_cli.commands.run.client.get",
        lambda *args, **kwargs: _FakeResponse({"items": [{"id": 42}]}),
    )
    assert _require_first_execution_id(1) == 42


def test_require_first_execution_id_raises_on_empty(monkeypatch):
    monkeypatch.setattr(
        "satori_cli.commands.run.client.get",
        lambda *args, **kwargs: _FakeResponse({"items": []}),
    )
    monkeypatch.setattr("satori_cli.commands.run.time.sleep", lambda *_: None)
    with pytest.raises(SatoriError, match="No executions found"):
        _require_first_execution_id(1)


@pytest.mark.parametrize(
    ("alias", "playbook_uri"),
    [
        ("pyspector", "satori://code/python/pyspector.yml"),
        ("semgrep", "satori://code/semgrep.yml"),
    ],
)
def test_run_playbook_alias_uses_current_directory(
    monkeypatch, tmp_path, alias, playbook_uri
):
    request = {}
    uploaded = {}

    def post(path, json):
        request["path"] = path
        request["body"] = json
        return _FakeResponse({"id": 42, "files_upload": {"url": "upload"}})

    def upload_files(self, data):
        uploaded["source"] = self._arg
        uploaded["data"] = data

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("satori_cli.commands.run.client.post", post)
    monkeypatch.setattr(
        "satori_cli.commands.run._wait_execution_ids_for_job", lambda *a, **k: [1]
    )
    monkeypatch.setattr("satori_cli.commands.run.stdout.print", lambda *args: None)
    monkeypatch.setattr(Source, "upload_files", upload_files)

    result = CliRunner().invoke(run, [alias])

    assert result.exit_code == 0
    assert request["path"] == "/jobs/runs"
    assert request["body"]["playbook_source"] == playbook_uri
    assert request["body"]["with_files"] is True
    assert request["body"]["expire"] is None
    assert request["body"]["notify"] is None
    assert uploaded == {"source": "./", "data": {"url": "upload"}}


def test_run_forwards_expire(monkeypatch, tmp_path):
    request = {}

    def post(path, json):
        request["body"] = json
        return _FakeResponse({"id": 42, "files_upload": None})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("satori_cli.commands.run.client.post", post)
    monkeypatch.setattr(
        "satori_cli.commands.run._wait_execution_ids_for_job", lambda *a, **k: [1]
    )
    monkeypatch.setattr("satori_cli.commands.run.stdout.print", lambda *args: None)

    result = CliRunner().invoke(run, ["pyspector", "--expire", "2 weeks"])

    assert result.exit_code == 0
    assert request["body"]["expire"] == "2 weeks"


def test_run_forwards_notify(monkeypatch, tmp_path):
    request = {}

    def post(path, json):
        request["body"] = json
        return _FakeResponse({"id": 42, "files_upload": None})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("satori_cli.commands.run.client.post", post)
    monkeypatch.setattr(
        "satori_cli.commands.run._wait_execution_ids_for_job", lambda *a, **k: [1]
    )
    monkeypatch.setattr("satori_cli.commands.run.stdout.print", lambda *args: None)

    result = CliRunner().invoke(
        run,
        [
            "pyspector",
            "--notify",
            "status=TP,severity=blocker,critical,high,result=fail,to=slack://ID1:ID2",
            "--notify",
            "result=pass,to=slack://ID1:ID3",
        ],
    )

    assert result.exit_code == 0, result.output
    assert request["body"]["notify"] == [
        {
            "result": "fail",
            "severity": ["blocker", "critical", "high"],
            "to": "slack://ID1:ID2",
        },
        {"result": "pass", "to": "slack://ID1:ID3"},
    ]


def test_run_rejects_bad_notify(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        run, ["pyspector", "--notify", "result=always,to=slack://T:C"]
    )
    assert result.exit_code != 0
    assert "notify" in result.output.lower() or "result" in result.output.lower()


def test_explicit_playbook_overrides_run_alias(monkeypatch, tmp_path):
    request = {}

    def post(path, json):
        request["body"] = json
        return _FakeResponse({"id": 42, "files_upload": None})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("satori_cli.commands.run.client.post", post)
    monkeypatch.setattr("satori_cli.commands.run.stdout.print", lambda *args: None)

    result = CliRunner().invoke(
        run, ["pyspector", "--playbook", "satori://custom.yml"]
    )

    assert result.exit_code == 0
    assert request["body"]["playbook_source"] == "satori://custom.yml"
    assert request["body"]["with_files"] is True


def test_run_alias_matching_is_exact(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(run, ["PySpector"])

    assert result.exit_code != 0
    assert isinstance(result.exception, SatoriError)
    assert str(result.exception) == "Source not supported"


def test_explicit_alias_path_is_not_converted(monkeypatch, tmp_path):
    source_dir = tmp_path / "pyspector"
    source_dir.mkdir()
    request = {}

    def post(path, json):
        request["body"] = json
        return _FakeResponse({"id": 42, "files_upload": None})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("satori_cli.commands.run.client.post", post)
    monkeypatch.setattr("satori_cli.commands.run.stdout.print", lambda *args: None)

    result = CliRunner().invoke(
        run, ["./pyspector", "--playbook", "satori://custom.yml"]
    )

    assert result.exit_code == 0
    assert request["body"]["playbook_source"] == "satori://custom.yml"
    assert request["body"]["with_files"] is True


@pytest.mark.parametrize(
    ("source_name", "expected_type"),
    [
        ("project", "DIR"),
        ("check.sh", "SCRIPT"),
        ("playbook.yml", "FILE"),
        ("satori://custom.yml", "URL"),
    ],
)
def test_run_source_param_preserves_regular_sources(
    monkeypatch, tmp_path, source_name, expected_type
):
    (tmp_path / "project").mkdir()
    (tmp_path / "check.sh").write_text("echo ok\n")
    (tmp_path / "playbook.yml").write_text("cmd: [echo ok]\n")
    monkeypatch.chdir(tmp_path)

    source = _RunSourceParam().convert(source_name, None, None)

    assert source.type == expected_type
    assert source._arg == source_name


def test_run_help_lists_playbook_aliases():
    result = CliRunner().invoke(run, ["--help"])

    assert result.exit_code == 0
    assert "pyspector" in result.output
    assert "semgrep" in result.output
    assert "--expire" in result.output
    assert "--notify" in result.output


@pytest.mark.parametrize("repo_flag", ["--repo", "--repository"])
def test_run_with_repo_creates_scan(monkeypatch, repo_flag):
    request = {}

    def post(path, json):
        request["path"] = path
        request["body"] = json
        return _FakeResponse(
            {
                "id": 99,
                "type": "SCAN",
                "playbook_source": "satori://code/python/pyspector_v2.yml",
                "visibility": "PRIVATE",
                "created_at": "2026-01-01T00:00:00Z",
                "repository_data": {"repository": "satorici/satori-cli"},
                "criteria": {"quantity": 1},
                "status": "FETCHING_DATA",
            }
        )

    monkeypatch.setattr("satori_cli.commands.run.client.post", post)
    monkeypatch.setattr("satori_cli.commands.run.stdout.print", lambda *args: None)

    result = CliRunner().invoke(
        run,
        [
            "satori://code/python/pyspector_v2.yml",
            repo_flag,
            "satorici/satori-cli",
        ],
    )

    assert result.exit_code == 0, result.output
    assert request["path"] == "/jobs/scans"
    assert request["body"]["playbook_source"] == "satori://code/python/pyspector_v2.yml"
    assert request["body"]["repository_data"] == {"repository": "satorici/satori-cli"}
    assert request["body"]["criteria"] == {"quantity": 1}


def test_run_with_repo_output_waits_and_shows(monkeypatch):
    waited = {}
    shown = {}

    def post(path, json):
        return _FakeResponse(
            {
                "id": 99,
                "type": "SCAN",
                "playbook_source": "satori://code/python/pyspector_v2.yml",
                "visibility": "PRIVATE",
                "created_at": "2026-01-01T00:00:00Z",
                "repository_data": {"repository": "satorici/satori-cli"},
                "criteria": {"quantity": 1},
                "status": "FETCHING_DATA",
            }
        )

    def wait(job_id):
        waited["job_id"] = job_id

    def show(execution_id, *args, **kwargs):
        shown["execution_id"] = execution_id

    monkeypatch.setattr("satori_cli.commands.run.client.post", post)
    monkeypatch.setattr("satori_cli.commands.run.stdout.print", lambda *args: None)
    monkeypatch.setattr("satori_cli.commands.run.stderr.print", lambda *args: None)
    monkeypatch.setattr("satori_cli.commands.run.wait_job_until_finished", wait)
    monkeypatch.setattr(
        "satori_cli.commands.run._require_first_execution_id", lambda job_id: 42
    )
    monkeypatch.setattr("satori_cli.commands.run.show_execution_output", show)

    result = CliRunner().invoke(
        run,
        [
            "satori://code/python/pyspector_v2.yml",
            "--repo",
            "satorici/satori-cli",
            "--output",
        ],
    )

    assert result.exit_code == 0, result.output
    assert waited == {"job_id": 99}
    assert shown == {"execution_id": 42}


def test_run_with_repo_verify_waits_and_verifies(monkeypatch):
    waited = {}
    verified = {}

    def post(path, json):
        return _FakeResponse(
            {
                "id": 99,
                "type": "SCAN",
                "playbook_source": "satori://code/python/pyspector_v2.yml",
                "visibility": "PRIVATE",
                "created_at": "2026-01-01T00:00:00Z",
                "repository_data": {"repository": "satorici/satori-cli"},
                "criteria": {"quantity": 1},
                "status": "FETCHING_DATA",
            }
        )

    def wait(job_id):
        waited["job_id"] = job_id

    def list_ids(execution_id):
        verified["listed"] = execution_id
        return [10, 11]

    def batch_verify(finding_ids):
        verified["finding_ids"] = finding_ids

    monkeypatch.setattr("satori_cli.commands.run.client.post", post)
    monkeypatch.setattr("satori_cli.commands.run.stdout.print", lambda *args: None)
    monkeypatch.setattr("satori_cli.commands.run.stderr.print", lambda *args: None)
    monkeypatch.setattr("satori_cli.commands.run.wait_job_until_finished", wait)
    monkeypatch.setattr(
        "satori_cli.commands.run._wait_execution_ids_for_job", lambda *a, **k: [42]
    )
    monkeypatch.setattr(
        "satori_cli.commands.run.list_finding_ids_for_execution", list_ids
    )
    monkeypatch.setattr(
        "satori_cli.commands.run.run_verify_findings", batch_verify
    )

    result = CliRunner().invoke(
        run,
        [
            "satori://code/python/pyspector_v2.yml",
            "--repo",
            "satorici/satori-cli",
            "--verify",
        ],
    )

    assert result.exit_code == 0, result.output
    assert waited == {"job_id": 99}
    assert verified == {"listed": 42, "finding_ids": [10, 11]}


def test_verify_executions_all_ids(monkeypatch):
    from satori_cli.commands.run import _verify_executions

    listed: list[int] = []
    verified_calls: list[list[int]] = []

    def list_ids(execution_id):
        listed.append(execution_id)
        return [100 + execution_id]

    def batch_verify(finding_ids):
        verified_calls.append(list(finding_ids))

    monkeypatch.setattr(
        "satori_cli.commands.run.list_finding_ids_for_execution", list_ids
    )
    monkeypatch.setattr(
        "satori_cli.commands.run.run_verify_findings", batch_verify
    )
    monkeypatch.setattr("satori_cli.commands.run.stderr.print", lambda *args: None)

    _verify_executions([1, 2])

    assert listed == [1, 2]
    assert verified_calls == [[101], [102]]


def test_verify_executions_skips_empty(monkeypatch):
    from satori_cli.commands.run import _verify_executions

    messages: list[str] = []
    verified_calls: list[list[int]] = []

    monkeypatch.setattr(
        "satori_cli.commands.run.list_finding_ids_for_execution",
        lambda execution_id: [],
    )
    monkeypatch.setattr(
        "satori_cli.commands.run.run_verify_findings",
        lambda finding_ids: verified_calls.append(list(finding_ids)),
    )
    monkeypatch.setattr(
        "satori_cli.commands.run.stderr.print",
        lambda *args: messages.append(" ".join(str(a) for a in args)),
    )

    _verify_executions([9])

    assert verified_calls == []
    assert any("No findings" in m for m in messages)


def test_run_help_lists_verify():
    result = CliRunner().invoke(run, ["--help"])

    assert result.exit_code == 0
    assert "--verify" in result.output


def test_run_help_lists_repo_alias():
    result = CliRunner().invoke(run, ["--help"])

    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "--repository" in result.output
