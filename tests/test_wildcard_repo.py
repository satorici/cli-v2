import asyncio
import io

import pytest
from click.testing import CliRunner
from rich.console import Console

from satori_cli.commands.local import local
from satori_cli.commands.run import run
from satori_cli.commands.scan import scan
from satori_cli.mcp_server import server
from satori_cli.utils.repo import (
    is_wildcard_repo,
    normalize_repo_target,
    wildcard_owner,
)
from satori_cli.utils.wrappers import JobWrapper, _wildcard_scan_rows, command_generator


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _wildcard_scan(**data) -> dict:
    return {
        "id": 99,
        "type": "SCAN",
        "playbook_source": "repo://.satori.yml",
        "visibility": "PRIVATE",
        "created_at": "2026-01-01T00:00:00Z",
        "repository_data": {"repository": "satorici/*", "wildcard": True, **data},
        "criteria": {"quantity": 1},
        "status": "FETCHING_DATA",
    }


@pytest.mark.parametrize(
    ("value", "owner"),
    [
        ("satorici", "satorici"),
        ("satorici/*", "satorici"),
        ("satorici/satori-cli", None),
        ("./satorici", None),
        ("bad_owner", None),
    ],
)
def test_wildcard_owner(value, owner):
    assert wildcard_owner(value) == owner


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("satorici", "satorici/*"),
        ("satorici/*", "satorici/*"),
        ("satorici/satori-cli", "satorici/satori-cli"),
    ],
)
def test_normalize_repo_target(value, expected):
    assert normalize_repo_target(value) == expected
    assert is_wildcard_repo(expected) == expected.endswith("/*")


@pytest.fixture
def scan_post(monkeypatch):
    request = {}

    def post(path, json):
        request["path"] = path
        request["body"] = json
        return _FakeResponse(_wildcard_scan())

    monkeypatch.setattr("satori_cli.commands.run.client.post", post)
    monkeypatch.setattr("satori_cli.commands.run.stdout.print", lambda *args: None)
    return request


@pytest.mark.parametrize("repo", ["satorici", "satorici/*"])
def test_run_repo_owner_creates_wildcard_scan(monkeypatch, scan_post, repo):
    def no_wait(*args, **kwargs):
        raise AssertionError("wildcard executions only exist once it is RUNNING")

    monkeypatch.setattr("satori_cli.commands.run._wait_execution_ids_for_job", no_wait)

    result = CliRunner().invoke(run, ["--repo", repo])

    assert result.exit_code == 0, result.output
    assert scan_post["path"] == "/jobs/scans"
    assert scan_post["body"]["repository_data"] == {"repository": "satorici/*"}
    assert scan_post["body"]["criteria"] == {"quantity": 1}
    assert "playbook_source" not in scan_post["body"]


def test_run_positional_wildcard_requires_repo_flag(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "satori_cli.commands.run.client.post",
        lambda *a, **k: pytest.fail("must not create a job"),
    )

    result = CliRunner().invoke(run, ["satorici/*"])

    assert result.exit_code != 0
    assert "--repo satorici/*" in result.output


def test_run_positional_owner_is_not_a_scan(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "satori_cli.commands.run.client.post",
        lambda *a, **k: pytest.fail("must not create a job"),
    )

    result = CliRunner().invoke(run, ["satorici"])

    assert result.exit_code != 0
    assert str(result.exception) == "Source not supported"


def test_run_existing_owner_named_dir_still_runs_locally(monkeypatch, tmp_path):
    request = {}
    (tmp_path / "satorici").mkdir()

    def post(path, json):
        request["path"] = path
        return _FakeResponse({"id": 42, "files_upload": None})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("satori_cli.commands.run.client.post", post)
    monkeypatch.setattr(
        "satori_cli.commands.run._wait_execution_ids_for_job", lambda *a, **k: [1]
    )
    monkeypatch.setattr("satori_cli.commands.run.stdout.print", lambda *args: None)

    result = CliRunner().invoke(
        run, ["satorici", "-p", "satori://code/python/pyspector_v2.yml"]
    )

    assert result.exit_code == 0, result.output
    assert request["path"] == "/jobs/runs"


def test_run_repo_wildcard_output_shows_every_execution(monkeypatch, scan_post):
    shown = []
    warnings = []

    def get(path, params=None):
        if path == "/jobs/99":
            return _FakeResponse(
                _wildcard_scan(
                    skipped=[
                        {"repository": "satorici/x", "reason": "no root .satori.yml"}
                    ]
                )
            )
        assert path == "/executions"
        assert params == {"job_id": 99, "quantity": 100}
        return _FakeResponse({"items": [{"id": 1}, {"id": 2}]})

    monkeypatch.setattr("satori_cli.commands.run.client.get", get)
    monkeypatch.setattr(
        "satori_cli.commands.run.wait_job_until_finished", lambda job_id: None
    )
    monkeypatch.setattr(
        "satori_cli.commands.run.stderr.print", lambda msg, *a: warnings.append(msg)
    )
    monkeypatch.setattr(
        "satori_cli.commands.run.show_execution_output", lambda i, *a: shown.append(i)
    )

    result = CliRunner().invoke(run, ["--repo", "satorici", "--output"])

    assert result.exit_code == 0, result.output
    assert shown == [1, 2]
    assert "WARNING: skipped satorici/x: no root .satori.yml" in warnings


def test_scan_owner_creates_wildcard_scan(monkeypatch):
    request = {}

    def post(path, json):
        request["body"] = json
        return _FakeResponse(_wildcard_scan())

    monkeypatch.setattr("satori_cli.commands.scan.client.post", post)
    monkeypatch.setattr("satori_cli.commands.scan.stdout.print", lambda *args: None)

    result = CliRunner().invoke(scan, ["satorici"])

    assert result.exit_code == 0, result.output
    assert request["body"]["repository_data"] == {"repository": "satorici/*"}


def test_scan_wildcard_rejects_history():
    result = CliRunner().invoke(scan, ["satorici/*", "-q", "2"])

    assert result.exit_code != 0
    assert "--quantity must be 1" in result.output


def test_local_rejects_wildcard(tmp_path):
    playbook = tmp_path / "playbook.yml"
    playbook.write_text("{ cmd: [echo hi] }\n")

    result = CliRunner().invoke(local, ["--repo", "satorici/*", str(playbook)])

    assert result.exit_code != 0
    assert "wildcard is not supported on local" in result.output


def test_mcp_scan_repository_accepts_wildcard(monkeypatch):
    seen = {}

    def post(url, **kw):
        seen["body"] = kw["json"]
        return _FakeResponse({"id": 5, "status": "FETCHING_DATA"})

    monkeypatch.setattr(server.client, "post", post)

    result = server.scan_repository("satorici/*", quantity=5)

    assert result["job_id"] == 5
    assert seen["body"]["repository_data"] == {"repository": "satorici/*"}
    assert seen["body"]["criteria"] == {"quantity": 1}
    assert "owner/repo" in server.scan_repository("satorici")["error"]


def test_mcp_run_local_rejects_wildcard():
    result = asyncio.run(server.run_local(playbook_yaml="x", repository="satorici/*"))
    assert result["error"] == "wildcard is not supported on local"


def test_command_generator_wildcard_scan():
    assert command_generator(_wildcard_scan()) == "satori-v2 scan 'satorici/*' -q 1"


def test_wildcard_scan_rows(monkeypatch):
    job = _wildcard_scan(
        repositories=["satorici/a", "satorici/b"],
        skipped=[{"repository": "satorici/c", "reason": "not accessible"}],
        truncated=3,
    )
    assert _wildcard_scan_rows(job) == [
        ("Repositories", "2"),
        ("Skipped", "satorici/c: not accessible"),
        ("Not scanned", "3 more over the limit"),
    ]
    assert _wildcard_scan_rows({"repository_data": {"repository": "o/r"}}) == []

    # Other tests can leave the JSON output format configured
    monkeypatch.setattr("satori_cli.utils.wrappers.is_json_output", lambda: False)
    console = Console(file=io.StringIO(), width=120)
    console.print(JobWrapper(job))
    assert "satorici/c: not accessible" in console.file.getvalue()


def test_scan_id_with_option_shows_scan_instead_of_creating(monkeypatch):
    monkeypatch.setattr(
        "satori_cli.commands.scan.client.post",
        lambda *a, **k: pytest.fail("must not create a scan"),
    )
    monkeypatch.setattr(
        "satori_cli.commands.scan.client.get",
        lambda path: _FakeResponse(_wildcard_scan()),
    )
    monkeypatch.setattr("satori_cli.commands.scan.stdout.print", lambda *args: None)

    result = CliRunner().invoke(scan, ["99", "--json"])

    assert result.exit_code == 0, result.output
