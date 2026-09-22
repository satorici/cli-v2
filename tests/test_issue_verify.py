from pathlib import Path

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


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


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


def test_repository_from_job_scan():
    assert verify_mod.repository_from_job(SCAN_JOB) == "acme/app"


def test_repository_from_job_run():
    assert verify_mod.repository_from_job(RUN_JOB) == "acme/app"


def test_repository_from_job_local():
    assert verify_mod.repository_from_job(LOCAL_JOB) is None


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
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.shutil.which",
        lambda name: f"/bin/{name}",
    )

    def fake_run(args, cwd=None, stdout=None, stderr=None):
        runs.append({"args": list(args), "cwd": cwd})
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True, exist_ok=True)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr("satori_cli.utils.verify_issue.subprocess.run", fake_run)
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
    assert Path(claude_cwd).name == "app"
    assert str(tmp_path / "work") in claude_cwd


def test_issue_verify_run_job(monkeypatch, tmp_path):
    runs: list[dict[str, object]] = []
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.client.get",
        _responses(job=RUN_JOB),
    )
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.shutil.which",
        lambda name: f"/bin/{name}",
    )

    def fake_run(args, cwd=None, stdout=None, stderr=None):
        runs.append({"args": list(args), "cwd": cwd})
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True, exist_ok=True)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr("satori_cli.utils.verify_issue.subprocess.run", fake_run)
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
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.shutil.which",
        lambda name: f"/bin/{name}",
    )

    result = CliRunner().invoke(issue, ["10", "verify"])

    assert result.exit_code != 0
    assert "no associated repository" in result.output


def test_issue_verify_missing_claude(monkeypatch):
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.shutil.which",
        lambda name: "/bin/git" if name == "git" else None,
    )

    result = CliRunner().invoke(issue, ["10", "verify"])

    assert result.exit_code != 0
    assert "claude" in result.output.lower()


def test_issue_verify_missing_git(monkeypatch):
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.shutil.which",
        lambda name: None,
    )

    result = CliRunner().invoke(issue, ["10", "verify"])

    assert result.exit_code != 0
    assert "git" in result.output.lower()


def test_issue_verify_claude_nonzero(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.client.get",
        _responses(),
    )
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.shutil.which",
        lambda name: f"/bin/{name}",
    )

    def fake_run(args, cwd=None, stdout=None, stderr=None):
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True, exist_ok=True)
            return type("R", (), {"returncode": 0})()
        return type("R", (), {"returncode": 7})()

    monkeypatch.setattr("satori_cli.utils.verify_issue.subprocess.run", fake_run)
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.tempfile.TemporaryDirectory",
        lambda prefix="": _FakeTempDir(tmp_path / "work"),
    )

    result = CliRunner().invoke(issue, ["10", "verify"])

    assert result.exit_code != 0
    assert "exited with status 7" in result.output


class _FakeTempDir:
    def __init__(self, path: Path):
        self.name = str(path)
        path.mkdir(parents=True, exist_ok=True)

    def __enter__(self):
        return self.name

    def __exit__(self, *args):
        return False
