from typing import Optional

import rich_click as click
from click_option_group import MutuallyExclusiveOptionGroup, optgroup

from ..api import client
from ..constants import advisory_url
from ..utils import options as opts
from ..utils.console import stderr, stdout
from ..utils.format import is_json_output
from ..utils.groups import IdGroup
from ..utils.wrappers import (
    ExternalIssueWrapper,
    IssueListWrapper,
    IssueWrapper,
    PagedWrapper,
)

ISSUE_STATUSES = [
    "OPEN",
    "INVESTIGATING",
    "TP",
    "FIXED",
    "FP",
    "ACCEPTED",
]

SEVERITY_ALIASES = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL", "BLOCKER")


def parse_severity_csv(
    ctx: click.Context, param: click.Parameter, value: Optional[str]
) -> Optional[list[int]]:
    if value is None:
        return None
    parts = [part.strip() for part in value.split(",")]
    if not parts or any(not part for part in parts):
        raise click.BadParameter(
            f"Expected comma-separated severities from {', '.join(SEVERITY_ALIASES)}."
        )
    result: list[int] = []
    seen: set[int] = set()
    for part in parts:
        upper = part.upper()
        if upper not in SEVERITY_ALIASES:
            raise click.BadParameter(
                f"Invalid severity {part!r}. "
                f"Choose from {', '.join(SEVERITY_ALIASES)}."
            )
        index = SEVERITY_ALIASES.index(upper)
        if index not in seen:
            seen.add(index)
            result.append(index)
    return result


def list_issues(
    page: int,
    quantity: int,
    execution_id: Optional[int] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    severity: Optional[list[int]] = None,
    order: Optional[str] = None,
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
    data = res.json()
    if order is None:
        data["items"] = sorted(
            data["items"],
            key=lambda f: f.get("severity") if f.get("severity") is not None else -1,
            reverse=True,
        )
    stdout.print(PagedWrapper(data, page, quantity, IssueListWrapper))


@click.command("issues")
@click.argument("execution_id_arg", metavar="EXECUTION-ID", type=int, required=False)
@click.option("--execution-id", "execution_id_opt", type=int)
@click.option(
    "--status",
    type=click.Choice(ISSUE_STATUSES, case_sensitive=False),
)
@click.option(
    "--source",
    type=click.Choice(["ASSERT", "TOOL"], case_sensitive=False),
)
@click.option(
    "--severity",
    callback=parse_severity_csv,
    metavar="|".join(SEVERITY_ALIASES),
    help="Comma-separated severities, e.g. high,low,medium",
)
@click.option(
    "--order",
    type=click.Choice(["ASC", "DESC"], case_sensitive=False),
)
@opts.json_opt
@opts.pagination_opts
def issues(
    page: int,
    quantity: int,
    execution_id_arg: Optional[int],
    execution_id_opt: Optional[int],
    status: Optional[str],
    source: Optional[str],
    severity: Optional[list[int]],
    order: Optional[str],
    **kwargs,
):
    if (
        execution_id_arg is not None
        and execution_id_opt is not None
        and execution_id_arg != execution_id_opt
    ):
        raise click.UsageError(
            "Conflicting EXECUTION-ID argument and --execution-id option."
        )
    list_issues(
        page,
        quantity,
        execution_id=execution_id_arg
        if execution_id_arg is not None
        else execution_id_opt,
        status=status,
        source=source,
        severity=severity,
        order=order,
    )


@click.group(cls=IdGroup, invoke_without_command=True)
@opts.json_opt
@click.pass_context
def issue(ctx, **kwargs):
    if ctx.invoked_subcommand is None:
        if ctx.obj is None:
            raise click.UsageError("Missing argument 'FINDING-ID'.")
        res = client.get(f"/findings/{ctx.obj}")
        timeline = client.get(f"/findings/{ctx.obj}/timeline")
        stdout.print(IssueWrapper(res.json(), history=timeline.json()))


@issue.command(name="status")
@click.argument("value", type=click.Choice(ISSUE_STATUSES, case_sensitive=False))
@opts.json_opt
@click.pass_obj
def issue_status(finding_id: int, value: str, **kwargs):
    if finding_id is None:
        raise click.UsageError("Missing argument 'FINDING-ID'.")
    res = client.patch(f"/findings/{finding_id}", json={"status": value.upper()})
    if is_json_output():
        stdout.print_json(res.json())
    else:
        stdout.print(f"Issue {finding_id} status set to {value.upper()}")


@issue.command(name="comment")
@click.argument("body")
@opts.json_opt
@click.pass_obj
def issue_comment(finding_id: int, body: str, **kwargs):
    if finding_id is None:
        raise click.UsageError("Missing argument 'FINDING-ID'.")
    res = client.post(f"/findings/{finding_id}/comments", json={"body": body})
    if is_json_output():
        stdout.print_json(res.json())
    else:
        data = res.json()
        stdout.print(f"Comment {data['id']} added to issue {finding_id}")


@issue.command(name="advisory")
@optgroup.group(cls=MutuallyExclusiveOptionGroup)
@optgroup.option("--publish", is_flag=True, help="Publish the draft advisory to GitHub")
@optgroup.option("--delete", is_flag=True, help="Delete the advisory")
@optgroup.option(
    "--status", is_flag=True, help="Fetch remote GitHub advisory status"
)
@opts.json_opt
@click.pass_obj
def issue_advisory(
    finding_id: int, publish: bool, delete: bool, status: bool, **kwargs
):
    if finding_id is None:
        raise click.UsageError("Missing argument 'FINDING-ID'.")

    body = {"finding_id": finding_id}

    if delete:
        client.request("DELETE", "/external_issues/security_advisory", json=body)
        if not is_json_output():
            stdout.print("Advisory deleted")
        return

    if publish:
        res = client.post(
            "/external_issues/security_advisory/publish",
            json=body,
            timeout=30,
        )
        data = res.json()
        if is_json_output():
            stdout.print_json(data)
        else:
            stdout.print(data.get("external_url") or data["external_id"])
        return

    if status:
        list_res = client.get(
            "/external_issues",
            params={
                "finding_id": finding_id,
                "kind": "SECURITY_ADVISORY",
                "quantity": 1,
            },
        )
        items = list_res.json().get("items") or []
        if not items:
            raise click.UsageError("No security advisory found for this issue.")
        res = client.get(f"/external_issues/{items[0]['id']}/status")
        data = res.json()
        if is_json_output():
            stdout.print_json(data)
        else:
            stdout.print(data["status"])
        return

    res = client.post(
        "/external_issues/security_advisory",
        json=body,
        timeout=10,
    )
    data = res.json()
    if is_json_output():
        stdout.print_json(data)
    else:
        stdout.print(ExternalIssueWrapper(data))
        stdout.print(f"View on web: {advisory_url(data['id'])}")
        stderr.print(
            "WARNING: Draft is not published yet. "
            f"Publish with: satori-v2 issue {finding_id} advisory --publish"
        )
