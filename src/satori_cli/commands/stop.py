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
