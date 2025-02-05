from typing import Optional

import rich_click as click

from ..api import client
from ..utils.console import stdout


@click.command()
@click.argument("job-id", type=int, required=False)
@click.option("--page", default=1)
@click.option("--quantity", default=10)
def reports(job_id: Optional[int], page: int, quantity: int):
    params = {k: v for k, v in locals().items() if v is not None}

    res = client.get("/executions", params=params)
    stdout.print_json(res.text)
