import time

from rich import progress

from ..api import client


def wait_job_until_finished(job_id: int):
    with progress.Progress(
        progress.SpinnerColumn("dots2"),
        progress.TextColumn("[progress.description]Status: {task.description}"),
        progress.TimeElapsedColumn(),
    ) as p:
        status = "QUEUED"
        task = p.add_task(status)

        while status not in ("FINISHED", "CANCELED"):
            res = client.get(f"jobs/{job_id}")
            status = res.json()["status"]
            p.update(task, description=status)
            time.sleep(1)


def show_execution_output(execution_id: int):
    res = client.get(f"/executions/{execution_id}/output", follow_redirects=True)
    print(res.text)
