from typing import Optional

import rich
import rich_click as click

from ..api import client

job_id_arg = click.argument("job-id", type=int)


@click.group()
def job():
    pass


@job.command()
@job_id_arg
def get(job_id: int):
    res = client.get(f"/jobs/{job_id}")
    rich.print_json(res.text)


@job.command("list")
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option("--type")
def list_(page: int, quantity: int, type: Optional[str]):
    params = {k: v for k, v in locals().items() if v is not None}

    res = client.get("/jobs", params=params)
    rich.print_json(res.text)


@job.command()
@job_id_arg
def delete(job_id: int):
    client.delete(f"/jobs/{job_id}")
