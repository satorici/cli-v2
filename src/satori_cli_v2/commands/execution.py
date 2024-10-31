from typing import Optional

import rich
import rich_click as click

from ..api import client
from ..utils.console import show_execution_output

execution_id_arg = click.argument("execution-id", type=int)


@click.group()
def execution():
    pass


@execution.command()
@execution_id_arg
def get(execution_id: int):
    res = client.get(f"/executions/{execution_id}")
    rich.print_json(res.text)


@execution.command()
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option("--job-type")
@click.option("--job-id", type=int)
def list(page: int, quantity: int, job_type: Optional[str], job_id: Optional[int]):
    params = {k: v for k, v in locals().items() if v is not None}

    res = client.get("/executions", params=params)
    rich.print_json(res.text)


@execution.command()
@execution_id_arg
def delete(execution_id: int):
    client.delete(f"/executions/{execution_id}")


@execution.command()
@execution_id_arg
def output(execution_id: int):
    show_execution_output(execution_id)
