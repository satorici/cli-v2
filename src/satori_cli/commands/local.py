import asyncio
import tempfile
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Optional

import rich_click as click
from rich import progress
from rich.live import Live
from rich.table import Table

from ..exceptions import SatoriError
from ..models import Playbook
from ..utils import options as opts
from ..utils.arguments import Source, source_arg
from ..utils.console import format_raw_results, stderr, stdout
from ..utils.format import is_json_output
from ..utils.git_clone import clone_repo, require_git
from ..utils.highlight import highlight_result
from ..utils.local_run import run_local_job
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

    use_progress = not is_json_output() and not show_output
    execution_id = None
    report = None
    needs_report = show_report or sync or show_issues or do_verify

    clone_tmpdir = None
    work_dir: Optional[str] = None
    if repository:
        git = require_git()
        clone_tmpdir = tempfile.TemporaryDirectory(prefix="satori-local-")
        work_dir = str(clone_repo(git, repository, Path(clone_tmpdir.name)))
    elif source.type == "DIR":
        work_dir = source._arg

    def run_job(on_running=None, on_job=None, results=None):
        return asyncio.run(
            run_local_job(
                playbook_data,
                parameters=input,
                visibility=visibility or "PRIVATE",
                tags=tags_obj,
                repository=repository,
                workdir=work_dir,
                run=tuple(run or ()),
                timeout=timeout,
                needs_report=needs_report,
                results=results,
                on_running=on_running,
                on_job=on_job,
            )
        )

    try:
        with SpooledTemporaryFile() as results:
            if use_progress:
                p = progress.Progress(
                    progress.SpinnerColumn("dots2"),
                    progress.TextColumn(
                        "[progress.description]Status: {task.description}",
                    ),
                    progress.TimeElapsedColumn(),
                )
                task = p.add_task("Starting execution")
                local_job: dict = {}

                def make_grid(report_ids=None):
                    grid = Table.grid("")
                    if local_job:
                        grid.add_row(
                            JobWrapper(local_job, compact=True, report_ids=report_ids)
                        )
                    grid.add_row(p)
                    return grid

                def on_running(path: str) -> None:
                    p.update(task, description="Running [b]" + path)

                def on_job(job: dict) -> None:
                    local_job.update(job)
                    live.update(make_grid())

                with Live(make_grid(), console=stdout, refresh_per_second=10) as live:
                    outcome = run_job(on_running, on_job, results)
                    p.update(
                        task, description="Timeout" if outcome.timed_out else "Completed"
                    )
                    execution_id = outcome.execution_id
                    report_ids = [execution_id] if execution_id is not None else None
                    live.update(make_grid(report_ids))
            else:
                outcome = run_job(results=results)
                execution_id = outcome.execution_id

                if not is_json_output():
                    report_ids = [execution_id] if execution_id is not None else None
                    stdout.print(
                        JobWrapper(outcome.job, compact=True, report_ids=report_ids)
                    )

            report = outcome.report

            if outcome.timed_out:
                stdout.print("Execution timed out")

            if show_output:
                results.seek(0)
                format_raw_results(results)
    finally:
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
