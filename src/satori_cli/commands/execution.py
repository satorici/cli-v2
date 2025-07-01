from typing import Optional

import rich_click as click

from ..api import client
from ..utils.console import (
    download_execution_files,
    show_execution,
    show_execution_output,
    stdout,
)

execution_id_arg = click.argument("execution-id", type=int)


@click.group()
def execution():
    pass


@execution.command()
@execution_id_arg
def get(execution_id: int):
    show_execution(execution_id)


@execution.command()
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option("--job-type")
@click.option("--job-id", type=int)
def list(page: int, quantity: int, job_type: Optional[str], job_id: Optional[int]):
    params = {k: v for k, v in locals().items() if v is not None}

    res = client.get("/executions", params=params)
    stdout.print_json(res.text)


@execution.command()
@execution_id_arg
def delete(execution_id: int):
    client.delete(f"/executions/{execution_id}")


@execution.command()
@execution_id_arg
def stop(execution_id: int):
    client.patch(f"/executions/{execution_id}/stop")


@execution.command()
@execution_id_arg
def output(execution_id: int):
    show_execution_output(execution_id)


@execution.command()
@execution_id_arg
def files(execution_id: int):
    download_execution_files(execution_id)
