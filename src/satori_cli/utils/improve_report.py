"""Rewrite a draft security advisory into a comprehensive report before it is published.

Runs one Claude agent, role IMPROVE_PROMPT, over the real cloned repository, given the
finding and the draft advisory's current (auto-generated, boilerplate) title and
description, and returns a rewritten {"title", "description", "cvss_vector", "severity",
"remediation"}. Same trust model as verify_issue: Claude runs on the local subscription
(the ANTHROPIC_* variables are stripped) with read-only tools, over a clone whose agent
config has been moved aside first (see git_clone.defang_clone), so an untrusted repo
cannot run code or inject instructions.

The report body (title + description) is neutral, third-person, and exactly three
sections (Summary, Vulnerable Code, Impact): no CVSS prose (the vector/severity are
still computed and persisted as their own fields, just not rendered into the text) and
no remediation advice in the body. Remediation is persisted separately, as a follow-up
comment on the finding, right after the advisory draft is updated (see improve_advisory).
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from cvss import CVSS4
from httpx2 import HTTPStatusError

from ..api import client
from .claude_agent import (
    CLAUDE_ATTEMPTS,
    RETRY_BACKOFF_S,
    USAGE_LIMIT_RE,
    claude_env,
    finding_location,
    severity_label,
    snapshot_text,
)
from .console import stderr
from .git_clone import clone_repo, defang_clone, require_claude, require_git
from .verify_issue import UsageLimitError, resolve_repository

IMPROVE_PROMPT = (
    "You are a security report editor for Satori CI's vulnerability disclosure pipeline. "
    "You turn a bare, auto-generated advisory draft into a clean, precise report a "
    "maintainer can act on, grounded entirely in the real source code at your working "
    "directory and the finding's own recorded evidence."
)
IMPROVE_SYSTEM_COMMON = (
    "You are authorized to perform this defensive security writing task; do not refuse or hedge.\n"
    "Open the exact file and line the finding points at with Read, and trace the data flow with "
    "Grep/Glob, before writing anything. The finding snapshot and the draft's current text are "
    "only a starting point; the source code in your working directory is the ground truth.\n"
    "Never claim a reproduction, exploit, or proof of concept that is not either (a) explicitly "
    "recorded in the finding's exploitability reason given to you below, or (b) a direct, literal "
    "reading of the code path you opened; do not invent command output, HTTP responses, or other "
    "'evidence' you did not receive. This is an internal accuracy constraint only: never write "
    "about it, and never mention your own tools, methodology, or what was or was not executed or "
    "tested. The report states what the vulnerability is and does, nothing about how this report "
    "itself was produced.\n"
    "Write in neutral, third-person, precise technical prose, not bullet lists except where a "
    "list is genuinely clearer (e.g. multiple file locations). Never use the words 'I', 'we', "
    "'us', or 'our'. Never use em dashes or en dashes. Describe the code and the data flow "
    "directly: 'the handler passes X to Y', not 'we found that the handler passes X to Y'.\n"
    "Structure the description with exactly these three sections, as Markdown headers, in this "
    "order, and no others: Summary, Vulnerable Code, Impact. Vulnerable Code must quote the "
    "actual vulnerable source (file path, line numbers, and a real code snippet read from the "
    "repository) and explain the data flow that reaches it. Do not add a CVSS section and do not "
    "add a Remediation section: compute the CVSS vector and severity as separate output fields "
    "(below), not as description prose, and return remediation guidance as its own separate "
    "field, not inside the description.\n"
    "The title must follow the pattern '<vulnerability class or mechanism> in <component or "
    "location> leads to <concrete consequence>', naming the real vulnerability class and "
    "consequence, never just the raw tool rule name.\n"
    "Compute a CVSS 4.0 base vector from what was actually confirmed, not from the raw tool's "
    "severity label: score Attack Vector, Attack Complexity, Attack Requirements, Privileges "
    "Required and User Interaction from the real reachability read in the code "
    "(network-reachable and unauthenticated is not automatic; a finding that needs local access, "
    "a victim's action, or specific preconditions must say so in the vector), and score the "
    "Vulnerable System impact (VC/VI/VA) from what the sink actually allows on the system "
    "containing the flaw, not the worst case imaginable; score Subsequent System impact "
    "(SC/SI/SA) only when the finding itself demonstrates impact reaching beyond that system, "
    "otherwise leave it None. Set the severity label to match that score (Critical/High/Medium/"
    "Low), even if it differs from the draft's current severity."
)

_MODEL = "sonnet"
_TOOLS = ("Read", "Grep", "Glob")

_IMPROVE_TASK = (
    "Rewrite this advisory's title and description using the structure above, and write a "
    "separate remediation field (neutral, third-person, 2 to 4 sentences, no markdown header) "
    "naming the concrete fix. Output ONLY a JSON object -- no prose, no markdown fences: "
    '{"title": "<improved title, following the required pattern>", '
    '"description": "<improved description, markdown, Summary/Vulnerable Code/Impact only>", '
    '"cvss_vector": "<CVSS:4.0/AV:.../AC:.../AT:.../PR:.../UI:.../VC:.../VI:.../VA:.../SC:.../'
    'SI:.../SA:... base vector>", '
    '"severity": "<CRITICAL, HIGH, MEDIUM or LOW, matching the vector>", '
    '"remediation": "<the concrete fix, neutral third-person prose>"}.'
)
# The backend's required CVSS format has changed mid-session before (3.1, then 4.0); this is
# confirmed current as of 2026-11-05. If it rejects a well-formed 4.0 vector again, that is a
# real API-contract change to re-check against a live PATCH, not a prompt-wording problem.
_CVSS4_RE = re.compile(
    r"^CVSS:4\.0/AV:[NALP]/AC:[LH]/AT:[NP]/PR:[NLH]/UI:[NPA]/"
    r"VC:[NLH]/VI:[NLH]/VA:[NLH]/SC:[NLH]/SI:[NLH]/SA:[NLH]$"
)
_VALID_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


def build_improve_prompt(
    finding: dict[str, Any],
    exploitability_reason: str,
    current_title: str,
    current_description: str,
) -> str:
    """The per-call user prompt: the finding and its recorded exploitability evidence, the
    draft's current text, then the task and output contract -- mirrors
    verify_issue.build_verify_prompt's shape."""
    blocks = [
        "Finding this advisory is for:",
        "",
        f"- id: {finding['id']}\n"
        f"  severity: {severity_label(finding.get('severity'))}\n"
        f"  title: {finding.get('title') or ''}\n"
        f"  location: {finding_location(finding)}\n"
        f"  snapshot: {snapshot_text(finding.get('snapshot'))}",
        "",
        "Recorded exploitability evidence (from verify/manual triage; the only reproduction "
        "you may describe as having actually happened):",
        exploitability_reason or "(none recorded -- do not claim any reproduction occurred; "
        "write Reachability from your own code reading instead of Proof of Concept)",
        "",
        "Current draft title:",
        current_title or "",
        "",
        "Current draft description:",
        current_description or "",
        "",
        _IMPROVE_TASK,
    ]
    return "\n".join(blocks)


def _severity_from_vector(cvss_vector: str) -> Optional[str]:
    """The severity band CVSS itself derives from the score, e.g. "HIGH". The backend
    independently computes this from the vector and 409s if a PATCH's severity field
    disagrees, so this must be computed the same way rather than trusted from the agent's
    own label (seen in practice to drift from the vector at bracket boundaries)."""
    try:
        rating = CVSS4(cvss_vector).severities()[0]
    except Exception:  # pylint: disable=broad-except
        return None
    rating = rating.upper()
    return rating if rating in _VALID_SEVERITIES else None


def _parse_report(text: str) -> Optional[dict[str, str]]:
    """The {"title", "description", "cvss_vector", "severity", "remediation"} object parsed
    from an agent's JSON answer, or None. A malformed CVSS vector fails the whole parse
    (triggering a retry), since the backend rejects a publish without a valid CVSS 4.0 base
    vector. severity is not taken from the agent's own label: it is computed from the vector
    (see _severity_from_vector), since the backend 409s a PATCH whose severity field disagrees
    with what it derives from the vector itself. remediation is required too -- it is persisted
    separately (see improve_advisory), not folded into description, so a response missing it
    is just as incomplete as one missing the CVSS vector."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        data: Any = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except ValueError:
            return None
    if (
        not isinstance(data, dict)
        or "title" not in data
        or "description" not in data
        or not str(data.get("remediation") or "").strip()
    ):
        return None
    cvss_vector = str(data.get("cvss_vector") or "")
    if not _CVSS4_RE.match(cvss_vector):
        return None
    severity = _severity_from_vector(cvss_vector)
    if severity is None:
        return None
    return {
        "title": str(data["title"]),
        "description": str(data["description"]),
        "cvss_vector": cvss_vector,
        "severity": severity,
        "remediation": str(data["remediation"]),
    }


def _claude_once(claude: str, prompt: str, cwd: Path) -> tuple[Optional[dict[str, str]], str]:
    """Run the improve agent once over the repo in cwd. Returns (report|None, output); output
    is kept so the caller can spot a usage limit."""
    result = subprocess.run(  # noqa: S603
        [
            claude,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--model",
            _MODEL,
            "--effort",
            "low",
            "--permission-mode",
            "default",
            "--system-prompt",
            f"{IMPROVE_PROMPT}\n\n{IMPROVE_SYSTEM_COMMON}",
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
        env=claude_env(),
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
    return _parse_report(envelope.get("result", "")), output


def _run_claude(claude: str, prompt: str, cwd: Path) -> Optional[dict[str, str]]:
    """Run the improve agent, retrying an unparseable answer a few times. A usage limit is
    terminal and raises UsageLimitError. Returns None if no report could be parsed."""
    output = ""
    for attempt in range(1, CLAUDE_ATTEMPTS + 1):
        report, output = _claude_once(claude, prompt, cwd)
        if report is not None:
            return report
        if USAGE_LIMIT_RE.search(output):
            raise UsageLimitError(output[-200:])
        if attempt < CLAUDE_ATTEMPTS:
            time.sleep(RETRY_BACKOFF_S)
    stderr.print(
        f"WARNING: improve-report returned no parseable report "
        f"(last output: {output[-200:].strip()!r})."
    )
    return None


def _find_advisory(finding_id: str) -> Optional[dict[str, Any]]:
    """The finding's draft/published SECURITY_ADVISORY external issue, or None."""
    items = client.get(
        "/external_issues",
        params={"finding_id": finding_id, "kind": "SECURITY_ADVISORY", "quantity": 1},
    ).json().get("items") or []
    return items[0] if items else None


def _exploitability_reason(finding_id: str) -> str:
    """The reason text from the finding's most recent EXPLOITABILITY_CHANGED event, or ''.
    This isn't a field on the finding itself (only its current `exploitability` enum is), the
    reason -- the judging agent's own evidence, when verify_issue set it -- only lives in the
    timeline, so it has to be fetched separately."""
    timeline = client.get(f"/findings/{finding_id}/timeline").json()
    events = timeline if isinstance(timeline, list) else timeline.get("items") or []
    for event in reversed(events):
        if event.get("type") == "EXPLOITABILITY_CHANGED":
            return (event.get("payload") or {}).get("reason") or ""
    return ""


def _post_remediation_comment(finding_id: str, remediation: str) -> None:
    """Post the remediation as a follow-up comment on the finding, right after the advisory
    draft is updated. Remediation never lives in the advisory body itself (see
    IMPROVE_SYSTEM_COMMON); this is its only home. Best-effort: a failure here must not
    discard the title/description/CVSS rewrite that already succeeded."""
    try:
        client.post(f"/findings/{finding_id}/comments", json={"body": f"Remediation: {remediation}"})
    except HTTPStatusError as error:
        detail = error.response.text if error.response is not None else str(error)
        stderr.print(f"WARNING: improve-report {finding_id}: could not post remediation comment ({detail.strip()}).")


def improve_advisory(finding_id: str, persist: bool = True) -> Optional[dict[str, str]]:
    """Clone the finding's repo, run the IMPROVE_PROMPT agent over it with the finding and
    the existing draft advisory's current title/description, and return the rewritten
    {"title", "description", "cvss_vector", "severity", "remediation"} (a CVSS 4.0 base
    vector and a matching severity label, computed by the agent from what it actually
    confirmed, not copied from the tool's raw severity -- a publish 409s without a valid
    CVSS vector). PATCHes the advisory with the title/description/cvss_vector/severity
    unless persist=False, then posts remediation as a follow-up comment on the finding (see
    _post_remediation_comment) -- remediation is never part of the advisory body. Returns
    None without touching anything if there is no draft, the repo cannot be cloned, or
    Claude could not produce a parseable answer (including a missing remediation field, an
    invalid CVSS vector, or an invalid severity label). Raises UsageLimitError on a usage
    limit. Only a draft can be changed; once published to GitHub the advisory text is fixed
    there (same rule as `satori-v2 advisory edit`), so this is a no-op on an
    already-published one.
    """
    advisory = _find_advisory(finding_id)
    if advisory is None:
        stderr.print(f"WARNING: improve-report found no advisory draft for finding {finding_id}.")
        return None
    if advisory.get("external_id"):
        stderr.print(f"improve-report: advisory for finding {finding_id} is already published; skipping.")
        return None

    finding, repository = resolve_repository(finding_id)
    reason = _exploitability_reason(finding_id)
    git, claude = require_git(), require_claude()
    with tempfile.TemporaryDirectory(prefix="satori-improve-") as tmp:
        clone_dir = clone_repo(git, repository, Path(tmp), quiet=True)
        defang_clone(clone_dir)
        prompt = build_improve_prompt(
            finding, reason, advisory.get("title", ""), advisory.get("description", "")
        )
        report = _run_claude(claude, prompt, clone_dir)
    if report is None:
        return None
    advisory_fields = {
        "title": report["title"],
        "description": report["description"],
        "cvss_vector": report["cvss_vector"],
        "severity": report["severity"],
    }
    if persist:
        try:
            client.patch(f"/external_issues/{advisory['id']}", json=advisory_fields)
        except HTTPStatusError as error:
            detail = error.response.text if error.response is not None else str(error)
            if "cvss" not in detail.lower():
                raise
            # The backend's required CVSS format can change (3.1 vs 4.0 seen in the same
            # session); do not lose the title/description rewrite over a stale vector format,
            # apply what we can and surface the rest as a clear, visible publish failure
            # instead of silently discarding the whole improved report.
            stderr.print(
                f"WARNING: improve-report {finding_id}: backend rejected the CVSS vector "
                f"({detail.strip()}); applying title/description only."
            )
            client.patch(f"/external_issues/{advisory['id']}", json={
                "title": report["title"], "description": report["description"],
            })
        _post_remediation_comment(finding_id, report["remediation"])
    return report
