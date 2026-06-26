from typing import Optional

import rich_click as click

from ..api import client
from ..utils import options as opts
from ..utils.console import (
    download_execution_files,
    show_execution_output,
    stdout,
)
from ..utils.wrappers import ExecutionListWrapper, ExecutionWrapper, PagedWrapper


@click.command()
@click.argument("job-id", type=int, required=False)
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option(
    "--status", type=click.Choice(["FINISHED", "CANCELED", "RUNNING", "QUEUED"])
)
@click.option("--public", "visibility", flag_value="PUBLIC")
@opts.json_opt
def reports(
    job_id: Optional[int],
    page: int,
    quantity: int,
    status: str,
    visibility: str,
    **kwargs,
):
    params = {k: v for k, v in locals().items() if v is not None and k != "kwargs"}

    res = client.get("/executions", params=params)
    stdout.print(PagedWrapper(res.json(), page, quantity, ExecutionListWrapper))


@click.group(invoke_without_command=True)
@click.argument("execution-id", type=int)
@opts.json_opt
@click.pass_context
def report(ctx, execution_id: int, **kwargs):
    ctx.obj = execution_id
    if ctx.invoked_subcommand is None:
        res = client.get(f"/executions/{execution_id}")
        stdout.print(ExecutionWrapper(res.json()))


# Aliases for report command
@report.command(name="output")
@click.pass_obj
def report_output(execution_id: int):
    show_execution_output(execution_id)


@report.command(name="files")
@click.pass_obj
def report_files(execution_id: int):
    download_execution_files(execution_id)


@report.command(name="delete")
@click.pass_obj
def report_delete(execution_id: int):
    client.delete(f"/executions/{execution_id}")


@report.command(name="visibility")
@click.argument(
    "value", type=click.Choice(["PUBLIC", "PRIVATE", "UNLISTED"], case_sensitive=False)
)
@click.pass_obj
def report_visibility(execution_id: int, value: str):
    client.patch(f"/executions/{execution_id}", json={"visibility": value.upper()})
    stdout.print(f"Report visibility set to {value.upper()}")
