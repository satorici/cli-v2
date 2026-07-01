from typing import Optional

import rich_click as click

from ..api import client
from ..exceptions import SatoriError
from ..utils import options as opts
from ..utils.arguments import Source, source_arg
from ..utils.console import stdout, wait_job_until_finished
from ..utils.misc import list_jobs, remove_none_values
from ..utils.wrappers import JobWrapper


@click.command("scans")
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option("--public", "visibility", flag_value="PUBLIC")
@opts.json_opt
def list_scans(page: int, quantity: int, visibility: Optional[str], **kwargs):
    return list_jobs(page, quantity, "SCAN", visibility)


@click.command()
@click.argument("repository")
@source_arg
@click.option("-q", "--quantity", type=int)
@opts.region_filter_opt
@opts.sync_opt
@opts.input_opt
@opts.env_opt
@opts.memory_opt
@opts.cpu_opt
@opts.image_opt
@opts.json_opt
def scan(
    repository: str,
    source: Source,
    sync: bool,
    region_filter: tuple[str],
    quantity: Optional[int],
    input: Optional[dict[str, list[str]]],
    env: Optional[dict[str, str]],
    cpu: Optional[int],
    memory: Optional[int],
    image: Optional[str],
    **kwargs,
):
    if source.type == "DIR":
        raise SatoriError("Directory sources are not compatible with scan")

    container_settings = {}

    if local_playbook := source.playbook:
        input = local_playbook.get_inputs_from_env(input)
        container_settings = remove_none_values(local_playbook.container_settings)

    container_settings.update(
        remove_none_values(
            {"cpu": cpu, "memory": memory, "image": image, "environment_variables": env}
        )
    )

    body = {
        "playbook_source": source.playbook_data(),
        "parameters": input,
        "regions": list(region_filter),
        "repository_data": {"repository": repository},
        "criteria": {"quantity": quantity},
        "environment_variables": env,
        "container_settings": remove_none_values(container_settings),
    }

    res = client.post("/jobs/scans", json=body)
    scan_job = res.json()

    stdout.print(JobWrapper(scan_job))

    if sync:
        wait_job_until_finished(scan_job["id"])
