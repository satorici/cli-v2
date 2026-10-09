from pathlib import Path

import pytest
from click.testing import CliRunner

from satori_cli.commands.issue import issue
from satori_cli.utils import verify_issue as verify_mod

FINDING = {
    "id": 10,
    "execution_id": 100,
    "title": "SQL injection in login",
    "status": "OPEN",
    "source": "TOOL",
    "severity": 3,
    "identity": "sqli:login",
    "snapshot": {"cwe": "CWE-89", "file": "app/login.py"},
}

EXECUTION = {"id": 100, "job_id": 50}

SCAN_JOB = {
    "id": 50,
    "type": "SCAN",
    "repository_data": {"repository": "acme/app"},
}

RUN_JOB = {
    "id": 50,
    "type": "RUN",
    "repository": "acme/app",
}

LOCAL_JOB = {
    "id": 50,
    "type": "LOCAL",
}

LOCAL_JOB_WITH_REPO = {
    "id": 50,
    "type": "LOCAL",
    "repository": "acme/app",
}


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _FakeTempDir:
    def __init__(self, path: Path):
        self.name = str(path)
        path.mkdir(parents=True, exist_ok=True)

    def __enter__(self):
        return self.name

    def __exit__(self, *args):
        return False


def _responses(finding=FINDING, execution=EXECUTION, job=SCAN_JOB):
    by_prefix = {
        "/findings/": finding,
        "/executions/": execution,
        "/jobs/": job,
    }

    def get(path, **kwargs):
        for prefix, data in by_prefix.items():
            if path.startswith(prefix):
                return _FakeResponse(data)
        raise AssertionError(f"Unexpected GET {path}")

    return get


def _patch_binaries(monkeypatch, which=None):
    which = which or (lambda name: f"/bin/{name}")
    monkeypatch.setattr("satori_cli.utils.git_clone.shutil.which", which)
    monkeypatch.setattr("satori_cli.utils.verify_issue.shutil.which", which)


def _patch_subprocess(monkeypatch, fake_run):
    monkeypatch.setattr("satori_cli.utils.git_clone.subprocess.run", fake_run)
    monkeypatch.setattr("satori_cli.utils.verify_issue.subprocess.run", fake_run)


def test_repository_from_job_scan():
    assert verify_mod.repository_from_job(SCAN_JOB) == "acme/app"


def test_repository_from_job_run():
    assert verify_mod.repository_from_job(RUN_JOB) == "acme/app"


def test_repository_from_job_local_without_repo():
    assert verify_mod.repository_from_job(LOCAL_JOB) is None


def test_repository_from_job_local_with_repo():
    assert verify_mod.repository_from_job(LOCAL_JOB_WITH_REPO) == "acme/app"


def test_build_verify_prompt_includes_majority_and_commands():
    prompt = verify_mod.build_verify_prompt(FINDING, "acme/app")
    assert "id: 10" in prompt
    assert "SQL injection in login" in prompt
    assert "acme/app" in prompt
    assert "3 independent Agent" in prompt
    assert "majority" in prompt.lower()
    assert "satori-v2 issue 10 comment" in prompt
    assert 'comment "Conclusion:' in prompt
    assert "Do not print a separate verification summary" in prompt
    assert "Do not include per-agent analysis" in prompt
    assert "satori-v2 issue 10 status TP" in prompt
    assert "CWE-89" in prompt


def test_issue_verify_scan_happy_path(monkeypatch, tmp_path):
    gets: list[str] = []
    runs: list[dict[str, object]] = []

    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.client.get",
        lambda path, **kw: (gets.append(path) or _responses()(path)),
    )
    _patch_binaries(monkeypatch)

    def fake_run(args, cwd=None, stdout=None, stderr=None):
        runs.append({"args": list(args), "cwd": cwd})
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True, exist_ok=True)
        return type("R", (), {"returncode": 0})()

    _patch_subprocess(monkeypatch, fake_run)
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.tempfile.TemporaryDirectory",
        lambda prefix="": _FakeTempDir(tmp_path / "work"),
    )

    result = CliRunner().invoke(issue, ["10", "verify"])

    assert result.exit_code == 0, result.output
    assert gets == ["/findings/10", "/executions/100", "/jobs/50"]
    assert len(runs) == 2
    clone_args = runs[0]["args"]
    claude_args = runs[1]["args"]
    claude_cwd = runs[1]["cwd"]
    assert isinstance(clone_args, list)
    assert isinstance(claude_args, list)
    assert isinstance(claude_cwd, str)
    assert clone_args[1:4] == ["clone", "--depth", "1"]
    assert "github.com/acme/app.git" in clone_args[4]
    assert claude_args[0] == "/bin/claude"
    assert claude_args[1] == "-p"
    prompt = claude_args[2]
    assert "3 independent Agent" in prompt
    assert "satori-v2 issue 10 comment" in prompt
    assert 'comment "Conclusion:' in prompt
    assert "Do not print a separate verification summary" in prompt
    assert "satori-v2 issue 10 status TP" in prompt
    assert "--allowedTools" in claude_args
    assert "--no-session-persistence" in claude_args
    assert claude_args[claude_args.index("--model") + 1] == "sonnet"
    assert claude_args[claude_args.index("--effort") + 1] == "low"
    assert Path(claude_cwd).name == "app"
    assert str(tmp_path / "work") in claude_cwd


def test_issue_verify_run_job(monkeypatch, tmp_path):
    runs: list[dict[str, object]] = []
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.client.get",
        _responses(job=RUN_JOB),
    )
    _patch_binaries(monkeypatch)

    def fake_run(args, cwd=None, stdout=None, stderr=None):
        runs.append({"args": list(args), "cwd": cwd})
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True, exist_ok=True)
        return type("R", (), {"returncode": 0})()

    _patch_subprocess(monkeypatch, fake_run)
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.tempfile.TemporaryDirectory",
        lambda prefix="": _FakeTempDir(tmp_path / "work"),
    )

    result = CliRunner().invoke(issue, ["10", "verify"])

    assert result.exit_code == 0, result.output
    clone_args = runs[0]["args"]
    assert isinstance(clone_args, list)
    assert "github.com/acme/app.git" in clone_args[4]


def test_issue_verify_local_job(monkeypatch, tmp_path):
    runs: list[dict[str, object]] = []
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.client.get",
        _responses(job=LOCAL_JOB_WITH_REPO),
    )
    _patch_binaries(monkeypatch)

    def fake_run(args, cwd=None, stdout=None, stderr=None):
        runs.append({"args": list(args), "cwd": cwd})
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True, exist_ok=True)
        return type("R", (), {"returncode": 0})()

    _patch_subprocess(monkeypatch, fake_run)
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.tempfile.TemporaryDirectory",
        lambda prefix="": _FakeTempDir(tmp_path / "work"),
    )

    result = CliRunner().invoke(issue, ["10", "verify"])

    assert result.exit_code == 0, result.output
    clone_args = runs[0]["args"]
    assert isinstance(clone_args, list)
    assert "github.com/acme/app.git" in clone_args[4]


def test_issue_verify_missing_repo(monkeypatch):
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.client.get",
        _responses(job=LOCAL_JOB),
    )
    _patch_binaries(monkeypatch)

    result = CliRunner().invoke(issue, ["10", "verify"])

    assert result.exit_code != 0
    assert "no associated repository" in result.output


def test_issue_verify_missing_claude(monkeypatch):
    monkeypatch.setattr(
        "satori_cli.utils.git_clone.shutil.which",
        lambda name: "/bin/git" if name == "git" else None,
    )
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.shutil.which",
        lambda name: "/bin/git" if name == "git" else None,
    )

    result = CliRunner().invoke(issue, ["10", "verify"])

    assert result.exit_code != 0
    assert "claude" in result.output.lower()


def test_issue_verify_missing_git(monkeypatch):
    _patch_binaries(monkeypatch, which=lambda name: None)

    result = CliRunner().invoke(issue, ["10", "verify"])

    assert result.exit_code != 0
    assert "git" in result.output.lower()


def test_issue_verify_claude_nonzero(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.client.get",
        _responses(),
    )
    _patch_binaries(monkeypatch)

    def fake_run(args, cwd=None, stdout=None, stderr=None):
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True, exist_ok=True)
            return type("R", (), {"returncode": 0})()
        return type("R", (), {"returncode": 7})()

    _patch_subprocess(monkeypatch, fake_run)
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.tempfile.TemporaryDirectory",
        lambda prefix="": _FakeTempDir(tmp_path / "work"),
    )

    result = CliRunner().invoke(issue, ["10", "verify"])

    assert result.exit_code != 0
    assert "exited with status 7" in result.output


def test_list_finding_ids_for_execution_paginates(monkeypatch):
    pages = {
        1: {
            "items": [{"id": 1}, {"id": 2}],
            "total": 3,
        },
        2: {
            "items": [{"id": 3}],
            "total": 3,
        },
    }
    calls: list[dict] = []

    def get(path, params=None, **kwargs):
        assert path == "/findings"
        assert params is not None
        calls.append(dict(params))
        return _FakeResponse(pages[params["page"]])

    monkeypatch.setattr("satori_cli.utils.verify_issue.client.get", get)
    monkeypatch.setattr("satori_cli.utils.verify_issue._FINDINGS_PAGE_SIZE", 2)

    assert verify_mod.list_finding_ids_for_execution(100) == [1, 2, 3]
    assert calls == [
        {"execution_id": 100, "page": 1, "quantity": 2},
        {"execution_id": 100, "page": 2, "quantity": 2},
    ]


def test_verify_findings_clones_once_and_runs_claude_per_finding(
    monkeypatch, tmp_path
):
    finding_b = {**FINDING, "id": 11, "title": "XSS"}
    by_id = {10: FINDING, 11: finding_b}
    runs: list[dict[str, object]] = []

    def get(path, **kwargs):
        if path.startswith("/findings/"):
            fid = int(path.rsplit("/", 1)[-1])
            return _FakeResponse(by_id[fid])
        if path.startswith("/executions/"):
            return _FakeResponse(EXECUTION)
        if path.startswith("/jobs/"):
            return _FakeResponse(SCAN_JOB)
        raise AssertionError(f"Unexpected GET {path}")

    monkeypatch.setattr("satori_cli.utils.verify_issue.client.get", get)
    _patch_binaries(monkeypatch)

    def fake_run(args, cwd=None, stdout=None, stderr=None):
        runs.append({"args": list(args), "cwd": cwd})
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True, exist_ok=True)
        return type("R", (), {"returncode": 0})()

    _patch_subprocess(monkeypatch, fake_run)
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.tempfile.TemporaryDirectory",
        lambda prefix="": _FakeTempDir(tmp_path / "work"),
    )

    verify_mod.verify_findings([10, 11])

    clone_runs = [r for r in runs if r["args"][1] == "clone"]
    claude_runs = [r for r in runs if r["args"][0] == "/bin/claude"]
    assert len(clone_runs) == 1
    assert len(claude_runs) == 2
    assert "satori-v2 issue 10 comment" in claude_runs[0]["args"][2]
    assert "satori-v2 issue 11 comment" in claude_runs[1]["args"][2]


def test_verify_findings_continues_then_raises_on_failures(monkeypatch, tmp_path):
    finding_b = {**FINDING, "id": 11}
    by_id = {10: FINDING, 11: finding_b}
    claude_calls = 0

    def get(path, **kwargs):
        if path.startswith("/findings/"):
            fid = int(path.rsplit("/", 1)[-1])
            return _FakeResponse(by_id[fid])
        if path.startswith("/executions/"):
            return _FakeResponse(EXECUTION)
        if path.startswith("/jobs/"):
            return _FakeResponse(SCAN_JOB)
        raise AssertionError(f"Unexpected GET {path}")

    monkeypatch.setattr("satori_cli.utils.verify_issue.client.get", get)
    _patch_binaries(monkeypatch)

    def fake_run(args, cwd=None, stdout=None, stderr=None):
        nonlocal claude_calls
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True, exist_ok=True)
            return type("R", (), {"returncode": 0})()
        claude_calls += 1
        return type("R", (), {"returncode": 3 if claude_calls == 1 else 5})()

    _patch_subprocess(monkeypatch, fake_run)
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.tempfile.TemporaryDirectory",
        lambda prefix="": _FakeTempDir(tmp_path / "work"),
    )

    with pytest.raises(Exception, match="failed for 2 finding") as exc:
        verify_mod.verify_findings([10, 11])
    assert claude_calls == 2
    assert "10 (exit 3)" in str(exc.value)
    assert "11 (exit 5)" in str(exc.value)
