import sys
import time
from typing import Optional

import httpx
import rich_click as click
from rich import progress
from rich.live import Live
from rich.table import Table

from satori_cli.exceptions import SatoriError

from ..api import client
from ..models import Playbook
from ..utils import options as opts
from ..utils.arguments import Source, source_arg
from ..utils.console import export_job_files, show_execution_output, stderr, stdout
from ..utils.misc import remove_none_values
from ..utils.wrappers import (
    JobExecutionsWrapper,
    JobWrapper,
    PagedWrapper,
    ReportWrapper,
)


@click.command()
@source_arg
@opts.playbook_opt
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
@opts.image_opt
@opts.json_opt
def run(
    source: Source,
    playbook: Optional[Playbook],
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
    image: Optional[str],
    **kwargs,
):
    if show_output and count > 1:
        stderr.print("WARNING: Only first execution output will be shown")

    container_settings = {}

    if local_playbook := playbook or source.playbook:
        input = local_playbook.get_inputs_from_env(input)
        container_settings = remove_none_values(local_playbook.container_settings)

    container_settings.update(
        remove_none_values(
            {"cpu": cpu, "memory": memory, "image": image, "environment_variables": env}
        )
    )

    playbook_data = playbook.playbook_data() if playbook else source.playbook_data()

    body = {
        "playbook_data": playbook_data,
        "type": "RUN",
        "parameters": input,
        "regions": list(region_filter),
        "count": count,
        "save_files": get_files or save_files,
        "save_report": not delete_report,
        "save_output": not delete_output,
        "container_settings": remove_none_values(container_settings),
        "with_files": source.type == "DIR",
    }

    run = client.post("/jobs", json=body).json()

    if files_upload := run["files_upload"]:
        source.upload_files(files_upload)

    run_id = run["id"]

    if sync or show_output or get_files or show_report:
        live_console = stderr if show_output or show_report else stdout

        p = progress.Progress(
            progress.SpinnerColumn("dots2"),
            progress.TimeElapsedColumn(),
            console=stderr,
        )
        p.add_task("")

        grid = Table.grid("")
        grid.add_row(JobWrapper(run))
        grid.add_row(p)

        with Live(grid, console=live_console, refresh_per_second=10) as live:
            while True:
                time.sleep(1)

                tries = 0

                while tries < 4:
                    try:
                        run = client.get(f"jobs/{run_id}").json()
                        break
                    except httpx.TimeoutException:
                        tries += 1
                else:
                    raise SatoriError("Fetch status failed after 3 retries")

                grid = Table.grid("")
                grid.add_row(JobWrapper(run))
                grid.add_row(p)

                live.update(grid)

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
        export_job_files(run_id)

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
