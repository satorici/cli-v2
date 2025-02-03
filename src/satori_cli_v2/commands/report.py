from typing import Optional

import rich_click as click

from ..api import client
from ..utils.console import stdout


@click.command()
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option("--job-id", type=int)
def reports(page: int, quantity: int, job_id: Optional[int]):
    params = {k: v for k, v in locals().items() if v is not None}

    res = client.get("/executions/reports", params=params)
    stdout.print_json(res.text)
