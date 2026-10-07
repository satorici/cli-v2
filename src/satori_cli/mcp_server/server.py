"""Local stdio MCP server: a thin, task-shaped client of the Satori v2 API.

stdout is the protocol channel. Nothing in here may print to it.
"""

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
from ..config import config
from ..constants import report_url
from ..exceptions import AuthError, SatoriError
from ..models import BundleCache
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

mcp = FastMCP(
    "satori",
    instructions=(
        "Satori CI. Write a playbook (read the satori-docs://playbooks/language resource), "
        "call run_playbook, then get_execution for pass/fail and get_execution_output "
        "with a `test` filter for logs. Output is always capped."
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


def _bundle_source(playbook_path: str | None, playbook_yaml: str | None) -> str:
    if bool(playbook_path) == bool(playbook_yaml):
        raise SatoriError("Provide exactly one of playbook_path or playbook_yaml.")

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
    repository: str | None = None,
    parameters: dict[str, list[str]] | None = None,
    regions: list[str] | None = None,
    wait: bool = True,
    wait_seconds: int = 120,
) -> dict:
    """Run a playbook on Satori and (optionally) wait for the result.

    Provide EXACTLY ONE of playbook_path (local .yml file) or playbook_yaml (inline YAML).
    `repository` is an optional "owner/repo" to associate the run with (see list_repos).
    If the run is still going after wait_seconds (max 600), call get_execution later.
    Playbook syntax: read the satori-docs://playbooks/language resource first.
    """
    source = _bundle_source(playbook_path, playbook_yaml)
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
        result["hint"] = "Call get_execution(execution_id) to check progress."
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
    severity: list[int] | None = None,
    status: str | None = None,
    quantity: int = 25,
    page: int = 1,
) -> dict:
    """List findings (severity 0-5; status OPEN, INVESTIGATING, TP, FIXED, FP, ACCEPTED)."""
    quantity = max(1, min(quantity, 25))
    params: dict[str, Any] = {"quantity": quantity, "page": page}
    if execution_id is not None:
        params["execution_id"] = execution_id
    if severity:
        params["severity"] = severity
    if status:
        params["status"] = status
    data = client.get("/findings", params=params).json()
    return shaping.paged(
        [shaping.summarize_finding(f) for f in data["items"]],
        data.get("total"),
        page,
        quantity,
    )


@mcp.tool()
@_safe
def get_finding(finding_id: int) -> dict:
    """Details of one finding (snapshot is truncated)."""
    return shaping.detail_finding(client.get(f"/findings/{finding_id}").json())


@mcp.tool()
@_safe
def list_repos(quantity: int = 50, page: int = 1) -> dict:
    """List repositories (owner/repo) Satori can target, with their last execution."""
    quantity = max(1, min(quantity, 50))
    data = client.get("/repos", params={"quantity": quantity, "page": page}).json()
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
