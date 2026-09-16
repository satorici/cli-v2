import rich_click as click

from ..api import client
from ..utils import options as opts
from ..utils.console import stdout
from ..utils.groups import IdGroup
from ..utils.wrappers import ExternalIssueListWrapper, ExternalIssueWrapper, PagedWrapper


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


@click.group(cls=IdGroup, invoke_without_command=True)
@opts.json_opt
@click.pass_context
def advisory(ctx, **kwargs):
    """Get or update an external issue (e.g. GitHub security advisory)."""
    if ctx.invoked_subcommand is None:
        if ctx.obj is None:
            raise click.UsageError("Missing argument 'ADVISORY-ID'.")
        res = client.get(f"/external_issues/{ctx.obj}")
        stdout.print(ExternalIssueWrapper(res.json()))


@advisory.command(name="visibility")
@click.argument(
    "value", type=click.Choice(["PUBLIC", "PRIVATE", "UNLISTED"], case_sensitive=False)
)
@click.pass_obj
def advisory_visibility(advisory_id: int, value: str):
    if advisory_id is None:
        raise click.UsageError("Missing argument 'ADVISORY-ID'.")
    client.patch(
        f"/external_issues/{advisory_id}",
        json={"visibility": value.upper()},
    )
    stdout.print(f"Advisory visibility set to {value.upper()}")
