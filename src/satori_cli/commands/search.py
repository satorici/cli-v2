from datetime import datetime

import rich_click as click

from ..api import client
from ..utils.console import stdout
from ..utils.misc import remove_none_values
from ..utils.wrappers import ExecutionListWrapper, PagedWrapper


def isodatetime(arg: str):
    return datetime.fromisoformat(arg)


@click.command()
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option("--job-type", type=click.Choice(["RUN", "SCAN", "MONITOR", "GITHUB"]))
@click.option("--job-id", type=int)
@click.option("--global", is_flag=True)
@click.option(
    "--status", type=click.Choice(["FINISHED", "CANCELED", "RUNNING", "QUEUED"])
)
@click.option("--visibility", type=click.Choice(["PUBLIC", "PRIVATE", "UNLISTED"]))
@click.option("--from", type=isodatetime)
@click.option("--to", type=isodatetime)
@click.option("--report-status", type=click.Choice(["PASS", "FAIL"]))
@click.option("--severity", type=click.IntRange(min=0, max=5))
def search(**kwargs):
    params = remove_none_values(kwargs)

    res = client.get("/executions", params=params)

    stdout.print(
        PagedWrapper(
            res.json(), params["page"], params["quantity"], ExecutionListWrapper
        )
    )
