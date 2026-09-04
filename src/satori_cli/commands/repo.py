from typing import Optional

import rich_click as click

from ..api import client
from ..utils import options as opts
from ..utils.console import stdout
from ..utils.wrappers import PagedWrapper, RepoListWrapper


@click.command("repos")
@click.option(
    "--order",
    type=click.Choice(["ASC", "DESC"], case_sensitive=False),
)
@opts.json_opt
@opts.pagination_opts
def repos(page: int, quantity: int, order: Optional[str], **kwargs):
    params = {
        k: v
        for k, v in {
            "page": page,
            "quantity": quantity,
            "order": order.upper() if order else None,
        }.items()
        if v is not None
    }
    res = client.get("/repos", params=params)
    stdout.print(PagedWrapper(res.json(), page, quantity, RepoListWrapper))
