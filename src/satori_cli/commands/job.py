import rich_click as click

from ..api import client
from ..utils.console import stdout
from ..utils.wrappers import ExecutionListWrapper, JobWrapper

job_id_arg = click.argument("job-id", type=int)


@click.command()
@click.argument("job-id", type=int)
def job(job_id: int):
    res = client.get(f"/jobs/{job_id}")
    stdout.print(JobWrapper(res.json()))
    res = client.get("/executions", params={"job_id": job_id, "quantity": 5})
    stdout.print("[b]Last 5 executions[/b]")
    stdout.print(ExecutionListWrapper(res.json()["items"]))
