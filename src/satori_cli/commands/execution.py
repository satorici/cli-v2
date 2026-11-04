from typing import Optional

import rich_click as click

from ..api import client
from ..utils import options as opts
from ..utils.console import (
    download_execution_files,
    show_execution,
    show_execution_output,
    stdout,
)
from ..utils.public_id import EXECUTION_ID, JOB_ID

execution_id_arg = click.argument("execution-id", type=EXECUTION_ID)


@click.group()
def execution():
    pass


@execution.command()
@execution_id_arg
def get(execution_id: str):
    show_execution(execution_id)


@execution.command()
@click.option("--job-type")
@click.option("--job-id", type=JOB_ID)
@opts.pagination_opts
def list(page: int, quantity: int, job_type: Optional[str], job_id: Optional[str]):
    params = {k: v for k, v in locals().items() if v is not None}

    res = client.get("/executions", params=params)
    stdout.print_json(res.text)


@execution.command()
@execution_id_arg
def delete(execution_id: str):
    client.delete(f"/executions/{execution_id}")


@execution.command()
@execution_id_arg
def stop(execution_id: str):
    client.patch(f"/executions/{execution_id}", json={"status": "CANCELED"})


@execution.command()
@execution_id_arg
@click.option("--test", "filter_tests", multiple=True)
@opts.format_opt
def output(execution_id: str, filter_tests: tuple[str, ...], **kwargs):
    show_execution_output(
        execution_id, filter_tests=list(filter_tests) or None
    )


@execution.command()
@execution_id_arg
def files(execution_id: str):
    download_execution_files(execution_id)
