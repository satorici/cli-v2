from typing import Optional

import rich
import rich_click as click

from ..api import client
from ..utils.arguments import source_arg
from ..utils.console import wait_job_until_finished
from ..utils.options import input_opt, region_filter_opt, sync_opt


@click.command()
@click.argument("repository")
@source_arg
@click.option("-q", "--quantity", type=int)
@region_filter_opt
@sync_opt
@input_opt
def scan(
    repository: str,
    source: dict,
    sync: bool,
    region_filter: tuple[str],
    quantity: Optional[int],
    input: Optional[dict[str, list[str]]],
):
    body = {
        "type": "SCAN",
        "parameters": input,
        "regions": list(region_filter),
        "repository": repository,
        "criteria": {"quantity": quantity},
    }

    res = client.post("/jobs", json=body | source)
    rich.print_json(res.text)

    if sync:
        scan_id = res.json()["id"]
        wait_job_until_finished(scan_id, "SCAN")
