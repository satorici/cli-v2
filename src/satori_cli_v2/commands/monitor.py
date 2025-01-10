from typing import Optional

import rich_click as click

from ..api import client
from ..utils.arguments import source_arg
from ..utils.console import stdout
from ..utils.options import env_opt, input_opt, region_filter_opt


@click.command()
@source_arg
@click.argument("expression")
@click.option("--description")
@region_filter_opt
@input_opt
@env_opt
def monitor(
    source: dict,
    expression: str,
    description: Optional[str],
    region_filter: tuple[str],
    input: Optional[dict[str, list[str]]],
    env: Optional[dict[str, str]],
):
    body = {
        "playbook_data": source,
        "type": "MONITOR",
        "parameters": input,
        "regions": list(region_filter),
        "expression": expression,
        "description": description,
        "environment_variables": env,
    }

    res = client.post("/jobs", json=body | source)
    res.raise_for_status()
    stdout.print_json(res.text)
