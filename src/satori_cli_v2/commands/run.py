import sys
from typing import Optional

import rich
import rich_click as click

from ..api import client
from ..utils.arguments import source_arg
from ..utils.console import show_execution_output, wait_job_until_finished
from ..utils.options import input_opt, region_filter_opt, sync_opt


@click.command()
@source_arg
@click.option("--count", default=1, show_default=True)
@sync_opt
@region_filter_opt
@input_opt
@click.option("--show-output", "-o", is_flag=True)
def run(
    source: dict,
    region_filter: tuple[str],
    count: int,
    sync: bool,
    show_output: bool,
    input: Optional[dict[str, list[str]]],
):
    if show_output and count > 1:
        print("WARNING: Only first execution output will be shown")

    body = {
        "type": "RUN",
        "parameters": input,
        "regions": list(region_filter),
        "data": {"count": count},
    }

    res = client.post("/jobs", json=body | source)
    rich.print_json(res.text)

    if not res.is_success:
        sys.exit(1)

    run_id = res.json()["id"]

    if sync or show_output:
        wait_job_until_finished(run_id)

    if show_output:
        res = client.get("/executions", params={"job_id": run_id})
        execution_id = res.json()["items"][0]["id"]
        show_execution_output(execution_id)
