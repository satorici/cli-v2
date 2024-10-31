import time

import httpx
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


def download_execution_files(execution_id: int):
    res = client.get(f"/executions/{execution_id}/files")

    with httpx.stream("GET", res.headers["Location"]) as s:
        total = int(s.headers["Content-Length"])

        with progress.Progress() as p:
            task = p.add_task("Downloading...", total=total)

            with open(f"satorici-files-{execution_id}.tar.gz", "wb") as f:
                for chunk in s.iter_raw():
                    p.update(task, advance=len(chunk))
                    f.write(chunk)
