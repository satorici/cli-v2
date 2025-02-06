from collections.abc import Callable
from typing import Optional

import rich_click as click

from ..api import client
from ..utils.arguments import source_arg
from ..utils.console import stdout
from ..utils import options as opts


@click.command()
@source_arg
@click.argument("expression")
@click.option("--description")
@opts.region_filter_opt
@opts.input_opt
@opts.env_opt
@opts.cpu_opt
@opts.memory_opt
def monitor(
    source: Callable[[], dict],
    expression: str,
    description: Optional[str],
    region_filter: tuple[str],
    input: Optional[dict[str, list[str]]],
    env: Optional[dict[str, str]],
    cpu: Optional[int],
    memory: Optional[int],
):
    container_settings = {k: v for k, v in {"cpu": cpu, "memory": memory}.items() if v}

    playbook_data = source()
    upload_data = playbook_data.pop("upload_data", None)

    body = {
        "playbook_data": source,
        "type": "MONITOR",
        "parameters": input,
        "regions": list(region_filter),
        "expression": expression,
        "description": description,
        "environment_variables": env,
        "container_settings": container_settings,
        "with_files": bool(upload_data),
    }

    res = client.post("/jobs", json=body)
    res.raise_for_status()

    monitor = res.json()
    stdout.print_json(data=monitor)

    if files_upload := monitor["files_upload"]:
        upload_data(files_upload)
