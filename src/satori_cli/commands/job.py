from typing import Optional

import rich_click as click

from ..api import client
from ..utils.console import stdout

job_id_arg = click.argument("job-id", type=int)


@click.group()
def job():
    pass


@job.command()
@job_id_arg
def get(job_id: int):
    res = client.get(f"/jobs/{job_id}")
    stdout.print_json(res.text)


def list_jobs(page: int, quantity: int, type: Optional[str], visibility: Optional[str]):
    params = {k: v for k, v in locals().items() if v is not None}

    res = client.get("/jobs", params=params)
    stdout.print_json(res.text)


@job.command("list")
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option("--type")
@click.option("--visibility", type=click.Choice(["PUBLIC", "UNLISTED", "PRIVATE"]))
def _(**kwargs):
    return list_jobs(**kwargs)


@job.command()
@job_id_arg
def delete(job_id: int):
    client.delete(f"/jobs/{job_id}")


@job.command()
@job_id_arg
def pause(job_id: int):
    client.patch(f"/jobs/{job_id}/pause")


@job.command()
@job_id_arg
def start(job_id: int):
    client.patch(f"/jobs/{job_id}/start")


@job.command()
@job_id_arg
def cancel(job_id: int):
    client.patch(f"/jobs/{job_id}/cancel")
