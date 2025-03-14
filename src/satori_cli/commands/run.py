import sys
import time
from collections.abc import Callable
from typing import Optional

import rich_click as click
from rich.live import Live

from ..api import client
from ..utils import options as opts
from ..utils.arguments import source_arg
from ..utils.console import (
    download_execution_files,
    show_execution_output,
    stderr,
    stdout,
)
from ..utils.wrappers import (
    JobExecutionsWrapper,
    JobWrapper,
    PagedWrapper,
    ReportWrapper,
)


@click.command()
@source_arg
@click.option("--count", default=1, show_default=True)
@opts.sync_opt
@opts.region_filter_opt
@opts.input_opt
@opts.env_opt
@click.option("--output", "-o", "show_output", is_flag=True)
@click.option("--report", "show_report", is_flag=True)
@click.option("--save-files", is_flag=True)
@click.option("--delete-report", is_flag=True)
@click.option("--delete-output", is_flag=True)
@click.option("--files", "-f", "get_files", is_flag=True)
@opts.cpu_opt
@opts.memory_opt
@opts.json_opt
def run(
    source: Callable[[], dict],
    region_filter: tuple[str],
    count: int,
    sync: bool,
    show_output: bool,
    show_report: bool,
    delete_report: bool,
    delete_output: bool,
    save_files: bool,
    get_files: bool,
    input: Optional[dict[str, list[str]]],
    env: Optional[dict[str, str]],
    cpu: Optional[int],
    memory: Optional[int],
    **kwargs,
):
    if show_output and count > 1:
        stderr.print("WARNING: Only first execution output will be shown")
    if get_files and count > 1:
        stderr.print("WARNING: Only first execution files will be downloaded")

    container_settings = {k: v for k, v in {"cpu": cpu, "memory": memory}.items() if v}

    playbook_data = source()
    upload_data = playbook_data.pop("upload_data", None)

    body = {
        "playbook_data": playbook_data,
        "type": "RUN",
        "parameters": input,
        "regions": list(region_filter),
        "count": count,
        "save_files": get_files or save_files,
        "save_report": not delete_report,
        "save_output": not delete_output,
        "environment_variables": env,
        "container_settings": container_settings,
        "with_files": bool(upload_data),
    }

    run = client.post("/jobs", json=body).json()

    if files_upload := run["files_upload"]:
        upload_data(files_upload)

    run_id = run["id"]

    if sync or show_output or get_files or show_report:
        live_console = stderr if show_output or show_report else stdout

        with Live(JobWrapper(run), console=live_console) as live:
            while True:
                time.sleep(1)
                run = client.get(f"/jobs/{run_id}").json()
                live.update(JobWrapper(run))

                if run["status"] in ("FINISHED", "CANCELED"):
                    break
    else:
        stdout.print(JobWrapper(run))
        sys.exit(0)

    res = client.get("/executions", params={"job_id": run_id})
    execution_id = res.json()["items"][0]["id"]

    if show_output:
        show_execution_output(execution_id)

    if get_files:
        download_execution_files(execution_id)

    if show_report:
        if count == 1:
            res = client.get(f"/executions/{execution_id}")
            report = res.json()["data"]["report"]["detail"]
            stdout.print(ReportWrapper(report))
        else:
            res = client.get("/executions", params={"job_id": run_id})
            executions = res.json()
            stdout.print(
                PagedWrapper(
                    executions, 1, len(executions["items"]), JobExecutionsWrapper
                )
            )
