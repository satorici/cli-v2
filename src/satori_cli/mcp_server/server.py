"""Local stdio MCP server: a thin, task-shaped client of the Satori v2 API.

stdout is the protocol channel. Nothing in here may print to it.
"""

import os
import re
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
from ..utils.output_filter import run_test_filter
from . import shaping

DOCS_URL = os.getenv("SATORI_DOCS_URL", "https://docs-v2.satori.ci").rstrip("/")
DOC_MAX_CHARS = 30_000
DOC_PAGES = {
    "language": "playbooks/language",
    "asserts": "playbooks/asserts",
    "inputs": "playbooks/inputs",
    "settings": "playbooks/settings",
    "execution": "playbooks/execution",
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
REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
MAX_SCAN_QUANTITY = 10

mcp = FastMCP(
    "satori",
    instructions=(
        "Satori CI. Write a playbook (read the satori-docs://playbooks/language resource), "
        "call run_playbook, then get_execution for pass/fail and get_execution_output "
        "with a `test` filter for logs. In Satori, reports = executions; use "
        "list_executions (or list_reports) to list reports. Use get_execution_playbook "
        "to read the YAML of a run, and stop_execution to cancel a running one. "
        "Use list_jobs/get_job to find a job and its executions, and "
        "update_finding_status to triage a finding (only when asked). "
        "list_playbooks/get_playbook browse ready-made catalog playbooks (use via "
        "playbook_uri); scan_repository scans one named owner/repo. "
        "Output is always capped."
    ),
)


def _safe(fn):
    """Turn API/auth failures into small error dicts instead of protocol errors."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AuthError:
            return {"error": "Not logged in. Run: satori-v2 config token <token>"}
        except httpx2.HTTPStatusError as e:
            status = e.response.status_code
            result: dict[str, Any] = {
                "error": shaping.clip(e.response.text, 2000),
                "status": status,
            }
            if status == 403:
                result["hint"] = "This action needs a PRO or ENTERPRISE plan."
            return result
        except httpx2.TimeoutException:
            return {"error": "Request to the Satori API timed out."}
        except SatoriError as e:
            return {"error": str(e)}

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
    """Start a scan of ONE GitHub repository with a playbook. Returns immediately.

    `repository` is required, as "owner/repo" (see list_repos). Provide EXACTLY ONE of
    playbook_path, playbook_yaml or playbook_uri (e.g. satori://code/python/pyspector_v2.yml,
    see list_playbooks). `quantity` is how many executions to create (max 10).
    Poll with get_job(job_id) / list_executions(job_id=...); results via get_execution.
    """
    if not REPO_RE.match(repository or ""):
        return {"error": "repository must be 'owner/repo'."}
    source = _bundle_source(playbook_path, playbook_yaml, playbook_uri)
    quantity = max(1, min(quantity, MAX_SCAN_QUANTITY))
    body = {
        "playbook_source": source,
        "parameters": parameters or {},
        "regions": regions or [],
        "repository_data": {"repository": repository},
        "criteria": {"quantity": quantity},
        "visibility": "PRIVATE",
    }
    scan = client.post("/jobs/scans", json=body).json()
    return {
        "job_id": scan["id"],
        "status": scan.get("status"),
        "repository": repository,
        "playbook_source": source,
        "hint": "Call get_job(job_id) to follow progress and see its executions.",
    }


@mcp.tool()
@_safe
def list_scans(
    visibility: str | None = None, quantity: int = 25, page: int = 1
) -> dict:
    """List scan jobs, newest first (same as list_jobs with type=SCAN)."""
    return list_jobs(
        type="SCAN", visibility=visibility, quantity=quantity, page=page
    )


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
def list_repos(
    order: str | None = None, quantity: int = 50, page: int = 1
) -> dict:
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


@mcp.prompt()
def write_and_run_playbook(goal: str) -> str:
    """Write a Satori playbook for a goal, run it and report the result."""
    return (
        f"Goal: {goal}\n\n"
        "1. Read the satori-docs://playbooks/language resource (and asserts if needed).\n"
        "2. Write the playbook YAML.\n"
        "3. Call run_playbook with playbook_yaml (a validation error is returned verbatim; fix and retry).\n"
        "4. Call get_execution; if there are failures, call get_execution_output with a `test` "
        "filter (never request full logs) and list_findings(execution_id=...).\n"
        "5. Summarize the result and include the report_url."
    )


def serve() -> None:
    mcp.run(transport="stdio")
