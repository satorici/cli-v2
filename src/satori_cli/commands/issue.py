import rich_click as click

from ..api import client
from ..utils import options as opts
from ..utils.console import stdout
from ..utils.wrappers import IssueListWrapper, PagedWrapper


def list_issues(execution_id: int, page: int, quantity: int):
    res = client.get(
        "/findings",
        params={"execution_id": execution_id, "page": page, "quantity": quantity},
    )
    stdout.print(PagedWrapper(res.json(), page, quantity, IssueListWrapper))


@click.command("issue")
@click.argument("execution-id", type=int)
@opts.json_opt
@opts.pagination_opts
def issue(execution_id: int, page: int, quantity: int, **kwargs):
    list_issues(execution_id, page, quantity)
