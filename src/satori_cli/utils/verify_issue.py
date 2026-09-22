"""Resolve a finding's repo, clone it, and run Claude Code to verify TP/FP."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

import rich_click as click

from ..api import client
from .console import stderr

_SNAPSHOT_MAX_CHARS = 12_000
_RISK_LABELS = {
    0: "Info",
    1: "Low",
    2: "Medium",
    3: "High",
    4: "Critical",
    5: "Blocker",
}

_VERIFY_PROMPT = """\
You are verifying a Satori security finding against the repository in the current working directory.

## Finding
- id: {finding_id}
- title: {title}
- status: {status}
- source: {source}
- severity: {severity}
- identity: {identity}
- repository: {repository}

### Snapshot
```json
{snapshot}
```

## Task
1. Spawn exactly 3 independent Agent subagents. Each agent must independently decide whether this finding is a real vulnerability (TP) or a false positive (FP), inspect the relevant code in this repo, and return:
   - verdict: TP or FP
   - short rationale
2. Take the majority vote (at least 2 of 3) as the final verdict.
3. Persist the result by running these CLI commands (in order):

```bash
satori-v2 issue {finding_id} comment "Conclusion: <concise final judgment>"
satori-v2 issue {finding_id} status TP
```

The comment body must be only a short Conclusion line (one or two sentences). Do not include per-agent analysis or the vote tally in the comment.

Do not print a separate verification summary, final-verdict block, or duplicate reasoning to the console — the CLI `comment` / `status` commands already report success. Rely on those; do not invent a second writeup.

Use `FP` instead of `TP` in the status command when the majority says FP.

Escape the comment body safely for the shell (prefer double quotes; escape any inner double quotes). Do not ask the user for confirmation — complete the verification end-to-end.
"""


def repository_from_job(job: dict[str, Any]) -> Optional[str]:
    job_type = (job.get("type") or "").upper()
    if job_type == "SCAN":
        data = job.get("repository_data") or {}
        repo = data.get("repository") if isinstance(data, dict) else None
        return repo or None
    if job_type == "RUN":
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


def build_verify_prompt(finding: dict[str, Any], repository: str) -> str:
    finding_id = finding["id"]
    return _VERIFY_PROMPT.format(
        finding_id=finding_id,
        title=finding.get("title") or "",
        status=finding.get("status") or "",
        source=finding.get("source") or "",
        severity=_severity_label(finding.get("severity")),
        identity=finding.get("identity") or "",
        repository=repository,
        snapshot=_snapshot_text(finding.get("snapshot")),
    )


def _require_binaries() -> tuple[str, str]:
    git = shutil.which("git")
    if not git:
        raise click.UsageError("`git` is not installed or not on PATH.")
    claude = shutil.which("claude")
    if not claude:
        raise click.UsageError(
            "`claude` (Claude Code CLI) is not installed or not on PATH. "
            "Install with: npm install -g @anthropic-ai/claude-code"
        )
    return git, claude


def _clone_repo(git: str, repository: str, dest: Path) -> Path:
    url = f"https://github.com/{repository}.git"
    dest.mkdir(parents=True, exist_ok=True)
    clone_dir = dest / Path(repository).name
    stderr.print(f"Cloning {repository} into {clone_dir}…")
    result = subprocess.run(  # noqa: S603
        [git, "clone", "--depth", "1", url, str(clone_dir)],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    if result.returncode != 0:
        raise click.ClickException(
            f"Failed to clone {url} (exit {result.returncode})."
        )
    return clone_dir


def _run_claude(claude: str, prompt: str, cwd: Path) -> int:
    stderr.print("Running Claude Code verification…")
    result = subprocess.run(  # noqa: S603
        [
            claude,
            "-p",
            prompt,
            "--allowedTools",
            "Bash,Read,Grep,Glob,Agent",
            "--no-session-persistence",
        ],
        cwd=str(cwd),
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    return result.returncode


def verify_issue(finding_id: int) -> None:
    git, claude = _require_binaries()
    finding, repository = resolve_repository(finding_id)
    prompt = build_verify_prompt(finding, repository)

    with tempfile.TemporaryDirectory(prefix="satori-verify-") as tmp:
        clone_dir = _clone_repo(git, repository, Path(tmp))
        code = _run_claude(claude, prompt, clone_dir)
        if code != 0:
            raise click.ClickException(
                f"Claude Code exited with status {code}."
            )
