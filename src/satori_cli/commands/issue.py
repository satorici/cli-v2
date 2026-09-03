import rich_click as click

from ..api import client
from ..utils import options as opts
from ..utils.console import stdout
from ..utils.wrappers import IssueListWrapper, PagedWrapper


def list_issues(execution_id: int, page: int, quantity: int):
    res = client.get(
        "/findings",
        params={"execution_id": execution_id},
    )
    data = res.json()
    data["items"] = sorted(
        data["items"],
        key=lambda f: f.get("severity") if f.get("severity") is not None else -1,
        reverse=True,
    )
    stdout.print(PagedWrapper(data, page, quantity, IssueListWrapper))


@click.command("issue")
@click.argument("execution-id", type=int)
@opts.json_opt
def issue(execution_id: int, page: int, quantity: int, **kwargs):
    list_issues(execution_id, page, quantity)
