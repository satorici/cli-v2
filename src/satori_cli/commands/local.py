import asyncio
import os
import tempfile
import time
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Optional

import httpx2
import msgpack
import rich_click as click
from rich import progress
from rich.live import Live
from rich.table import Table

from ..api import client
from ..exceptions import SatoriError
from ..models import Playbook
from ..utils import options as opts
from ..utils.arguments import Source, source_arg
from ..utils.console import format_raw_results, stderr, stdout
from ..utils.execution.runner import TimedOut, process_commands
from ..utils.format import is_json_output
from ..utils.git_clone import clone_repo, require_git
from ..utils.highlight import highlight_result
from ..utils.verify_issue import list_finding_ids_for_execution
from ..utils.verify_issue import verify_findings as run_verify_findings
from ..utils.wrappers import JobWrapper, ReportWrapper
from .issue import list_issues


def _verify_execution(execution_id: int) -> None:
    finding_ids = list_finding_ids_for_execution(execution_id)
    if not finding_ids:
        stderr.print(f"No findings to verify for execution {execution_id}.")
        return
    stderr.print(
        f"Verifying {len(finding_ids)} finding(s) for execution {execution_id}…"
    )
    run_verify_findings(finding_ids)


@click.command()
@source_arg
@opts.playbook_opt
@opts.input_opt
@opts.split_opt
@opts.data_file_opt
@click.option("--timeout", type=int)
@click.option("--run", multiple=True)
@opts.visibility_opt
@click.option("--tag", "-t", "tags", multiple=True, type=(str, str))
@click.option("--output", "-o", "show_output", is_flag=True)
@click.option("--report", "show_report", is_flag=True)
@click.option("--issues", "show_issues", is_flag=True)
@click.option("--repository", "--repo", "repository")
@click.option(
    "--verify",
    "do_verify",
    is_flag=True,
    help="After the local run finishes, verify every finding with Claude Code (TP/FP).",
)
@opts.sync_opt
def local(
    source: Source,
    playbook: Optional[Playbook],
    input: Optional[dict[str, list[str]]],
    split: Optional[dict[str, str]],
    data_file: Optional[tuple[str]],
    timeout: Optional[int],
    run: Optional[tuple[str]],
    visibility: Optional[str],
    tags: Optional[tuple[tuple[str, str]]],
    show_output: bool,
    show_report: bool,
    show_issues: bool,
    repository: Optional[str],
    do_verify: bool,
    sync: bool,
    **kwargs,
):
    if do_verify and not repository:
        raise click.UsageError("--verify requires --repo so findings can be resolved.")

    input = opts.apply_splits(input, split)
    input = opts.apply_data_files(input, data_file)

    playbook_data = playbook.playbook_data() if playbook else source.playbook_data()

    if tags:
        tags_obj = {k: v for k, v in tags}
    else:
        tags_obj = {}

    body = {
        "playbook_source": playbook_data,
        "parameters": input,
        "visibility": visibility or "PRIVATE",
        "tags": tags_obj,
        "repository": repository,
    }

    local_job = client.post("/jobs/locals", json=body).json()

    use_progress = not is_json_output() and not show_output
    execution_id = None
    report = None
    needs_report = show_report or sync or show_issues or do_verify

    clone_tmpdir = None
    work_dir: Optional[str] = None
    original_cwd = os.getcwd()
    if repository:
        git = require_git()
        clone_tmpdir = tempfile.TemporaryDirectory(prefix="satori-local-")
        work_dir = str(clone_repo(git, repository, Path(clone_tmpdir.name)))

    try:
        with SpooledTemporaryFile() as recipe, SpooledTemporaryFile() as results:
            res = httpx2.get(local_job["recipe_url"])
            recipe.write(res.content)
            recipe.seek(0)

            unpacked = msgpack.Unpacker(recipe)

            if run:
                unpacked = (
                    cline for cline in unpacked if cline["path"].startswith(run)
                )

            settings = httpx2.get(local_job["settings_url"]).json()

            async def execute(on_running=None):
                if work_dir is not None:
                    os.chdir(work_dir)
                elif source.type == "DIR":
                    os.chdir(source._arg)

                async for cline, result in process_commands(
                    unpacked,
                    settings,
                    timeout,
                    on_running=on_running,
                ):
                    msgpack.pack(cline | {"output": result}, results)

            fields = {"x-amz-meta-status": "FINISHED"}
            timed_out = False

            def upload_and_poll():
                nonlocal execution_id, report

                results.seek(0)
                results_upload = local_job["results_upload"]
                res = httpx2.post(
                    results_upload["url"],
                    data=results_upload["fields"] | fields,
                    files={"file": results},
                )
                res.raise_for_status()

                # The execution (and its report) are created by the backend after
                # results are uploaded, so poll instead of querying once.
                for _ in range(60):
                    res = client.get(
                        "/executions",
                        params={"job_id": local_job["id"], "quantity": 1},
                    )

                    if items := res.json()["items"]:
                        execution_id = items[0]["id"]

                        if not needs_report:
                            break

                        execution = client.get(f"/executions/{execution_id}").json()
                        if report := execution.get("report"):
                            break

                    time.sleep(2)

            if use_progress:
                p = progress.Progress(
                    progress.SpinnerColumn("dots2"),
                    progress.TextColumn(
                        "[progress.description]Status: {task.description}",
                    ),
                    progress.TimeElapsedColumn(),
                )
                task = p.add_task("Starting execution")

                def make_grid(report_ids=None):
                    grid = Table.grid("")
                    grid.add_row(
                        JobWrapper(local_job, compact=True, report_ids=report_ids)
                    )
                    grid.add_row(p)
                    return grid

                def on_running(path: str) -> None:
                    p.update(task, description="Running [b]" + path)

                with Live(make_grid(), console=stdout, refresh_per_second=10) as live:
                    try:
                        asyncio.run(execute(on_running))
                        p.update(task, description="Completed")
                    except TimedOut:
                        timed_out = True
                        fields["x-amz-meta-status"] = "CANCELED"
                        p.update(task, description="Timeout")

                    upload_and_poll()
                    report_ids = [execution_id] if execution_id is not None else None
                    live.update(make_grid(report_ids))
            else:
                try:
                    asyncio.run(execute())
                except TimedOut:
                    timed_out = True
                    fields["x-amz-meta-status"] = "CANCELED"

                upload_and_poll()

                if not is_json_output():
                    report_ids = [execution_id] if execution_id is not None else None
                    stdout.print(
                        JobWrapper(local_job, compact=True, report_ids=report_ids)
                    )

            if timed_out:
                stdout.print("Execution timed out")

            if show_output:
                results.seek(0)
                format_raw_results(results)
    finally:
        if work_dir is not None or source.type == "DIR":
            os.chdir(original_cwd)
        if clone_tmpdir is not None:
            clone_tmpdir.cleanup()

    if needs_report:
        if report:
            if show_report:
                if detail := report.get("detail"):
                    stdout.print(ReportWrapper(detail))
                else:
                    stderr.print("No report detail available for this execution.")
            elif sync:
                fails = report.get("total_fails")
                stdout.print(
                    highlight_result(
                        "Result: " + (f"Fail({fails})" if fails else "Pass"),
                    ),
                )
        else:
            stderr.print("No report available for this execution.")

    if show_issues:
        if execution_id is not None:
            list_issues(page=1, quantity=10, execution_id=execution_id)
        else:
            stderr.print("No execution available to list issues.")

    if do_verify:
        if execution_id is None:
            raise SatoriError("No execution available to verify findings.")
        _verify_execution(execution_id)
