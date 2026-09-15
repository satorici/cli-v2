import rich_click as click

from ..api import client
from ..utils import options as opts
from ..utils.console import stdout
from ..utils.wrappers import ExternalIssueListWrapper, PagedWrapper


@click.command("advisories")
@click.option("--execution-id", type=int)
@click.option(
    "--kind",
    type=click.Choice(["SECURITY_ADVISORY", "ISSUE"], case_sensitive=False),
)
@click.option(
    "--provider",
    type=click.Choice(["GITHUB"], case_sensitive=False),
)
@click.option(
    "--order",
    type=click.Choice(["ASC", "DESC"], case_sensitive=False),
)
@opts.json_opt
@opts.pagination_opts
def advisories(
    page: int,
    quantity: int,
    execution_id: int | None,
    kind: str | None,
    provider: str | None,
    order: str | None,
    **kwargs,
):
    """List external issues (e.g. GitHub security advisories) you created."""
    params = {
        k: v
        for k, v in {
            "page": page,
            "quantity": quantity,
            "execution_id": execution_id,
            "kind": kind.upper() if kind else None,
            "provider": provider.upper() if provider else None,
            "order": order.upper() if order else None,
        }.items()
        if v is not None
    }
    res = client.get("/external_issues", params=params)
    stdout.print(PagedWrapper(res.json(), page, quantity, ExternalIssueListWrapper))
