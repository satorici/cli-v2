"""Silent core of a local run: nothing in here may print (MCP stdout is the protocol)."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from tempfile import SpooledTemporaryFile
from typing import IO, Any, Optional

import httpx2
import msgpack

from ..api import client
from .execution.runner import TimedOut, process_commands


@dataclass
class LocalRunResult:
    job: dict
    execution_id: Optional[int]
    report: Optional[dict]
    timed_out: bool


async def run_local_job(
    playbook_source: str,
    *,
    parameters: Optional[dict[str, Any]] = None,
    visibility: str = "PRIVATE",
    tags: Optional[dict[str, str]] = None,
    repository: Optional[str] = None,
    workdir: Optional[str] = None,
    run: tuple[str, ...] = (),
    timeout: Optional[int] = None,
    needs_report: bool = True,
    results: Optional[IO[bytes]] = None,
    on_running: Optional[Callable[[str], None]] = None,
    on_job: Optional[Callable[[dict], None]] = None,
    poll_attempts: int = 60,
    poll_interval: float = 2,
) -> LocalRunResult:
    """Create a LOCAL job, run its recipe in ``workdir``, upload results, find the execution."""
    body = {
        "playbook_source": playbook_source,
        "parameters": parameters,
        "visibility": visibility,
        "tags": tags or {},
        "repository": repository,
    }
    local_job = (await asyncio.to_thread(client.post, "/jobs/locals", json=body)).json()
    if on_job is not None:
        on_job(local_job)

    own_results = results is None
    results = results if results is not None else SpooledTemporaryFile()
    timed_out = False
    try:
        with SpooledTemporaryFile() as recipe:
            res = await asyncio.to_thread(httpx2.get, local_job["recipe_url"])
            recipe.write(res.content)
            recipe.seek(0)
            unpacked = msgpack.Unpacker(recipe)
            if run:
                unpacked = (c for c in unpacked if c["path"].startswith(tuple(run)))

            settings = (
                await asyncio.to_thread(httpx2.get, local_job["settings_url"])
            ).json()

            try:
                async for cline, result in process_commands(
                    unpacked,
                    settings,
                    timeout,
                    on_running=on_running,
                    cwd=workdir,
                ):
                    msgpack.pack(cline | {"output": result}, results)
            except TimedOut:
                timed_out = True

        fields = {"x-amz-meta-status": "CANCELED" if timed_out else "FINISHED"}
        results.seek(0)
        upload = local_job["results_upload"]
        res = await asyncio.to_thread(
            httpx2.post,
            upload["url"],
            data=upload["fields"] | fields,
            files={"file": results},
        )
        res.raise_for_status()

        execution_id: Optional[int] = None
        report: Optional[dict] = None
        # The execution (and its report) are created by the backend after the
        # results upload, so poll instead of querying once.
        for _ in range(poll_attempts):
            res = await asyncio.to_thread(
                client.get,
                "/executions",
                params={"job_id": local_job["id"], "quantity": 1},
            )
            if items := res.json()["items"]:
                execution_id = items[0]["id"]
                if not needs_report:
                    break
                execution = (
                    await asyncio.to_thread(client.get, f"/executions/{execution_id}")
                ).json()
                if report := execution.get("report"):
                    break
            await asyncio.sleep(poll_interval)
    finally:
        if own_results:
            results.close()

    return LocalRunResult(local_job, execution_id, report, timed_out)
