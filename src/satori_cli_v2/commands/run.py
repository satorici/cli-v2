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
from ..utils.options import input_opt, region_filter_opt, sync_opt, env_opt


@click.command()
@source_arg
@click.option("--count", default=1, show_default=True)
@sync_opt
@region_filter_opt
@input_opt
@env_opt
@click.option("--show-output", "-o", is_flag=True)
@click.option("--show-report", is_flag=True)
@click.option("--save-files", is_flag=True)
@click.option("--no-save-report", is_flag=True)
@click.option("--get-files", "-f", is_flag=True)
def run(
    source: dict,
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
):
    if show_output and count > 1:
        stderr.print("WARNING: Only first execution output will be shown")
    if get_files and count > 1:
        stderr.print("WARNING: Only first execution files will be downloaded")
    if show_report and count > 1:
        stderr.print("WARNING: Only first execution report will be shown")

    body = {
        "playbook_data": source,
        "type": "RUN",
        "parameters": input,
        "regions": list(region_filter),
        "count": count,
        "save_files": get_files or save_files,
        "save_report": not no_save_report,
        "environment_variables": env,
    }

    res = client.post("/jobs", json=body)
    stdout.print_json(res.text)

    if not res.is_success:
        sys.exit(1)

    run_id = res.json()["id"]

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
