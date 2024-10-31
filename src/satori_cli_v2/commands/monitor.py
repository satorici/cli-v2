from typing import Optional

import rich
import rich_click as click

from ..api import client
from ..utils.arguments import source_arg
from ..utils.options import input_opt, region_filter_opt


@click.command()
@source_arg
@click.argument("expression")
@click.option("--description")
@region_filter_opt
@input_opt
def monitor(
    source: dict,
    expression: str,
    description: Optional[str],
    region_filter: tuple[str],
    input: Optional[dict[str, list[str]]],
):
    body = {
        "type": "MONITOR",
        "parameters": input,
        "regions": list(region_filter),
        "data": {"expression": expression, "description": description},
    }

    res = client.post("/monitors", json=body | source)
    rich.print_json(res.text)
