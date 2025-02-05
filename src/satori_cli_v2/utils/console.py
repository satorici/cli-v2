from base64 import b64decode
import json
import time

import httpx
from rich import progress
from rich.console import Console

from ..api import client

stdout = Console()
stderr = Console(stderr=True)


def wait_job_until_finished(job_id: int):
    with progress.Progress(
        progress.SpinnerColumn("dots2"),
        progress.TextColumn("[progress.description]Status: {task.description}"),
        progress.TimeElapsedColumn(),
        console=stderr,
    ) as p:
        status = "QUEUED"
        task = p.add_task(status)

        while status not in ("FINISHED", "CANCELED"):
            res = client.get(f"jobs/{job_id}")
            status = res.json()["status"]
            p.update(task, description=status)
            time.sleep(1)


def show_execution_output(execution_id: int):
    with client.stream(
        "GET", f"/executions/{execution_id}/output", follow_redirects=True
    ) as s:
        for line in s.iter_lines():
            loaded = json.loads(line)
            stdout.out("Command:", loaded["original"])

            results = loaded["output"]

            stdout.out("Return code:", results["return_code"])
            stdout.out("Stdout:")
            stdout.out(b64decode(results["stdout"]).decode(errors="ignore"), highlight=False)
            stdout.out("Stderr:")
            stdout.out(b64decode(results["stderr"]).decode(errors="ignore"), highlight=False)
            stdout.out()


def show_execution_report(execution_id: int):
    res = client.get(f"/executions/{execution_id}", follow_redirects=True)
    res.raise_for_status()
    stdout.print_json(res.text)


def download_execution_files(execution_id: int):
    res = client.get(f"/executions/{execution_id}/files")

    with httpx.stream("GET", res.headers["Location"]) as s:
        total = int(s.headers["Content-Length"])

        with progress.Progress(console=stderr) as p:
            task = p.add_task("Downloading...", total=total)

            with open(f"satorici-files-{execution_id}.tar.gz", "wb") as f:
                for chunk in s.iter_raw():
                    p.update(task, advance=len(chunk))
                    f.write(chunk)
