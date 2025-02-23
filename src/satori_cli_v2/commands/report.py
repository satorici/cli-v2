from typing import Optional

import rich_click as click

from ..api import client
from ..utils import options as opts
from ..utils.console import stdout
from ..utils.wrappers import ExecutionListWrapper, PagedWrapper


@click.command()
@click.argument("job-id", type=int, required=False)
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@opts.json_opt
def reports(job_id: Optional[int], page: int, quantity: int, **kwargs):
    params = {k: v for k, v in locals().items() if v is not None and k != "kwargs"}

    res = client.get("/executions", params=params)
    stdout.print(PagedWrapper(res.json(), page, quantity, ExecutionListWrapper))
