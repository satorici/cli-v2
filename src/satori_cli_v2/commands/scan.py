from typing import Optional

import rich_click as click

from ..api import client
from ..utils.arguments import source_arg
from ..utils.console import stdout, wait_job_until_finished
from ..utils import options as opts
from .job import list_jobs


@click.command("scans")
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option("--public", "visibility", flag_value="PUBLIC")
def list_scans(page: int, quantity: int, visibility: Optional[str]):
    return list_jobs(page, quantity, "SCAN", visibility)


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
    container_settings = {k: v for k, v in {"cpu": cpu, "memory": memory}.items() if v}

    body = {
        "playbook_data": source,
        "type": "SCAN",
        "parameters": input,
        "regions": list(region_filter),
        "repository_data": {"repository": repository},
        "criteria": {"quantity": quantity},
        "environment_variables": env,
        "container_settings": container_settings,
    }

    res = client.post("/jobs", json=body)

    res.raise_for_status()

    stdout.print_json(res.text)

    if sync:
        scan_id = res.json()["id"]
        wait_job_until_finished(scan_id)
