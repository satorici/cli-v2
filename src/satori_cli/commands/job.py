import rich_click as click

from ..api import client
from ..utils.console import stdout
from ..utils.wrappers import JobWrapper

job_id_arg = click.argument("job-id", type=int)


@click.command()
@click.argument("job-id", type=int)
def job(job_id: int):
    res = client.get(f"/jobs/{job_id}")
    stdout.print(JobWrapper(res.json()))
