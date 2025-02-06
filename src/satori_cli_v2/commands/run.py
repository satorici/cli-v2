from collections.abc import Callable
import sys
from typing import Optional

import rich_click as click

from ..api import client
from ..utils.arguments import source_arg
from ..utils.console import (
    download_execution_files,
    show_execution_output,
    show_execution_report,
    stderr,
    stdout,
    wait_job_until_finished,
)
from ..utils import options as opts


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
@click.option("--no-save-report", is_flag=True)
@click.option("--files", "-f", "get_files", is_flag=True)
@opts.cpu_opt
@opts.memory_opt
def run(
    source: Callable[[], dict],
    region_filter: tuple[str],
    count: int,
    sync: bool,
    show_output: bool,
    show_report: bool,
    no_save_report: bool,
    save_files: bool,
    get_files: bool,
    input: Optional[dict[str, list[str]]],
    env: Optional[dict[str, str]],
    cpu: Optional[int],
    memory: Optional[int],
):
    if show_output and count > 1:
        stderr.print("WARNING: Only first execution output will be shown")
    if get_files and count > 1:
        stderr.print("WARNING: Only first execution files will be downloaded")
    if show_report and count > 1:
        stderr.print("WARNING: Only first execution report will be shown")

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
        "save_report": not no_save_report,
        "environment_variables": env,
        "container_settings": container_settings,
        "with_files": bool(upload_data),
    }

    res = client.post("/jobs", json=body)

    run = res.json()
    stdout.print_json(data=run)

    if not res.is_success:
        sys.exit(1)

    if files_upload := run["files_upload"]:
        upload_data(files_upload)

    run_id = run["id"]

    if sync or show_output or get_files or show_report:
        wait_job_until_finished(run_id)
    else:
        sys.exit(0)

    res = client.get("/executions", params={"job_id": run_id})
    execution_id = res.json()["items"][0]["id"]

    if show_output:
        show_execution_output(execution_id)

    if get_files:
        download_execution_files(execution_id)

    if show_report:
        show_execution_report(execution_id)
