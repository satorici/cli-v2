from typing import Optional

import httpx
import rich_click as click

from ..api import client
from ..utils import options as opts
from ..utils.console import (
    download_execution_files,
    load_execution_outputs,
    show_execution_output,
    stdout,
)
from ..utils.format import is_json_output
from ..utils.groups import IdGroup
from ..utils.parsers import parse_dynamic_output
from ..utils.wrappers import (
    DynamicFindingsWrapper,
    ExecutionListWrapper,
    ExecutionWrapper,
    PagedWrapper,
)
from .search import reports_delete, reports_download, reports_search, reports_stop


class JobIdGroup(IdGroup):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, id_attr="job_id", **kwargs)


@click.group(cls=JobIdGroup, invoke_without_command=True)
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option(
    "--status",
    type=click.Choice(
        ["FINISHED", "CANCELED", "RUNNING", "QUEUED"], case_sensitive=False
    ),
)
@click.option("--public", "visibility", flag_value="PUBLIC")
@opts.json_opt
@click.pass_context
def reports(
    ctx,
    page: int,
    quantity: int,
    status: str,
    visibility: str,
    **kwargs,
):
    if ctx.invoked_subcommand is None:
        job_id: Optional[int] = getattr(ctx, "job_id", None)
        params = {
            k: v
            for k, v in locals().items()
            if v is not None and k not in ("kwargs", "ctx")
        }

        res = client.get("/executions", params=params)
        stdout.print(PagedWrapper(res.json(), page, quantity, ExecutionListWrapper))


reports.add_command(reports_search, name="search")
reports.add_command(reports_download, name="download")
reports.add_command(reports_stop, name="stop")
reports.add_command(reports_delete, name="delete")


def _parsed_findings_groups(execution_id: int) -> list[tuple[str, list]]:
    groups: list[tuple[str, list]] = []
    try:
        outputs = load_execution_outputs(execution_id)
    except (httpx.HTTPError, OSError, ValueError):
        return groups

    for output in outputs:
        result = output.get("output") or {}
        stdout_text = result.get("stdout")
        if not stdout_text:
            continue
        findings = parse_dynamic_output(stdout_text)
        if findings:
            groups.append((output.get("path") or "test", findings))
    return groups


@click.group(cls=IdGroup, invoke_without_command=True)
@opts.json_opt
@click.pass_context
def report(ctx, **kwargs):
    if ctx.invoked_subcommand is None:
        if ctx.obj is None:
            raise click.UsageError("Missing argument 'EXECUTION-ID'.")
        res = client.get(f"/executions/{ctx.obj}")
        stdout.print(ExecutionWrapper(res.json()))

        if not is_json_output():
            groups = _parsed_findings_groups(ctx.obj)
            if groups:
                stdout.print(DynamicFindingsWrapper(groups))


# Aliases for report command
@report.command(name="output")
@click.option("--test", "filter_tests", multiple=True)
@opts.format_opt
@opts.json_opt
@click.pass_obj
def report_output(execution_id: int, filter_tests: tuple[str, ...], **kwargs):
    show_execution_output(
        execution_id, filter_tests=list(filter_tests) or None
    )


@report.command(name="files")
@click.pass_obj
def report_files(execution_id: int):
    download_execution_files(execution_id)


@report.command(name="delete")
@click.pass_obj
def report_delete(execution_id: int):
    client.delete(f"/executions/{execution_id}")
    stdout.print(f"Report {execution_id} deleted")


@report.command(name="visibility")
@click.argument(
    "value", type=click.Choice(["PUBLIC", "PRIVATE", "UNLISTED"], case_sensitive=False)
)
@click.pass_obj
def report_visibility(execution_id: int, value: str):
    client.patch(f"/executions/{execution_id}", json={"visibility": value.upper()})
    stdout.print(f"Report visibility set to {value.upper()}")
