import rich_click as click

from ..api import client
from ..utils import options as opts
from ..utils.console import stdout
from ..utils.format import is_json_output
from ..utils.groups import IdGroup
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


@click.group(cls=IdGroup, invoke_without_command=True)
@opts.json_opt
@click.pass_context
def issue(ctx, **kwargs):
    if ctx.invoked_subcommand is None:
        if ctx.obj is None:
            raise click.UsageError("Missing argument 'FINDING-ID'.")
        res = client.get(f"/findings/{ctx.obj}")
        stdout.print(IssueWrapper(res.json()))


@issue.command(name="advisory")
@opts.json_opt
@click.pass_obj
def issue_advisory(finding_id: int, **kwargs):
    if finding_id is None:
        raise click.UsageError("Missing argument 'FINDING-ID'.")
    res = client.post("/external_issues", json={"finding_id": finding_id})
    data = res.json()
    if is_json_output():
        stdout.print_json(data)
    else:
        stdout.print(data.get("external_url") or data["external_id"])
