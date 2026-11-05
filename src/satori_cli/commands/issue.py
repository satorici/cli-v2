import rich_click as click
from click_option_group import MutuallyExclusiveOptionGroup, optgroup
from httpx2 import HTTPStatusError

from ..api import client
from ..constants import advisory_url
from ..utils import options as opts
from ..utils.console import stderr, stdout
from ..utils.format import is_json_output
from ..utils.groups import IdGroup
from ..utils.public_id import EXECUTION_ID, FINDING_ID
from ..utils.verify_issue import verify_issue
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
EXPLOITABILITY_VALUES = [
    "UNKNOWN",
    "EXPLOITABLE",
    "NOT_EXPLOITABLE",
    "INCONCLUSIVE",
]

# The position is the numeric severity: 0 = BLOCKER (worst) … 5 = INFO.
SEVERITY_ALIASES = ("BLOCKER", "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")


def severity_name_to_int(name: str) -> int | None:
    """Map a severity name (case-insensitive) to 0–5, or None if unknown."""
    upper = name.upper()
    if upper not in SEVERITY_ALIASES:
        return None
    return SEVERITY_ALIASES.index(upper)


def normalize_severities(values: list[int | str]) -> list[int] | str:
    """Normalize ints/names to severity ints. Returns an error string on failure."""
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        if isinstance(value, int):
            if value < 0 or value > 5:
                return f"severity ints must be 0-5; got {value}."
            index = value
        elif isinstance(value, str):
            index = severity_name_to_int(value)
            if index is None:
                return (
                    f"Invalid severity {value!r}. "
                    f"Choose from {', '.join(SEVERITY_ALIASES)} or ints 0-5."
                )
        else:
            return (
                f"severity entries must be ints or names; got {type(value).__name__}."
            )
        if index not in seen:
            seen.add(index)
            result.append(index)
    return result


def parse_severity_csv(
    ctx: click.Context, param: click.Parameter, value: str | None
) -> list[int] | None:
    if value is None:
        return None
    parts = [part.strip() for part in value.split(",")]
    if not parts or any(not part for part in parts):
        raise click.BadParameter(
            f"Expected comma-separated severities from {', '.join(SEVERITY_ALIASES)}."
        )
    normalized = normalize_severities(parts)
    if isinstance(normalized, str):
        raise click.BadParameter(normalized)
    return normalized


def list_issues(
    page: int,
    quantity: int,
    execution_id: str | None = None,
    status: str | None = None,
    exploitability: str | None = None,
    source: str | None = None,
    severity: list[int] | None = None,
    order: str | None = None,
):
    params = {
        k: v
        for k, v in {
            "page": page,
            "quantity": quantity,
            "execution_id": execution_id,
            "status": status.upper() if status else None,
            "exploitability": exploitability.upper() if exploitability else None,
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
            key=lambda f: f["severity"] if f.get("severity") is not None else 6,
        )
    if data["total"] == 0:
        stdout.print("[bold blue]No issues found[/bold blue]")
        return
    stdout.print(PagedWrapper(data, page, quantity, IssueListWrapper))


@click.command("issues")
@click.argument(
    "execution_id_arg", metavar="EXECUTION-ID", type=EXECUTION_ID, required=False
)
@click.option("--execution-id", "execution_id_opt", type=EXECUTION_ID)
@click.option(
    "--status",
    type=click.Choice(ISSUE_STATUSES, case_sensitive=False),
)
@click.option(
    "--exploitability",
    type=click.Choice(EXPLOITABILITY_VALUES, case_sensitive=False),
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
    execution_id_arg: str | None,
    execution_id_opt: str | None,
    status: str | None,
    exploitability: str | None,
    source: str | None,
    severity: list[int] | None,
    order: str | None,
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
        exploitability=exploitability,
        source=source,
        severity=severity,
        order=order,
    )


@click.group(cls=IdGroup, id_type=FINDING_ID, invoke_without_command=True)
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
def issue_status(finding_id: str, value: str, **kwargs):
    if finding_id is None:
        raise click.UsageError("Missing argument 'FINDING-ID'.")
    res = client.patch(f"/findings/{finding_id}", json={"status": value.upper()})
    if is_json_output():
        stdout.print_json(res.json())
    else:
        stdout.print(f"Issue {finding_id} status set to {value.upper()}")


@issue.command(name="exploitability")
@click.argument("value", type=click.Choice(EXPLOITABILITY_VALUES, case_sensitive=False))
@click.option("--reason", help="Reason recorded in the finding timeline")
@opts.json_opt
@click.pass_obj
def issue_exploitability(finding_id: str, value: str, reason: str | None, **kwargs):
    if finding_id is None:
        raise click.UsageError("Missing argument 'FINDING-ID'.")
    normalized = value.upper()
    if normalized != "UNKNOWN" and not (reason or "").strip():
        raise click.UsageError("--reason is required unless exploitability is UNKNOWN.")
    res = client.patch(
        f"/findings/{finding_id}",
        json={
            "exploitability": normalized,
            "exploitability_reason": (reason or "").strip() or None,
        },
    )
    if is_json_output():
        stdout.print_json(res.json())
    else:
        stdout.print(f"Issue {finding_id} exploitability set to {normalized}")


@issue.command(name="comment")
@click.argument("body")
@opts.json_opt
@click.pass_obj
def issue_comment(finding_id: str, body: str, **kwargs):
    if finding_id is None:
        raise click.UsageError("Missing argument 'FINDING-ID'.")
    res = client.post(f"/findings/{finding_id}/comments", json={"body": body})
    if is_json_output():
        stdout.print_json(res.json())
    else:
        data = res.json()
        stdout.print(f"Comment {data['id']} added to issue {finding_id}")


@issue.command(name="verify")
@click.pass_obj
def issue_verify(finding_id: str):
    """Verify a finding with Claude Code (3-agent majority → comment + TP/FP)."""
    if finding_id is None:
        raise click.UsageError("Missing argument 'FINDING-ID'.")
    verify_issue(finding_id)


@issue.command(name="advisory")
@optgroup.group(cls=MutuallyExclusiveOptionGroup)
@optgroup.option("--publish", is_flag=True, help="Publish the draft advisory to GitHub")
@optgroup.option("--delete", is_flag=True, help="Delete the advisory")
@optgroup.option("--status", is_flag=True, help="Fetch remote GitHub advisory status")
@optgroup.option(
    "--improve",
    is_flag=True,
    help="Rewrite the draft's title/description into a comprehensive report with Claude Code",
)
@opts.json_opt
@click.pass_obj
def issue_advisory(
    finding_id: str, publish: bool, delete: bool, status: bool, improve: bool, **kwargs
):
    if finding_id is None:
        raise click.UsageError("Missing argument 'FINDING-ID'.")

    body = {"finding_id": finding_id}

    if improve:
        from ..utils.improve_report import UsageLimitError as ImproveUsageLimitError
        from ..utils.improve_report import improve_advisory

        try:
            report = improve_advisory(finding_id)
        except ImproveUsageLimitError as error:
            raise click.ClickException(
                "Claude usage limit reached; re-run to continue."
            ) from error
        if report is None:
            raise click.ClickException("Could not improve this advisory (see warnings above).")
        if is_json_output():
            stdout.print_json(report)
        else:
            stdout.print("Advisory improved")
            stdout.print(f"New title: {report['title']}")
        return

    if delete:
        res = client.request("DELETE", "/external_issues/security_advisory", json=body)
        data = res.json()
        if is_json_output():
            stdout.print_json(data)
        else:
            stdout.print("Advisory deleted")
            if warning := data.get("warning"):
                stderr.print(f"WARNING: {warning}")
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

    try:
        res = client.post(
            "/external_issues/security_advisory",
            json=body,
            timeout=10,
        )
        data = res.json()
    except HTTPStatusError as e:
        if e.response.status_code != 409:
            raise
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
            raise
        data = items[0]

    timeline = client.get(f"/findings/{finding_id}/timeline").json()
    stdout.print(ExternalIssueWrapper(data, history=timeline))
    if not is_json_output():
        stdout.print(f"View on web: {advisory_url(data['id'])}")
        if not data.get("external_id"):
            stderr.print(
                "WARNING: Draft is not published yet. "
                f"Publish with: satori-v2 issue {finding_id} advisory --publish"
            )
