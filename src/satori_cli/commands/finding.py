from typing import Optional

import rich_click as click

from ..api import client
from ..utils import options as opts
from ..utils.console import stdout
from ..utils.wrappers import FindingsListWrapper, PagedWrapper

FINDING_STATUSES = [
    "OPEN",
    "INVESTIGATING",
    "CONFIRMED",
    "FIXED",
    "FALSE_POSITIVE",
    "ACCEPTED_RISK",
]


@click.command("findings")
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option("--execution-id", type=int)
@click.option(
    "--status",
    type=click.Choice(FINDING_STATUSES, case_sensitive=False),
)
@click.option(
    "--source",
    type=click.Choice(["ASSERT", "TOOL"], case_sensitive=False),
)
@click.option("--severity", type=click.IntRange(0, 5))
@click.option(
    "--order",
    type=click.Choice(["ASC", "DESC"], case_sensitive=False),
)
@opts.json_opt
def findings(
    page: int,
    quantity: int,
    execution_id: Optional[int],
    status: Optional[str],
    source: Optional[str],
    severity: Optional[int],
    order: Optional[str],
    **kwargs,
):
    params = {
        k: v
        for k, v in {
            "page": page,
            "quantity": quantity,
            "execution_id": execution_id,
            "status": status.upper() if status else None,
            "source": source.upper() if source else None,
            "severity": severity,
            "order": order.upper() if order else None,
        }.items()
        if v is not None
    }
    res = client.get("/findings", params=params)
    stdout.print(PagedWrapper(res.json(), page, quantity, FindingsListWrapper))
