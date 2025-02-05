from typing import Optional

import rich_click as click

from ..api import client
from ..utils.arguments import source_arg
from ..utils.console import stdout, wait_job_until_finished
from ..utils import options as opts


@click.command()
@click.argument("repository")
@source_arg
@click.option("-q", "--quantity", type=int)
@opts.region_filter_opt
@opts.sync_opt
@opts.input_opt
@opts.env_opt
def scan(
    repository: str,
    source: dict,
    sync: bool,
    region_filter: tuple[str],
    quantity: Optional[int],
    input: Optional[dict[str, list[str]]],
    env: Optional[dict[str, str]],
    cpu: Optional[int],
    memory: Optional[int],
):
    body = {
        "playbook_data": source,
        "type": "SCAN",
        "parameters": input,
        "regions": list(region_filter),
        "repository_data": {"repository": repository},
        "criteria": {"quantity": quantity},
        "environment_variables": env,
        "container_settings": {"cpu": cpu, "memory": memory},
    }

    res = client.post("/jobs", json=body)

    res.raise_for_status()

    stdout.print_json(res.text)

    if sync:
        scan_id = res.json()["id"]
        wait_job_until_finished(scan_id)
