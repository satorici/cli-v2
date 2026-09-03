import rich_click as click

from ..api import client
from ..utils import options as opts
from ..utils.console import stdout
from ..utils.wrappers import IssueListWrapper, IssueWrapper, PagedWrapper


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


@click.command("issues")
@click.argument("execution-id", type=int)
@opts.json_opt
@opts.pagination_opts
def issues(execution_id: int, page: int, quantity: int, **kwargs):
    list_issues(execution_id, page, quantity)


@click.command("issue")
@click.argument("finding-id", type=int)
@opts.json_opt
def issue(finding_id: int, **kwargs):
    res = client.get(f"/findings/{finding_id}")
    stdout.print(IssueWrapper(res.json()))
