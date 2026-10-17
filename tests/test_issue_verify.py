import json
import re
import subprocess
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
    "identity": {"path": "app/login.py", "start_line": 42},
    "snapshot": {"cwe": "CWE-89", "filePath": "app/login.py", "lineNumber": 42},
}

EXECUTION = {"id": 100, "job_id": 50}
SCAN_JOB = {"id": 50, "type": "SCAN", "repository_data": {"repository": "acme/app"}}
RUN_JOB = {"id": 50, "type": "RUN", "repository": "acme/app"}
LOCAL_JOB = {"id": 50, "type": "LOCAL"}
LOCAL_JOB_WITH_REPO = {"id": 50, "type": "LOCAL", "repository": "acme/app"}


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
    by_prefix = {"/findings/": finding, "/executions/": execution, "/jobs/": job}

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


def _claude_stdout(prompt: str, verdict: str) -> str:
    """A Claude --output-format json envelope assigning `verdict` to every id in the prompt."""
    ids = [int(x) for x in re.findall(r"- id: (\d+)", prompt)]
    arr = [{"id": i, "verdict": verdict, "line": 1, "evidence": "x"} for i in ids]
    return json.dumps({"subtype": "success", "is_error": False, "result": json.dumps(arr)})


def _fake_run_factory(by_role, runs=None):
    """Fake subprocess.run: handles git clone and the claude calls, returning the verdict in
    by_role for the role found in --system-prompt."""

    def run(args, **kwargs):
        if runs is not None:
            runs.append(list(args))
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(args, 0, "", "")
        system = args[args.index("--system-prompt") + 1]
        if system.startswith(verify_mod.ANALYST):
            role = "analyst"
        elif system.startswith(verify_mod.ADVERSARY):
            role = "adversary"
        else:
            role = "tiebreak"
        return subprocess.CompletedProcess(
            args, 0, _claude_stdout(args[2], by_role[role]), ""
        )

    return run


def _patch_tempdir(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "satori_cli.utils.verify_issue.tempfile.TemporaryDirectory",
        lambda prefix="": _FakeTempDir(tmp_path / "work"),
    )


def test_repository_from_job_scan():
    assert verify_mod.repository_from_job(SCAN_JOB) == "acme/app"


def test_repository_from_job_run():
    assert verify_mod.repository_from_job(RUN_JOB) == "acme/app"


def test_repository_from_job_local_without_repo():
    assert verify_mod.repository_from_job(LOCAL_JOB) is None


def test_repository_from_job_local_with_repo():
    assert verify_mod.repository_from_job(LOCAL_JOB_WITH_REPO) == "acme/app"


def test_location_from_snapshot_then_identity():
    assert verify_mod._location(FINDING) == "app/login.py:42"
    assert verify_mod._location({"identity": {"path": "c/d.py", "start_line": 3}}) == "c/d.py:3"
    assert verify_mod._location({"snapshot": "bad"}) == "?:?"


def test_build_verify_prompt_puts_data_first_and_contract_last():
    prompt = verify_mod.build_verify_prompt([FINDING])
    assert "id: 10" in prompt
    assert "location: app/login.py:42" in prompt
    assert "SQL injection in login" in prompt
    assert "CWE-89" in prompt
    assert "JSON array" in prompt
    assert "Agent" not in prompt  # no 3-subagent instruction anymore
    assert prompt.index("id: 10") < prompt.index("JSON array")  # data before task


def test_verdicts_parses_array_and_tolerates_fences():
    assert verify_mod._verdicts('[{"id": 5, "verdict": "TP"}]') == {5: "TP"}
    assert verify_mod._verdicts('```json\n[{"id":5,"verdict":"FP"}]\n```') == {5: "FP"}
    assert verify_mod._verdicts("not json") is None
    assert verify_mod._verdicts('[{"id":1,"verdict":"maybe"}]') == {}


def test_verdicts_recovers_from_invalid_json():
    # a model echoed a source line with unescaped quotes into a field -> invalid JSON, but the
    # id+verdict pairs are still recovered rather than lost
    broken = '[{"id": 12, "verdict": "TP", "evidence": "os.system("rm " + u)"},' \
             ' {"id": 13, "verdict": "fp", "evidence": "re.compile("\\d+")"}]'
    assert verify_mod._verdicts(broken) == {12: "TP", 13: "FP"}
    # verdict-before-id order and surrounding prose are tolerated too
    assert verify_mod._verdicts('Done:\n[{"verdict":"TP","id":9}]') == {9: "TP"}


def test_judge_findings_agreement_skips_tiebreaker(monkeypatch, tmp_path):
    runs = []
    _patch_subprocess(monkeypatch, _fake_run_factory(
        {"analyst": "TP", "adversary": "TP"}, runs))
    verdicts = verify_mod.judge_findings([FINDING], tmp_path, "/bin/claude")
    assert verdicts == {10: "TP"}
    assert len(runs) == 2  # analyst + adversary only, no tie-breaker


def test_judge_findings_disagreement_uses_tiebreaker(monkeypatch, tmp_path):
    runs = []
    _patch_subprocess(monkeypatch, _fake_run_factory(
        {"analyst": "TP", "adversary": "FP", "tiebreak": "FP"}, runs))
    verdicts = verify_mod.judge_findings([FINDING], tmp_path, "/bin/claude")
    assert verdicts == {10: "FP"}
    assert len(runs) == 3  # analyst + adversary + tie-breaker


def test_claude_argv_caps_tools_and_replaces_system_prompt(monkeypatch, tmp_path):
    runs = []
    _patch_subprocess(monkeypatch, _fake_run_factory(
        {"analyst": "FP", "adversary": "FP"}, runs))
    verify_mod.judge_findings([FINDING], tmp_path, "/bin/claude")
    argv = runs[0]
    assert "--tools" in argv and {"Read", "Grep", "Glob"} <= set(argv)
    assert "--append-system-prompt" not in argv
    assert "--no-session-persistence" in argv
    assert "Agent" not in argv  # the Agent tool is gone


def test_adversary_runs_on_opus_analyst_on_sonnet(monkeypatch, tmp_path):
    runs = []
    _patch_subprocess(monkeypatch, _fake_run_factory(
        {"analyst": "TP", "adversary": "TP"}, runs))
    verify_mod.judge_findings([FINDING], tmp_path, "/bin/claude")
    models = {}
    for argv in runs:
        system = argv[argv.index("--system-prompt") + 1]
        role = "analyst" if system.startswith(verify_mod.ANALYST) else "adversary"
        models[role] = argv[argv.index("--model") + 1]
    assert models == {"analyst": "sonnet", "adversary": "opus"}


def test_verify_findings_for_repo_filters_min_severity(monkeypatch, tmp_path):
    low = {**FINDING, "id": 11, "severity": 2}
    runs = []
    _patch_binaries(monkeypatch)
    _patch_subprocess(monkeypatch, _fake_run_factory(
        {"analyst": "TP", "adversary": "TP"}, runs))
    _patch_tempdir(monkeypatch, tmp_path)
    patches = []
    monkeypatch.setattr("satori_cli.utils.verify_issue.client.patch",
                        lambda path, **kw: patches.append((path, kw.get("json"))))
    verdicts = verify_mod.verify_findings_for_repo(
        [FINDING, low], "acme/app", min_severity="High")
    assert verdicts == {10: "TP"}  # the Medium (sev 2) finding was skipped
    assert patches == [("/findings/10", {"status": "TP"})]


def test_verify_findings_for_repo_no_eligible_findings_does_nothing(monkeypatch, tmp_path):
    ran = []
    _patch_binaries(monkeypatch)
    _patch_subprocess(monkeypatch, _fake_run_factory({"analyst": "TP", "adversary": "TP"}, ran))
    verdicts = verify_mod.verify_findings_for_repo(
        [{**FINDING, "severity": 1}], "acme/app", min_severity="High")
    assert verdicts == {} and ran == []  # nothing eligible -> no clone, no claude


def test_verify_findings_persists_via_patch(monkeypatch, tmp_path):
    patches = []
    monkeypatch.setattr("satori_cli.utils.verify_issue.client.get", _responses())
    monkeypatch.setattr("satori_cli.utils.verify_issue.client.patch",
                        lambda path, **kw: patches.append((path, kw.get("json"))))
    _patch_binaries(monkeypatch)
    _patch_subprocess(monkeypatch, _fake_run_factory({"analyst": "TP", "adversary": "TP"}))
    _patch_tempdir(monkeypatch, tmp_path)
    verdicts = verify_mod.verify_findings([10])
    assert verdicts == {10: "TP"}
    assert patches == [("/findings/10", {"status": "TP"})]


def test_verify_findings_usage_limit_is_clean_error(monkeypatch, tmp_path):
    monkeypatch.setattr("satori_cli.utils.verify_issue.client.get", _responses())
    _patch_binaries(monkeypatch)
    _patch_tempdir(monkeypatch, tmp_path)

    def fake_run(args, **kwargs):
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 1, "Claude usage limit reached", "")

    _patch_subprocess(monkeypatch, fake_run)
    result = CliRunner().invoke(issue, ["10", "verify"])
    assert result.exit_code != 0
    assert "usage limit" in result.output.lower()


def test_issue_verify_happy_path_clones_once(monkeypatch, tmp_path):
    runs = []
    monkeypatch.setattr("satori_cli.utils.verify_issue.client.get",
                        lambda path, **kw: _responses()(path))
    monkeypatch.setattr("satori_cli.utils.verify_issue.client.patch", lambda path, **kw: None)
    _patch_binaries(monkeypatch)
    _patch_subprocess(monkeypatch, _fake_run_factory({"analyst": "TP", "adversary": "TP"}, runs))
    _patch_tempdir(monkeypatch, tmp_path)
    result = CliRunner().invoke(issue, ["10", "verify"])
    assert result.exit_code == 0, result.output
    clone_runs = [r for r in runs if r[1] == "clone"]
    claude_runs = [r for r in runs if r[1] == "-p"]
    assert len(clone_runs) == 1  # cloned once
    assert len(claude_runs) == 2  # analyst + adversary


def test_issue_verify_missing_claude(monkeypatch):
    monkeypatch.setattr("satori_cli.utils.verify_issue.client.get", _responses())
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


def test_issue_verify_missing_repo(monkeypatch):
    monkeypatch.setattr("satori_cli.utils.verify_issue.client.get", _responses(job=LOCAL_JOB))
    _patch_binaries(monkeypatch)
    result = CliRunner().invoke(issue, ["10", "verify"])
    assert result.exit_code != 0
    assert "no associated repository" in result.output


def test_list_finding_ids_for_execution_paginates(monkeypatch):
    pages = {
        1: {"items": [{"id": 1}, {"id": 2}], "total": 3},
        2: {"items": [{"id": 3}], "total": 3},
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
