from typing import Optional

import rich_click as click

from ..api import client
from ..models import Playbook
from ..utils import options as opts
from ..utils.arguments import Source, source_arg
from ..utils.console import stdout
from ..utils.misc import remove_none_values
from .job import list_jobs


@click.command("monitors")
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option("--public", "visibility", flag_value="PUBLIC")
def list_monitors(page: int, quantity: int, visibility: Optional[str]):
    return list_jobs(page, quantity, "MONITOR", visibility)


@click.command()
@source_arg
@opts.playbook_opt
@click.argument("expression")
@click.option("--description")
@opts.region_filter_opt
@opts.input_opt
@opts.env_opt
@opts.cpu_opt
@opts.memory_opt
@opts.image_opt
def monitor(
    source: Source,
    playbook: Optional[Playbook],
    expression: str,
    description: Optional[str],
    region_filter: tuple[str],
    input: Optional[dict[str, list[str]]],
    env: Optional[dict[str, str]],
    cpu: Optional[int],
    memory: Optional[int],
    image: Optional[str],
):
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
        "playbook_source": playbook_data,
        "parameters": input,
        "regions": list(region_filter),
        "expression": expression,
        "description": description,
        "environment_variables": env,
        "container_settings": remove_none_values(container_settings),
        "with_files": bool(source.type == "DIR"),
    }

    res = client.post("/jobs/monitors", json=body)

    monitor = res.json()
    stdout.print_json(data=monitor)

    if files_upload := monitor["files_upload"]:
        source.upload_files(files_upload)
