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
    monkeypatch.setattr("satori_cli.commands.run.stdout.print", lambda *args: None)
    monkeypatch.setattr(Source, "upload_files", upload_files)

    result = CliRunner().invoke(run, [alias])

    assert result.exit_code == 0
    assert request["path"] == "/jobs/runs"
    assert request["body"]["playbook_source"] == playbook_uri
    assert request["body"]["with_files"] is True
    assert request["body"]["expire"] is None
    assert uploaded == {"source": "./", "data": {"url": "upload"}}


def test_run_forwards_expire(monkeypatch, tmp_path):
    request = {}

    def post(path, json):
        request["body"] = json
        return _FakeResponse({"id": 42, "files_upload": None})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("satori_cli.commands.run.client.post", post)
    monkeypatch.setattr("satori_cli.commands.run.stdout.print", lambda *args: None)

    result = CliRunner().invoke(run, ["pyspector", "--expire", "2 weeks"])

    assert result.exit_code == 0
    assert request["body"]["expire"] == "2 weeks"


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


def test_run_help_lists_repo_alias():
    result = CliRunner().invoke(run, ["--help"])

    assert result.exit_code == 0
    assert "--repo" in result.output
    assert "--repository" in result.output
