from concurrent.futures import ThreadPoolExecutor

import rich_click as click

from ..api import client
from ..utils.console import stdout

job_id_arg = click.argument("run-id", type=int)


@click.group()
def stop():
    pass


@stop.command()
@job_id_arg
def run(run_id: int):
    client.patch(f"/jobs/runs/{run_id}", json={"status": "CANCELED"})
    stdout.print("Run stopped")


@stop.command()
def all():
    res = client.get("/jobs", params={"type": "RUN", "quantity": 100})

    last_runs = res.json()

    run_ids = [
        run["id"]
        for run in last_runs["items"]
        if run["status"] in ("QUEUED", "RUNNING")
    ]

    with ThreadPoolExecutor() as executor:
        for run_id in run_ids:
            executor.submit(
                client.patch, f"/jobs/runs/{run_id}", json={"status": "CANCELED"}
            )

    stdout.print("Runs stopped")
