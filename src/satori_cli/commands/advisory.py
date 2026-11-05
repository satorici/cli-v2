import rich_click as click

from ..api import client
from ..utils import options as opts
from ..utils.console import stdout
from ..utils.groups import IdGroup
from ..utils.wrappers import ExternalIssueListWrapper, ExternalIssueWrapper, PagedWrapper
from ..utils.public_id import ADVISORY_ID, EXECUTION_ID


@click.command("advisories")
@click.option("--execution-id", type=EXECUTION_ID)
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
    execution_id: str | None,
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


@click.group(cls=IdGroup, id_type=ADVISORY_ID, invoke_without_command=True)
@opts.json_opt
@click.pass_context
def advisory(ctx, **kwargs):
    """Get or update an external issue (e.g. GitHub security advisory)."""
    if ctx.invoked_subcommand is None:
        if ctx.obj is None:
            raise click.UsageError("Missing argument 'ADVISORY-ID'.")
        res = client.get(f"/external_issues/{ctx.obj}")
        data = res.json()
        timeline = client.get(f"/findings/{data['finding_id']}/timeline").json()
        stdout.print(ExternalIssueWrapper(data, history=timeline))


@advisory.command(name="edit")
@click.option("--title", help="Replace the advisory title.")
@click.option(
    "--body",
    "--description",
    "description",
    help="Replace the advisory description (Markdown).",
)
@click.option(
    "--body-file",
    type=click.File("r"),
    help="Read the new description from a file (wins over --body).",
)
@click.option(
    "--severity",
    type=click.Choice(["low", "medium", "high", "critical"], case_sensitive=False),
    help="Set the independently assessed advisory severity.",
)
@click.option("--cvss-vector", help="Set the CVSS 4.0 Base vector.")
@click.pass_obj
def advisory_edit(
    advisory_id: str,
    title: str | None,
    description: str | None,
    body_file,
    severity: str | None,
    cvss_vector: str | None,
):
    """Edit a draft advisory's title or description to humanize it before publishing.

    Only a draft can be edited; once the advisory is published to GitHub its text is fixed
    there. Pass --title and/or the body (--body or --body-file).
    """
    if advisory_id is None:
        raise click.UsageError("Missing argument 'ADVISORY-ID'.")
    if body_file is not None:
        description = body_file.read()
    if all(value is None for value in (title, description, severity, cvss_vector)):
        raise click.UsageError(
            "Pass --title, --body, --body-file, --severity or --cvss-vector."
        )
    payload: dict[str, str] = {}
    if title is not None:
        payload["title"] = title
    if description is not None:
        payload["description"] = description
    if severity is not None:
        payload["severity"] = severity.upper()
    if cvss_vector is not None:
        payload["cvss_vector"] = cvss_vector
    client.patch(f"/external_issues/{advisory_id}", json=payload)
    stdout.print("Advisory updated")


@advisory.command(name="visibility")
@click.argument(
    "value", type=click.Choice(["PUBLIC", "PRIVATE", "UNLISTED"], case_sensitive=False)
)
@click.pass_obj
def advisory_visibility(advisory_id: str, value: str):
    if advisory_id is None:
        raise click.UsageError("Missing argument 'ADVISORY-ID'.")
    client.patch(
        f"/external_issues/{advisory_id}",
        json={"visibility": value.upper()},
    )
    stdout.print(f"Advisory visibility set to {value.upper()}")
