"""Resolve a finding's repo, clone it, and judge TP/FP with Claude Code.

Two independent Claude agents read the actual code -- an analyst and an adversary who argues
every finding is a false positive -- and a tie-breaker settles any disagreement. The verdicts
are parsed here and persisted via the API; Claude runs on the local subscription (the
ANTHROPIC_* variables are stripped so it never bills the API or hits another model).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

import rich_click as click

from ..api import client
from .console import stderr
from .git_clone import clone_repo, require_git

_SNAPSHOT_MAX_CHARS = 12_000
_RISK_LABELS = {
    0: "Info",
    1: "Low",
    2: "Medium",
    3: "High",
    4: "Critical",
    5: "Blocker",
}
_SEVERITY_RANK = {label.lower(): value for value, label in _RISK_LABELS.items()}

# tries per agent: a model may answer with prose instead of the JSON array, or be briefly
# overloaded; a usage limit is terminal and stops at once
CLAUDE_ATTEMPTS = 3
_RETRY_BACKOFF_S = 2.0
# the only tools verify needs; --tools caps the tool-defs SENT per call (~15k -> ~2k tokens;
# --allowedTools alone does not, it only gates permission)
_TOOLS = ("Read", "Grep", "Glob")
_USAGE_LIMIT_RE = re.compile(
    r"usage limit|session limit|rate.?limit|quota exceeded|credit balance"
    r"|insufficient_quota|overloaded_error|try again later",
    re.IGNORECASE,
)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL)
_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)
# Last-resort recovery: pull id+verdict pairs even when the JSON is invalid (e.g. a model
# echoed a source line with unescaped quotes in a field we don't use) or wrapped in prose.
# [^{}] keeps each match inside one object; both field orders are allowed.
_PAIR_RE = re.compile(
    r'"id"\s*:\s*(\d+)[^{}]*?"verdict"\s*:\s*"(TP|FP)"'
    r'|"verdict"\s*:\s*"(TP|FP)"[^{}]*?"id"\s*:\s*(\d+)',
    re.IGNORECASE,
)

ANALYST = (
    "You are a senior application-security engineer verifying whether reported findings "
    "are real, exploitable vulnerabilities in the repository at your working directory."
)
ADVERSARY = (
    "You are a skeptical application-security reviewer. Start from the assumption that "
    "every finding is a FALSE POSITIVE and try to disprove it by reading the code; "
    "concede TP only when the vulnerability is genuinely reachable and exploitable."
)
TIEBREAKER = (
    "You are the deciding application-security reviewer. Two reviewers disagreed; read "
    "the code and make the final, decisive TP or FP call for each finding."
)
_ROLE_NAMES = {ANALYST: "analyst", ADVERSARY: "adversary", TIEBREAKER: "tie-breaker"}
# the adversary (which must try hardest to disprove a finding) runs on the stronger model
_ROLE_MODELS = {ANALYST: "sonnet", ADVERSARY: "opus", TIEBREAKER: "sonnet"}
# appended to every role; the stable half of the system prompt (role + this stays
# byte-identical across findings, so the tools+system cache prefix is reused call to call)
SYSTEM_COMMON = (
    "You are authorized to perform this defensive security analysis; judge each finding on "
    "its merits and do not refuse or hedge.\n"
    "You MUST investigate with your tools before deciding: open the exact file and line the "
    "finding points at with Read, trace the data flow with Grep/Glob, and confirm whether the "
    "sink is reachable with attacker-controlled input. The finding snapshot is only a lead; "
    "the source code in your working directory is the ground truth -- never issue a verdict "
    "from the snapshot alone.\n"
    "A finding is a TRUE POSITIVE only when attacker-controllable input can reach an "
    "exploitable sink on a reachable path with no effective sanitizer or mitigation; otherwise "
    "it is a FALSE POSITIVE (unreachable, not attacker-controlled, already sanitized or "
    "parameterized, test or vendored code, and the like). When you cannot demonstrate a "
    "concrete exploit path, judge FP."
)
_TASK = (
    "For each finding below, open its file at the given line, trace input -> sink, check "
    "sanitizers and reachability, then decide TP (real and exploitable) or FP. "
    "Output ONLY a JSON array -- no prose, no markdown fences. Each element: "
    '{"id": <finding id int>, "verdict": "TP" or "FP", "line": <1-based line int>}.'
)


class UsageLimitError(RuntimeError):
    """Claude Code reported a usage/rate limit; verification should stop and resume later."""


def repository_from_job(job: dict[str, Any]) -> Optional[str]:
    job_type = (job.get("type") or "").upper()
    if job_type == "SCAN":
        data = job.get("repository_data") or {}
        repo = data.get("repository") if isinstance(data, dict) else None
        return repo or None
    if job_type in ("RUN", "LOCAL"):
        return job.get("repository") or None
    return None


def resolve_repository(finding_id: int) -> tuple[dict[str, Any], str]:
    finding = client.get(f"/findings/{finding_id}").json()
    execution_id = finding.get("execution_id")
    if execution_id is None:
        raise click.UsageError(f"Finding {finding_id} has no execution_id.")

    execution = client.get(f"/executions/{execution_id}").json()
    job_id = execution.get("job_id")
    if job_id is None:
        raise click.UsageError(
            f"Execution {execution_id} has no job_id; cannot resolve repository."
        )

    job = client.get(f"/jobs/{job_id}").json()
    repository = repository_from_job(job)
    if not repository:
        raise click.UsageError(
            f"Job {job_id} (type={job.get('type')!r}) has no associated repository."
        )
    return finding, repository


def _severity_label(severity: Any) -> str:
    if severity is None:
        return "N/A"
    if isinstance(severity, int):
        return _RISK_LABELS.get(severity, str(severity))
    return str(severity)


def _snapshot_text(snapshot: Any) -> str:
    if snapshot is None:
        return "null"
    try:
        text = json.dumps(snapshot, indent=2, default=str)
    except (TypeError, ValueError):
        text = str(snapshot)
    if len(text) > _SNAPSHOT_MAX_CHARS:
        return text[:_SNAPSHOT_MAX_CHARS] + "\n... [truncated]"
    return text


def _location(finding: dict[str, Any]) -> str:
    """file:line the finding points at (from its snapshot, falling back to identity), so the
    agent can open the exact code rather than dig it out of the snapshot JSON."""
    snapshot = finding.get("snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    identity = finding.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    path = snapshot.get("filePath") or identity.get("path") or "?"
    line = snapshot.get("lineNumber") or identity.get("start_line") or "?"
    return f"{path}:{line}"


def build_verify_prompt(findings: list[dict[str, Any]]) -> str:
    """The per-call user prompt: the findings to judge first, the task and output contract
    last -- the stable role and criteria live in the system prompt."""
    blocks = ["Findings to judge (read the code before deciding):", ""]
    for finding in findings:
        blocks.append(
            f"- id: {finding['id']}\n"
            f"  severity: {_severity_label(finding.get('severity'))}\n"
            f"  title: {finding.get('title') or ''}\n"
            f"  location: {_location(finding)}\n"
            f"  snapshot: {_snapshot_text(finding.get('snapshot'))}"
        )
    blocks += ["", _TASK]
    return "\n".join(blocks)


def _pairwise_verdicts(text: str) -> dict[int, str]:
    """Recover {id: verdict} by scanning for id+verdict pairs directly -- tolerant of invalid
    JSON (a stray unescaped quote in an unused field) and of prose around the array."""
    verdicts: dict[int, str] = {}
    for first_id, first_v, second_v, second_id in _PAIR_RE.findall(text):
        verdicts[int(first_id or second_id)] = (first_v or second_v).upper()
    return verdicts


def _verdicts(text: str) -> Optional[dict[int, str]]:
    """The {id: 'TP'|'FP'} map parsed from an agent's JSON-array answer, or None."""
    text = text.strip()
    fence = _FENCE_RE.search(text)
    body = fence.group(1).strip() if fence else text
    try:
        data: Any = json.loads(body)
    except ValueError:
        match = _ARRAY_RE.search(body)
        try:
            data = json.loads(match.group(0)) if match else None
        except ValueError:
            data = None
    if isinstance(data, list):
        return {
            int(item["id"]): item["verdict"].upper()
            for item in data
            if isinstance(item, dict) and "id" in item
            and str(item.get("verdict")).upper() in ("TP", "FP")
        }
    return _pairwise_verdicts(text) or None


def _require_binaries() -> tuple[str, str]:
    git = require_git()
    claude = shutil.which("claude")
    if not claude:
        raise click.UsageError(
            "`claude` (Claude Code CLI) is not installed or not on PATH. "
            "Install with: npm install -g @anthropic-ai/claude-code"
        )
    return git, claude


def _claude_env() -> dict[str, str]:
    """The environment for Claude, stripped of the API key/base-url/model so verification
    always uses the local subscription rather than a billed API or another model. (Secrets are
    not scrubbed here: the untrusted repo can't reach this environment anyway -- its hooks are
    renamed away before Claude starts and the agent's tools are read-only -- and a name-based
    denylist would be a fragile, bypassable guard, not a boundary.)"""
    return {
        key: value
        for key, value in os.environ.items()
        if key not in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL")
    }


def _claude_once(
    claude: str, prompt: str, role: str, cwd: Path
) -> tuple[Optional[dict[int, str]], str]:
    """Run one Claude agent (role via the system prompt) over the repo in cwd. Returns
    (verdicts|None, output); output is kept so the caller can spot a usage limit."""
    result = subprocess.run(  # noqa: S603
        [
            claude,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--model",
            _ROLE_MODELS.get(role, "sonnet"),
            "--effort",
            "low",
            "--permission-mode",
            "default",
            "--system-prompt",
            f"{role}\n\n{SYSTEM_COMMON}",
            "--tools",
            *_TOOLS,
            "--allowedTools",
            *_TOOLS,
            "--no-session-persistence",
        ],
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        env=_claude_env(),
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode:
        return None, output
    try:
        envelope = json.loads(result.stdout)
    except ValueError:
        return None, output
    if (
        envelope.get("is_error")
        or envelope.get("subtype") != "success"
        or envelope.get("permission_denials")
    ):
        return None, output
    return _verdicts(envelope.get("result", "")), output


def _run_claude(claude: str, findings: list[dict[str, Any]], role: str, cwd: Path) -> dict[int, str]:
    """Run an agent, retrying an unparseable answer a few times. A usage limit is terminal
    (a retry only burns more quota) and raises UsageLimitError. Returns {} if no verdicts
    could be parsed after every attempt."""
    prompt = build_verify_prompt(findings)
    output = ""
    for attempt in range(1, CLAUDE_ATTEMPTS + 1):
        verdicts, output = _claude_once(claude, prompt, role, cwd)
        if verdicts is not None:
            return verdicts
        if _USAGE_LIMIT_RE.search(output):
            raise UsageLimitError(output[-200:])
        if attempt < CLAUDE_ATTEMPTS:
            time.sleep(_RETRY_BACKOFF_S)
    stderr.print(
        f"WARNING: verify {_ROLE_NAMES.get(role, 'agent')} returned no parseable verdicts "
        f"(last output: {output[-200:].strip()!r})."
    )
    return {}


def judge_findings(
    findings: list[dict[str, Any]], clone_dir: Path, claude: str
) -> dict[int, str]:
    """Judge all findings with two agents -- an analyst and an adversary -- over one clone,
    settling any disagreement with a tie-breaker. Returns {finding_id: 'TP'|'FP'} (a finding
    with no agreed/decisive verdict is omitted). Raises UsageLimitError on a usage limit."""
    analysis = _run_claude(claude, findings, ANALYST, clone_dir)
    adversary = _run_claude(claude, findings, ADVERSARY, clone_dir)
    verdicts: dict[int, str] = {}
    for finding in findings:
        fid = finding["id"]
        first, second = analysis.get(fid), adversary.get(fid)
        if first is not None and first == second:
            verdicts[fid] = first
            continue
        tie = _run_claude(claude, [finding], TIEBREAKER, clone_dir)
        if tie.get(fid):
            verdicts[fid] = tie[fid]
    return verdicts


def _severity_floor(min_severity: Any) -> Optional[int]:
    if min_severity is None:
        return None
    if isinstance(min_severity, int):
        return min_severity
    floor = _SEVERITY_RANK.get(str(min_severity).lower())
    if floor is None:
        raise click.UsageError(
            f"Unknown severity {min_severity!r}; use one of: "
            + ", ".join(_RISK_LABELS[value] for value in sorted(_RISK_LABELS))
        )
    return floor


def _meets_severity(finding: dict[str, Any], floor: Optional[int]) -> bool:
    if floor is None:
        return True
    severity = finding.get("severity")
    return isinstance(severity, int) and severity >= floor


# A cloned repo's agent config we move aside before running Claude in it: `.claude/` (hooks,
# settings, skills, commands, agents -> code execution), `.mcp.json` (servers Claude would
# spawn), and the instruction files Claude auto-loads (prompt injection).
_UNTRUSTED_CONFIG = (".claude", ".mcp.json", "CLAUDE.md", "AGENTS.md", ".cursorrules")


def _defang_clone(clone_dir: Path) -> None:
    """Rename a cloned repo's agent config to ``*.bak`` before running Claude in it, so an
    untrusted repo's hooks, MCP servers and instruction files cannot take effect. Claude loads
    project config from its working directory with no trust prompt in ``-p`` mode, so moving
    these files aside -- deterministically, before Claude starts -- is what stops a cloned
    repo from running code or injecting instructions during verification."""
    for name in _UNTRUSTED_CONFIG:
        entry = clone_dir / name
        if not entry.exists():
            continue
        backup = clone_dir / f"{name}.bak"
        if backup.is_dir():
            shutil.rmtree(backup, ignore_errors=True)
        elif backup.exists():
            backup.unlink()
        entry.rename(backup)


def verify_findings_for_repo(
    findings: list[dict[str, Any]],
    repository: str,
    min_severity: Any = None,
    persist: bool = True,
    quiet: bool = False,
) -> dict[int, str]:
    """Clone `repository` once and judge `findings` (only those at or above `min_severity`,
    e.g. 'High', when given). Persists each verdict via the API unless persist=False, and
    returns {finding_id: 'TP'|'FP'}. Raises UsageLimitError on a Claude usage limit. `quiet`
    drops the "Cloning …" status line (for batch callers whose own progress is the output)."""
    floor = _severity_floor(min_severity)
    todo = [finding for finding in findings if _meets_severity(finding, floor)]
    if not todo:
        return {}
    git, claude = _require_binaries()
    with tempfile.TemporaryDirectory(prefix="satori-verify-") as tmp:
        clone_dir = clone_repo(git, repository, Path(tmp), quiet=quiet)
        _defang_clone(clone_dir)
        verdicts = judge_findings(todo, clone_dir, claude)
    if persist:
        for finding_id, verdict in verdicts.items():
            client.patch(f"/findings/{finding_id}", json={"status": verdict})
    return verdicts


_FINDINGS_PAGE_SIZE = 200


def list_finding_ids_for_execution(execution_id: int) -> list[int]:
    """Paginate GET /findings for an execution and return every finding id."""
    ids: list[int] = []
    page = 1
    while True:
        data = client.get(
            "/findings",
            params={
                "execution_id": execution_id,
                "page": page,
                "quantity": _FINDINGS_PAGE_SIZE,
            },
        ).json()
        items = data.get("items") or []
        ids.extend(item["id"] for item in items if "id" in item)
        total = data.get("total")
        if total is not None and len(ids) >= total:
            break
        if len(items) < _FINDINGS_PAGE_SIZE:
            break
        page += 1
    return ids


def verify_findings(finding_ids: list[int], min_severity: Any = None) -> dict[int, str]:
    """Verify multiple findings (of one repo) with a single clone; persist and report each
    verdict. Returns {finding_id: 'TP'|'FP'}."""
    if not finding_ids:
        return {}

    first_finding, repository = resolve_repository(finding_ids[0])
    findings: list[dict[str, Any]] = [first_finding]
    for finding_id in finding_ids[1:]:
        finding, repo = resolve_repository(finding_id)
        if repo != repository:
            raise click.UsageError(
                f"Finding {finding_id} repository {repo!r} differs from "
                f"{repository!r}; cannot batch-verify across repositories."
            )
        findings.append(finding)

    try:
        verdicts = verify_findings_for_repo(findings, repository, min_severity)
    except UsageLimitError as error:
        raise click.ClickException(
            "Claude usage limit reached; re-run to continue verification."
        ) from error

    for finding in findings:
        verdict = verdicts.get(finding["id"], "undecided")
        stderr.print(f"finding {finding['id']}: {verdict}")
    return verdicts


def verify_issue(finding_id: int) -> dict[int, str]:
    return verify_findings([finding_id])
