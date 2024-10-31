import sys
from typing import Optional

import rich
import rich_click as click

from ..api import client
from ..utils.arguments import source_arg
from ..utils.console import wait_job_until_finished
from ..utils.options import input_opt, region_filter_opt, sync_opt


@click.command()
@source_arg
@click.option("--count", default=1, show_default=True)
@sync_opt
@region_filter_opt
@input_opt
def run(
    source: dict,
    region_filter: tuple[str],
    count: int,
    sync: bool,
    input: Optional[dict[str, list[str]]],
):
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

    if sync:
        run_id = res.json()["id"]
        wait_job_until_finished(run_id)
