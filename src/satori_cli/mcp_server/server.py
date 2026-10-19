"""Local stdio MCP server: a thin, task-shaped client of the Satori v2 API.

stdout is the protocol channel. Nothing in here may print to it.
"""

import asyncio
import inspect
import os
import tempfile
import time
from functools import wraps
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx2
from mcp.server.fastmcp import FastMCP

from ..api import client
from ..commands.issue import normalize_severities
from ..config import config
from ..constants import report_url
from ..exceptions import AuthError, SatoriError
from ..models import BundleCache
from ..playbooks_api import client as playbooks_client
from ..utils.bundler import make_bundle
from ..utils.console import load_execution_outputs
from ..utils.git_clone import clone_repo, require_git
from ..utils.local_run import run_local_job
from ..utils.output_filter import run_test_filter
from ..utils.repo import is_github_repo, wildcard_owner
from . import recommend, shaping

DOCS_URL = os.getenv("SATORI_DOCS_URL", "https://docs-v2.satori.ci").rstrip("/")
DOC_MAX_CHARS = 30_000
DOC_PAGES = {
    "language": "playbooks/language",
    "asserts": "playbooks/asserts",
    "inputs": "playbooks/inputs",
    "settings": "playbooks/settings",
    "execution": "playbooks/execution",
    "tool-output": "playbooks/tool-output",
}

REPORT_STATUSES = ("PASS", "FAIL")
JOB_TYPES = ("RUN", "SCAN", "MONITOR", "GITHUB", "LOCAL")
VISIBILITIES = ("PUBLIC", "PRIVATE", "UNLISTED")

FINDING_STATUSES = ("OPEN", "INVESTIGATING", "TP", "FIXED", "FP", "ACCEPTED")
LISTABLE_JOB_TYPES = ("RUN", "SCAN", "MONITOR")
FINDING_SOURCES = ("ASSERT", "TOOL")
ORDERS = ("ASC", "DESC")
ADVISORY_KINDS = ("SECURITY_ADVISORY", "ISSUE")
ADVISORY_PROVIDERS = ("GITHUB",)
MAX_SCAN_QUANTITY = 10

mcp = FastMCP(
    "satori",
    instructions=(
        "Satori CI. Write a playbook (read the satori-docs://playbooks/language resource), "
        "call run_playbook, then get_execution for pass/fail and get_execution_output "
        "with a `test` filter for logs. When a playbook runs a security/analysis tool, "
        "prefer that tool's JSON/JSONL stdout flags (read satori-docs://playbooks/tool-output). "
        "In Satori, reports = executions; use "
        "list_executions (or list_reports) to list reports. Use get_execution_playbook "
        "to read the YAML of a run, and stop_execution to cancel a running one. "
        "Use list_jobs/get_job to find a job and its executions, and "
        "update_finding_status to triage a finding (only when asked). "
        "Use add_finding_comment to comment without changing status, and "
        "get_finding_timeline for status/comment history. "
        "list_playbooks/get_playbook browse ready-made catalog playbooks (use via "
        "playbook_uri); scan_repository scans one named owner/repo. "
        "run_local runs a playbook's commands on THIS machine (results are uploaded; "
        "analyze them with get_execution_output/list_findings). "
        "recommend_playbook inspects a repo and proposes a lint/format/types/unit/security "
        "playbook for .satori-llm.yml (or changes to an existing one); .satori.yml is for "
        "CI/manual and should import file://.satori-llm.yml. Relay `questions` to the user, "
        "call again with `prefs`, and write files only with their approval. "
        "Before editing code, run_local .satori-llm.yml once as a baseline; afterwards fix "
        "only failures that were not in the baseline. "
        "Output is always capped."
    ),
)


def _error_result(e: Exception) -> dict | None:
    if isinstance(e, AuthError):
        return {"error": "Not logged in. Run: satori-v2 config token <token>"}
    if isinstance(e, httpx2.HTTPStatusError):
        status = e.response.status_code
        result: dict[str, Any] = {
            "error": shaping.clip(e.response.text, 2000),
            "status": status,
        }
        if status == 403:
            result["hint"] = "This action needs a PRO or ENTERPRISE plan."
        return result
    if isinstance(e, httpx2.TimeoutException):
        return {"error": "Request to the Satori API timed out."}
    if isinstance(e, SatoriError):
        return {"error": str(e)}
    return None


def _safe(fn):
    """Turn API/auth failures into small error dicts instead of protocol errors."""

    if inspect.iscoroutinefunction(fn):

        @wraps(fn)
        async def async_wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except (AuthError, httpx2.HTTPError, SatoriError) as e:
                if (result := _error_result(e)) is None:
                    raise
                return result

        return async_wrapper

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (AuthError, httpx2.HTTPError, SatoriError) as e:
            if (result := _error_result(e)) is None:
                raise
            return result

    return wrapper


@mcp.tool()
@_safe
def whoami() -> dict:
    """Show which Satori account, profile and endpoint this server is using."""
    settings = client.get("/settings").json()
    return {
        "profile": config.profile,
        "endpoint": str(client.base_url),
        "notify_email": (settings.get("notify") or {}).get("email"),
        "github_pat_configured": (
            (settings.get("github") or {}).get("token", {}).get("configured")
        ),
    }


def _bundle_source(
    playbook_path: str | None,
    playbook_yaml: str | None,
    playbook_uri: str | None = None,
) -> str:
    if sum(map(bool, (playbook_path, playbook_yaml, playbook_uri))) != 1:
        raise SatoriError(
            "Provide exactly one of playbook_path, playbook_yaml or playbook_uri."
        )

    if playbook_uri:
        if not playbook_uri.startswith("satori://"):
            raise SatoriError(
                "playbook_uri must be a catalog URI like satori://code/python/pyspector_v2.yml "
                "(see list_playbooks)."
            )
        return playbook_uri

    if playbook_yaml:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".satori.yml"
            path.write_text(playbook_yaml)
            bundle = make_bundle(path)
    else:
        path = Path(playbook_path).expanduser()  # type: ignore[arg-type]
        if not path.is_file() or path.suffix not in (".yml", ".yaml"):
            raise SatoriError(
                f"playbook_path must be an existing .yml file: {playbook_path}"
            )
        bundle = make_bundle(path)

    bundle_sha256 = sha256(bundle).hexdigest()
    if not (bundle_id := BundleCache.get_bundle_id(bundle_sha256)):
        bundle_id = client.post("/bundles", files={"bundle": bundle}).text
        BundleCache.set_bundle_id(bundle_sha256, bundle_id)
    return f"bundle://{bundle_id}"


def _first_execution_id(job_id: int, attempts: int = 15) -> int | None:
    for _ in range(attempts):
        items = client.get(
            "/executions", params={"job_id": job_id, "quantity": 1}
        ).json()["items"]
        if items:
            return items[0]["id"]
        time.sleep(1)
    return None


def _execution_summary(execution_id: int) -> dict:
    execution = client.get(f"/executions/{execution_id}").json()
    return shaping.summarize_execution(execution, report_url(execution_id))


@mcp.tool()
@_safe
def recommend_playbook(
    directory: str | None = None,
    prefs: dict[str, Any] | None = None,
) -> dict:
    """Recommend a quality-check playbook (lint, format, types, unit, security) for a repo.

    Detects the stack in `directory` (default: the server's current directory) for Python,
    JS/TS, Go, Java, C#, Rust, Ruby, PHP, Swift, C/C++ (CMake) or Solidity (Foundry), and
    returns content for `.satori-llm.yml` plus a `checks` list explaining why each check
    is there. `.satori.yml` is reserved for CI/manual runs and should
    `import: [file://.satori-llm.yml]`.

    If `.satori-llm.yml` already exists (or a legacy `.satori.yml` with
    `# satori:recommended`), returns `changes` instead of the full file; merge into
    `.satori-llm.yml` yourself. Only questions the repo cannot answer come back in
    `questions`: ask the user in chat, then call again with `prefs` (e.g.
    {"formatter": "black", "dead_code": false}). Prefs are saved in the LLM playbook's
    `# satori:recommended` header. Never write files without the user's approval.
    Workflow: run_local `.satori-llm.yml` BEFORE changing code to capture a baseline,
    and after each change fix only the failures that are not in the baseline.
    """
    root = Path(directory or ".").expanduser()
    if not root.is_dir():
        return {"error": f"directory must be an existing directory: {directory}"}
    root = root.resolve()

    llm_path = root / recommend.LLM_PLAYBOOK
    ci_path = root / recommend.CI_PLAYBOOK
    llm_text = (
        llm_path.read_text("utf-8", errors="replace") if llm_path.is_file() else None
    )
    ci_text = (
        ci_path.read_text("utf-8", errors="replace") if ci_path.is_file() else None
    )

    # Prefer .satori-llm.yml; fall back to a legacy recommended .satori.yml for migrate.
    legacy_ci = (
        llm_text is None
        and ci_text is not None
        and recommend.has_recommended_header(ci_text)
    )
    existing_llm = llm_text if llm_text is not None else (ci_text if legacy_ci else None)
    previous = recommend.parse_header(existing_llm) if existing_llm else None

    profile = recommend.detect(root)
    rec = recommend.build(profile, prefs, previous)

    result: dict[str, Any] = {
        "language": profile.language,
        "package_manager": profile.manager,
        "rules_version": rec.rules_version,
        "checks": [
            {k: c[k] for k in ("id", "category", "command", "blocking", "why")}
            for c in rec.checks
        ],
        "questions": rec.questions,
        "prefs": rec.prefs_used,
        "notes": rec.notes,
        "llm_playbook": recommend.LLM_PLAYBOOK,
        "ci_playbook": recommend.CI_PLAYBOOK,
    }

    hint_parts: list[str] = []
    if existing_llm is None:
        result["playbook_yaml"] = shaping.clip(rec.yaml, shaping.MAX_PLAYBOOK_CHARS)
        hint_parts.append(
            f"Write playbook_yaml to {recommend.LLM_PLAYBOOK} with the user's approval, "
            f"then run_local(playbook_path={recommend.LLM_PLAYBOOK!r})."
        )
    else:
        result["existing"] = True
        result["changes"] = recommend.diff_existing(existing_llm, rec)
        result["header"] = rec.header
        if legacy_ci:
            result["migrate_from_ci"] = True
            hint_parts.append(
                f"Move the recommended content out of {recommend.CI_PLAYBOOK} into "
                f"{recommend.LLM_PLAYBOOK}: merge `changes`, set the `# satori:recommended` "
                "header line to `header`, with the user's approval."
            )
        else:
            hint_parts.append(
                f"Merge `changes` into {recommend.LLM_PLAYBOOK} and replace its "
                "`# satori:recommended` header line with `header` (add it if missing), "
                "with the user's approval."
            )

    if ci_text is None:
        result["ci_playbook_yaml"] = recommend.ci_importer_yaml()
        hint_parts.append(
            f"Also write ci_playbook_yaml to {recommend.CI_PLAYBOOK} (imports the LLM file)."
        )
    elif not recommend.ci_imports_llm(ci_text):
        result["needs_ci_import"] = True
        result["ci_import_yaml"] = recommend.ci_importer_yaml()
        hint_parts.append(
            f"Add `import: - {recommend.LLM_IMPORT}` to {recommend.CI_PLAYBOOK} "
            "(see ci_import_yaml); do not overwrite existing CI checks."
        )

    if rec.questions:
        hint_parts.append(
            "Ask the user the `questions` first and call again with `prefs`; "
            "defaults were applied meanwhile."
        )
    result["hint"] = " ".join(hint_parts)
    return result


@mcp.tool()
@_safe
def run_playbook(
    playbook_path: str | None = None,
    playbook_yaml: str | None = None,
    playbook_uri: str | None = None,
    repository: str | None = None,
    parameters: dict[str, list[str]] | None = None,
    regions: list[str] | None = None,
    wait: bool = True,
    wait_seconds: int = 120,
) -> dict:
    """Run a playbook on Satori and (optionally) wait for the result.

    Provide EXACTLY ONE of playbook_path (local .yml file), playbook_yaml (inline YAML) or
    playbook_uri (a catalog playbook such as satori://code/python/pyspector_v2.yml; see list_playbooks).
    `repository` is an optional "owner/repo" to associate the run with (see list_repos).
    If the run is still going after wait_seconds (max 600), call get_execution later.
    Playbook syntax: read the satori-docs://playbooks/language resource first.
    For security/analysis tools, prefer JSON/JSONL stdout flags
    (satori-docs://playbooks/tool-output).
    """
    source = _bundle_source(playbook_path, playbook_yaml, playbook_uri)
    body = {
        "playbook_source": source,
        "parameters": parameters or {},
        "regions": regions or [],
        "count": 1,
        "save_report": True,
        "save_output": True,
        "repository": repository,
        "visibility": "PRIVATE",
    }
    run = client.post("/jobs/runs", json=body).json()
    job_id = run["id"]
    result: dict[str, Any] = {
        "job_id": job_id,
        "status": run.get("status"),
        "playbook_source": source,
    }

    execution_id = _first_execution_id(job_id)
    result["execution_id"] = execution_id
    if execution_id:
        result["report_url"] = report_url(execution_id)

    if not wait or execution_id is None:
        result["hint"] = (
            "Call get_execution(execution_id) to check progress, "
            "or stop_execution(execution_id) to cancel."
        )
        return result

    deadline = time.monotonic() + max(0, min(wait_seconds, 600))
    status = result["status"]
    while status not in ("FINISHED", "CANCELED") and time.monotonic() < deadline:
        time.sleep(2)
        status = client.get(f"/jobs/{job_id}").json()["status"]
    result["status"] = status

    if status in ("FINISHED", "CANCELED"):
        result["execution"] = _execution_summary(execution_id)
    else:
        result["hint"] = (
            f"Still {status} after {wait_seconds}s. "
            "Call get_execution(execution_id) later."
        )
    return result


LOCAL_DEFAULT_TIMEOUT = 300
LOCAL_MAX_TIMEOUT = 3600


@mcp.tool()
@_safe
async def run_local(
    playbook_path: str | None = None,
    playbook_yaml: str | None = None,
    playbook_uri: str | None = None,
    repository: str | None = None,
    directory: str | None = None,
    parameters: dict[str, list[str]] | None = None,
    run: list[str] | None = None,
    timeout_seconds: int = LOCAL_DEFAULT_TIMEOUT,
) -> dict:
    """Run a playbook's commands on THIS machine, upload the results and return the execution.

    Unlike run_playbook, commands execute locally with the user's privileges, so only run
    playbooks the user asked for or that you wrote for them. Provide EXACTLY ONE of
    playbook_path, playbook_yaml or playbook_uri. Working directory: `repository`
    ("owner/repo", shallow-cloned to a temp dir) OR `directory` (existing local dir);
    default is the server's current directory. `run` limits execution to test paths with
    those prefixes. timeout_seconds max 3600.
    Returns the same shape as run_playbook; analyze with get_execution_output and list_findings.
    """
    if repository and directory:
        return {"error": "Provide only one of repository or directory."}
    if repository and repository.endswith("/*"):
        return {"error": "wildcard is not supported on local"}
    if repository and not is_github_repo(repository):
        return {"error": "repository must be 'owner/repo'."}
    if directory and not Path(directory).expanduser().is_dir():
        return {"error": f"directory must be an existing directory: {directory}"}

    source = await asyncio.to_thread(
        _bundle_source, playbook_path, playbook_yaml, playbook_uri
    )
    timeout = max(1, min(timeout_seconds, LOCAL_MAX_TIMEOUT))

    clone_tmpdir = None
    try:
        workdir = str(Path(directory).expanduser()) if directory else None
        if repository:
            git = require_git(quiet=True)
            clone_tmpdir = tempfile.TemporaryDirectory(prefix="satori-local-")
            workdir = str(
                await asyncio.to_thread(
                    clone_repo, git, repository, Path(clone_tmpdir.name), True
                )
            )
        outcome = await run_local_job(
            source,
            parameters=parameters or {},
            repository=repository,
            workdir=workdir,
            run=tuple(run or ()),
            timeout=timeout,
            needs_report=True,
        )
    finally:
        if clone_tmpdir is not None:
            clone_tmpdir.cleanup()

    result: dict[str, Any] = {
        "job_id": outcome.job["id"],
        "status": "CANCELED" if outcome.timed_out else "FINISHED",
        "playbook_source": source,
        "execution_id": outcome.execution_id,
    }
    if outcome.timed_out:
        result["timed_out"] = True
    if outcome.execution_id is None:
        result["hint"] = (
            "Results were uploaded but no execution appeared yet; "
            "call get_job(job_id) or list_executions(job_id=...) later."
        )
        return result

    result["report_url"] = report_url(outcome.execution_id)
    result["execution"] = await asyncio.to_thread(
        _execution_summary, outcome.execution_id
    )
    result["hint"] = (
        "Call get_execution_output(execution_id, test=...) for logs and "
        "list_findings(execution_id=...) for findings."
    )
    return result


@mcp.tool()
@_safe
def get_execution(execution_id: int) -> dict:
    """Status and assertion results of an execution (no logs; use get_execution_output)."""
    return _execution_summary(execution_id)


@mcp.tool()
@_safe
def list_executions(
    job_id: int | None = None,
    status: list[str] | None = None,
    report_status: str | None = None,
    job_type: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    q: str | None = None,
    visibility: str | None = None,
    severity: int | None = None,
    playbook: str | None = None,
    tags: list[str] | None = None,
    id_gt: int | None = None,
    id_lt: int | None = None,
    global_: bool = False,
    order: str | None = None,
    quantity: int = 25,
    page: int = 1,
) -> dict:
    """List reports (executions), newest first.

    In Satori, reports = executions. Use list_executions (or list_reports) to list reports.
    status: any of QUEUED, RUNNING, FINISHED, CANCELED. report_status: PASS or FAIL.
    job_type: RUN, SCAN, MONITOR, GITHUB or LOCAL. from_/to: ISO datetimes (from_ < to).
    visibility: PUBLIC, PRIVATE or UNLISTED. severity: report severity 0-5.
    playbook: playbook filter. tags: key:value strings. id_gt/id_lt: id range.
    global_: include public executions from others. order: ASC or DESC (default DESC).
    q: free-text search. Max 25 per page; use next_page to continue.
    """
    visibility = visibility.upper() if visibility else None
    order = order.upper() if order else None
    if report_status and report_status not in REPORT_STATUSES:
        return {"error": f"report_status must be one of {REPORT_STATUSES}"}
    if job_type and job_type not in JOB_TYPES:
        return {"error": f"job_type must be one of {JOB_TYPES}"}
    if visibility and visibility not in VISIBILITIES:
        return {"error": f"visibility must be one of {VISIBILITIES}"}
    if severity is not None and (severity < 0 or severity > 5):
        return {"error": "severity must be an int 0-5."}
    if order and order not in ORDERS:
        return {"error": f"order must be one of {ORDERS}"}
    if from_ and to and from_ >= to:
        return {"error": "from_ must be earlier than to."}

    quantity = max(1, min(quantity, 25))
    params: dict[str, Any] = {
        "quantity": quantity,
        "page": page,
        "order": order or "DESC",
    }
    optional = {
        "job_id": job_id,
        "status": status,
        "report_status": report_status,
        "job_type": job_type,
        "from": from_,
        "to": to,
        "q": q,
        "visibility": visibility,
        "severity": severity,
        "playbook": playbook,
        "tags": tags,
        "id_gt": id_gt,
        "id_lt": id_lt,
    }
    params.update({k: v for k, v in optional.items() if v is not None and v != []})
    if global_:
        params["global"] = True
    data = client.get("/executions", params=params).json()
    return shaping.paged(
        [
            shaping.summarize_execution_row(e, report_url(e["id"]))
            for e in data["items"]
        ],
        data.get("total"),
        page,
        quantity,
    )


@mcp.tool()
@_safe
def list_reports(
    job_id: int | None = None,
    status: list[str] | None = None,
    report_status: str | None = None,
    job_type: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    q: str | None = None,
    visibility: str | None = None,
    severity: int | None = None,
    playbook: str | None = None,
    tags: list[str] | None = None,
    id_gt: int | None = None,
    id_lt: int | None = None,
    global_: bool = False,
    order: str | None = None,
    quantity: int = 25,
    page: int = 1,
) -> dict:
    """Alias for list_executions. In Satori, reports = executions."""
    return list_executions(
        job_id=job_id,
        status=status,
        report_status=report_status,
        job_type=job_type,
        from_=from_,
        to=to,
        q=q,
        visibility=visibility,
        severity=severity,
        playbook=playbook,
        tags=tags,
        id_gt=id_gt,
        id_lt=id_lt,
        global_=global_,
        order=order,
        quantity=quantity,
        page=page,
    )


@mcp.tool()
@_safe
def stop_execution(execution_id: int) -> dict:
    """Cancel a RUNNING execution (e.g. after run_playbook with wait=false)."""
    status = client.get(f"/executions/{execution_id}").json().get("status")
    if status != "RUNNING":
        return {
            "execution_id": execution_id,
            "status": status,
            "stopped": False,
            "hint": "Only RUNNING executions can be stopped.",
        }
    client.patch(f"/executions/{execution_id}", json={"status": "CANCELED"})
    return {
        "execution_id": execution_id,
        "stopped": True,
        "hint": "Cancellation is asynchronous; call get_execution to confirm.",
    }


@mcp.tool()
@_safe
def get_execution_playbook(execution_id: int) -> dict:
    """The playbook YAML an execution ran (capped), to debug or iterate on it."""
    text = client.get(f"/executions/{execution_id}/playbook").text
    return {
        "execution_id": execution_id,
        "yaml": shaping.clip(text, shaping.MAX_PLAYBOOK_CHARS),
        "truncated": len(text) > shaping.MAX_PLAYBOOK_CHARS,
    }


@mcp.tool()
@_safe
def get_execution_output(
    execution_id: int,
    test: str | None = None,
    stream: str = "stdout",
    tail_lines: int = 100,
    offset_from_end: int = 0,
) -> dict:
    """Read execution logs, always capped.

    Without `test`, returns only an index of tests with line counts per stream.
    With `test` (a test path such as "cmd.0", or "cmd.0.stderr" to pick a stream),
    returns the last `tail_lines` (max 500, 20k chars) lines of `stream`.
    Use offset_from_end (from next_offset_from_end) to page backwards.
    """
    if stream not in shaping.OUTPUT_STREAMS:
        return {"error": f"stream must be one of {shaping.OUTPUT_STREAMS}"}

    outputs = load_execution_outputs(execution_id)
    if not test:
        return {
            "execution_id": execution_id,
            "tests": shaping.output_index(outputs),
            "hint": "Call again with `test` set to one of these paths to read its output.",
        }

    path, _, suffix = test.replace(":", ".").rpartition(".")
    if suffix in shaping.OUTPUT_STREAMS:
        stream = suffix
    else:
        path = test.replace(":", ".")
    selected = run_test_filter([path], [dict(o) for o in outputs])
    if not selected:
        return {
            "error": f"No test matches {test!r}.",
            "tests": shaping.output_index(outputs),
        }

    picked = selected[0]
    text = str((picked.get("output") or {}).get(stream) or "")
    result = shaping.tail_lines(text, tail_lines, offset_from_end)
    result.update(
        {"execution_id": execution_id, "path": picked["path"], "stream": stream}
    )
    return result


@mcp.tool()
@_safe
def list_findings(
    execution_id: int | None = None,
    severity: list[int | str] | None = None,
    status: str | None = None,
    source: str | None = None,
    order: str | None = None,
    quantity: int = 25,
    page: int = 1,
) -> dict:
    """List findings (severity 0-5 or INFO/LOW/MEDIUM/HIGH/CRITICAL/BLOCKER).

    status: OPEN, INVESTIGATING, TP, FIXED, FP, ACCEPTED.
    source: ASSERT (playbook assertion failures) or TOOL (findings parsed from tool output).
    order: ASC or DESC by creation time.
    """
    status = status.upper() if status else None
    source = source.upper() if source else None
    order = order.upper() if order else None
    if status and status not in FINDING_STATUSES:
        return {"error": f"status must be one of {FINDING_STATUSES}"}
    if source and source not in FINDING_SOURCES:
        return {"error": f"source must be one of {FINDING_SOURCES}"}
    if order and order not in ORDERS:
        return {"error": f"order must be one of {ORDERS}"}
    severities: list[int] | None = None
    if severity:
        normalized = normalize_severities(severity)
        if isinstance(normalized, str):
            return {"error": normalized}
        severities = normalized
    quantity = max(1, min(quantity, 25))
    params: dict[str, Any] = {"quantity": quantity, "page": page}
    if execution_id is not None:
        params["execution_id"] = execution_id
    if severities:
        params["severity"] = severities
    if status:
        params["status"] = status
    if source:
        params["source"] = source
    if order:
        params["order"] = order
    data = client.get("/findings", params=params).json()
    return shaping.paged(
        [shaping.summarize_finding(f) for f in data["items"]],
        data.get("total"),
        page,
        quantity,
    )


@mcp.tool()
@_safe
def get_finding(finding_id: int, include_timeline: bool = True) -> dict:
    """Details of one finding plus its recent timeline (status changes and comments)."""
    result = shaping.detail_finding(client.get(f"/findings/{finding_id}").json())
    if include_timeline:
        result.update(
            shaping.summarize_timeline(
                client.get(f"/findings/{finding_id}/timeline").json()
            )
        )
    return result


@mcp.tool()
@_safe
def get_finding_timeline(finding_id: int) -> dict:
    """Status changes and comments for a finding (capped), without the finding body.

    Prefer this when you only need history; use get_finding for full details.
    """
    return shaping.summarize_timeline(
        client.get(f"/findings/{finding_id}/timeline").json()
    )


@mcp.tool()
@_safe
def update_finding_status(
    finding_id: int, status: str, comment: str | None = None
) -> dict:
    """Triage a finding: set its status, optionally adding a comment explaining why.

    status: OPEN, INVESTIGATING, TP (true positive), FIXED, FP (false positive) or ACCEPTED.
    Changes shared triage state; use only when the user asked to triage this finding.
    """
    status = status.upper()
    if status not in FINDING_STATUSES:
        return {"error": f"status must be one of {FINDING_STATUSES}"}
    if comment is not None and len(comment) > shaping.MAX_COMMENT_CHARS:
        return {"error": f"comment exceeds {shaping.MAX_COMMENT_CHARS} characters."}

    updated = client.patch(f"/findings/{finding_id}", json={"status": status}).json()
    result: dict[str, Any] = {"id": finding_id, "status": updated.get("status", status)}
    if comment:
        try:
            result["comment_id"] = client.post(
                f"/findings/{finding_id}/comments", json={"body": comment}
            ).json()["id"]
        except httpx2.HTTPStatusError as e:
            result["comment_error"] = shaping.clip(e.response.text, 500)
    return result


@mcp.tool()
@_safe
def add_finding_comment(finding_id: int, body: str) -> dict:
    """Post a comment on a finding without changing its status.

    Use only when the user asked to comment. To triage and comment together, use
    update_finding_status with comment=... instead.
    """
    if not body or not body.strip():
        return {"error": "body must be a non-empty comment."}
    if len(body) > shaping.MAX_COMMENT_CHARS:
        return {"error": f"comment exceeds {shaping.MAX_COMMENT_CHARS} characters."}
    comment_id = client.post(
        f"/findings/{finding_id}/comments", json={"body": body}
    ).json()["id"]
    return {"finding_id": finding_id, "comment_id": comment_id}


@mcp.tool()
@_safe
def list_jobs(
    type: str | None = None,
    visibility: str | None = None,
    quantity: int = 25,
    page: int = 1,
) -> dict:
    """List jobs, newest first (a job is the parent of executions; use it to recover a job_id).

    type: RUN, SCAN or MONITOR. visibility: PUBLIC, PRIVATE or UNLISTED.
    Max 25 per page; use next_page to continue.
    """
    visibility = visibility.upper() if visibility else None
    if type and type not in LISTABLE_JOB_TYPES:
        return {"error": f"type must be one of {LISTABLE_JOB_TYPES}"}
    if visibility and visibility not in VISIBILITIES:
        return {"error": f"visibility must be one of {VISIBILITIES}"}
    quantity = max(1, min(quantity, 25))
    params: dict[str, Any] = {"quantity": quantity, "page": page, "order": "DESC"}
    if type:
        params["type"] = type
    if visibility:
        params["visibility"] = visibility
    data = client.get("/jobs", params=params).json()
    return shaping.paged(
        [shaping.summarize_job(j) for j in data["items"]],
        data.get("total"),
        page,
        quantity,
    )


@mcp.tool()
@_safe
def get_job(job_id: int) -> dict:
    """A job and its 5 most recent executions (no playbook body; see get_execution_playbook)."""
    result = shaping.summarize_job(client.get(f"/jobs/{job_id}").json())
    items = client.get(
        "/executions", params={"job_id": job_id, "quantity": 5, "order": "DESC"}
    ).json()["items"]
    result["executions"] = [
        shaping.summarize_execution_row(e, report_url(e["id"])) for e in items
    ]
    return result


@mcp.tool()
@_safe
def scan_repository(
    repository: str,
    playbook_path: str | None = None,
    playbook_yaml: str | None = None,
    playbook_uri: str | None = None,
    parameters: dict[str, list[str]] | None = None,
    regions: list[str] | None = None,
    quantity: int = 1,
) -> dict:
    """Start a scan of a GitHub repository with a playbook. Returns immediately.

    `repository` is required, as "owner/repo" (see list_repos), or "owner/*" to scan
    the HEAD of every repository of owner (up to 100) in one job; only use "owner/*"
    when the user asked for all of an owner's repositories. Optionally provide
    EXACTLY ONE of playbook_path, playbook_yaml or playbook_uri (e.g.
    satori://code/python/pyspector_v2.yml, see list_playbooks). When none are given,
    the API uses the repository root .satori.yml (each repository's own for "owner/*",
    skipping repositories without one). `quantity` is how many executions to create
    (max 10; always 1 per repository for "owner/*"). Poll with get_job(job_id) /
    list_executions(job_id=...); results via get_execution.
    """
    wildcard = (repository or "").endswith("/*") and bool(wildcard_owner(repository))
    if not wildcard and not is_github_repo(repository or ""):
        return {"error": "repository must be 'owner/repo' or 'owner/*'."}
    provided = sum(map(bool, (playbook_path, playbook_yaml, playbook_uri)))
    if provided > 1:
        return {
            "error": (
                "Provide at most one of playbook_path, playbook_yaml or playbook_uri."
            )
        }
    source = (
        _bundle_source(playbook_path, playbook_yaml, playbook_uri)
        if provided == 1
        else None
    )
    quantity = 1 if wildcard else max(1, min(quantity, MAX_SCAN_QUANTITY))
    body: dict[str, Any] = {
        "parameters": parameters or {},
        "regions": regions or [],
        "repository_data": {"repository": repository},
        "criteria": {"quantity": quantity},
        "visibility": "PRIVATE",
    }
    if source is not None:
        body["playbook_source"] = source
    scan = client.post("/jobs/scans", json=body).json()
    return {
        "job_id": scan["id"],
        "status": scan.get("status"),
        "repository": repository,
        "playbook_source": scan.get("playbook_source") or source,
        "hint": "Call get_job(job_id) to follow progress and see its executions.",
    }


@mcp.tool()
@_safe
def list_scans(
    visibility: str | None = None, quantity: int = 25, page: int = 1
) -> dict:
    """List scan jobs, newest first (same as list_jobs with type=SCAN)."""
    return list_jobs(type="SCAN", visibility=visibility, quantity=quantity, page=page)


@mcp.tool()
@_safe
def list_playbooks(
    q: str | None = None,
    category: str | None = None,
    quantity: int = 25,
    page: int = 1,
) -> dict:
    """Search the catalog of ready-made playbooks (satori://...) instead of writing YAML.

    q: case-insensitive match on id, name or description. category: e.g. api, code, cloud.
    Run one with run_playbook/scan_repository(playbook_uri=...); read details with get_playbook.
    """
    quantity = max(1, min(quantity, 25))
    catalog = playbooks_client.get("/playbooks").json()["playbooks"]
    needle = q.lower() if q else None
    matches = [
        p
        for p in catalog
        if (not category or p.get("category", "").lower() == category.lower())
        and (
            not needle
            or needle
            in " ".join(
                str(p.get(k, "")) for k in ("id", "name", "description")
            ).lower()
        )
    ]
    start = (page - 1) * quantity
    return shaping.paged(
        [
            shaping.summarize_catalog_playbook(p)
            for p in matches[start : start + quantity]
        ],
        len(matches),
        page,
        quantity,
    )


@mcp.tool()
@_safe
def get_playbook(playbook_uri: str) -> dict:
    """Details and YAML of a catalog playbook (satori://... URI or its id), capped."""
    playbook_id = playbook_uri.removeprefix("satori://")
    data = playbooks_client.get(f"/playbooks/{playbook_id}").json()
    result = shaping.summarize_catalog_playbook(data)
    content = data.get("content") or ""
    result["image"] = data.get("image")
    result["example"] = data.get("example")
    result["yaml"] = shaping.clip(content, shaping.MAX_PLAYBOOK_CHARS)
    result["truncated"] = len(content) > shaping.MAX_PLAYBOOK_CHARS
    return result


@mcp.tool()
@_safe
def list_advisories(
    execution_id: int | None = None,
    kind: str | None = None,
    provider: str | None = None,
    order: str | None = None,
    quantity: int = 25,
    page: int = 1,
) -> dict:
    """List external issues you already created from findings (read-only).

    kind: SECURITY_ADVISORY or ISSUE. provider: GITHUB. order: ASC or DESC.
    Returns titles and links (external_url), not the full advisory text.
    """
    kind = kind.upper() if kind else None
    provider = provider.upper() if provider else None
    order = order.upper() if order else None
    if kind and kind not in ADVISORY_KINDS:
        return {"error": f"kind must be one of {ADVISORY_KINDS}"}
    if provider and provider not in ADVISORY_PROVIDERS:
        return {"error": f"provider must be one of {ADVISORY_PROVIDERS}"}
    if order and order not in ORDERS:
        return {"error": f"order must be one of {ORDERS}"}
    quantity = max(1, min(quantity, 25))
    optional = {
        "execution_id": execution_id,
        "kind": kind,
        "provider": provider,
        "order": order,
    }
    params: dict[str, Any] = {"quantity": quantity, "page": page}
    params.update({k: v for k, v in optional.items() if v is not None})
    data = client.get("/external_issues", params=params).json()
    return shaping.paged(
        [shaping.summarize_advisory(a) for a in data["items"]],
        data.get("total"),
        page,
        quantity,
    )


@mcp.tool()
@_safe
def list_monitors(
    visibility: str | None = None, quantity: int = 25, page: int = 1
) -> dict:
    """List monitor jobs with their schedule `expression` (read-only; same as list_jobs type=MONITOR)."""
    return list_jobs(
        type="MONITOR", visibility=visibility, quantity=quantity, page=page
    )


@mcp.tool()
@_safe
def list_repos(order: str | None = None, quantity: int = 50, page: int = 1) -> dict:
    """List repositories (owner/repo) Satori can target, with their last execution.

    order: ASC or DESC by last activity.
    """
    order = order.upper() if order else None
    if order and order not in ORDERS:
        return {"error": f"order must be one of {ORDERS}"}
    quantity = max(1, min(quantity, 50))
    params: dict[str, Any] = {"quantity": quantity, "page": page}
    if order:
        params["order"] = order
    data = client.get("/repos", params=params).json()
    return shaping.paged(
        [shaping.summarize_repo(r) for r in data["items"]],
        data.get("total"),
        page,
        quantity,
    )


def _fetch_doc(name: str) -> str:
    url = f"{DOCS_URL}/{DOC_PAGES[name]}.md"
    try:
        res = httpx2.get(url, follow_redirects=True, timeout=10)
        res.raise_for_status()
    except httpx2.HTTPError as e:
        return (
            f"Could not fetch {url} ({e}). Docs source: "
            f"satori-docs/satori_help/docs/{DOC_PAGES[name]}.md"
        )
    return shaping.clip(res.text, DOC_MAX_CHARS)


@mcp.resource("satori-docs://playbooks/language")
def doc_language() -> str:
    """Playbook language reference."""
    return _fetch_doc("language")


@mcp.resource("satori-docs://playbooks/asserts")
def doc_asserts() -> str:
    """Playbook asserts reference."""
    return _fetch_doc("asserts")


@mcp.resource("satori-docs://playbooks/inputs")
def doc_inputs() -> str:
    """Playbook inputs reference."""
    return _fetch_doc("inputs")


@mcp.resource("satori-docs://playbooks/settings")
def doc_settings() -> str:
    """Playbook settings reference."""
    return _fetch_doc("settings")


@mcp.resource("satori-docs://playbooks/execution")
def doc_execution() -> str:
    """Playbook execution reference."""
    return _fetch_doc("execution")


@mcp.resource("satori-docs://playbooks/tool-output")
def doc_tool_output() -> str:
    """Prefer JSON tool stdout so Satori can parse TOOL findings."""
    return _fetch_doc("tool-output")


@mcp.prompt()
def write_and_run_playbook(goal: str) -> str:
    """Write a Satori playbook for a goal, run it and report the result."""
    return (
        f"Goal: {goal}\n\n"
        "1. Read the satori-docs://playbooks/language resource (and asserts if needed).\n"
        "2. If the playbook runs a security/analysis tool, read "
        "satori-docs://playbooks/tool-output and prefer that tool's JSON/JSONL flags "
        "over human-readable defaults.\n"
        "3. Write the playbook YAML.\n"
        "4. Call run_playbook with playbook_yaml (a validation error is returned verbatim; fix and retry).\n"
        "5. Call get_execution; if there are failures, call get_execution_output with a `test` "
        "filter (never request full logs) and list_findings(execution_id=...).\n"
        "6. Summarize the result and include the report_url."
    )


def serve() -> None:
    mcp.run(transport="stdio")
