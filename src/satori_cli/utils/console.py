import json
import sys
import time
from base64 import b64decode

import httpx
from rich import progress
from rich.console import Console

from ..api import client
from ..utils.wrappers import ExecutionWrapper

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
            if stdout_ := results["stdout"]:
                sys.stdout.buffer.write(b64decode(stdout_))
                stdout.out()

            stdout.out("Stderr:")
            if stderr_ := results["stderr"]:
                sys.stdout.buffer.write(b64decode(stderr_))
                stdout.out()

            stdout.out()


def show_execution(execution_id: int):
    res = client.get(f"/executions/{execution_id}", follow_redirects=True)
    stdout.print(ExecutionWrapper(res.json()))


def download_execution_files(execution_id: int):
    res = client.get(f"/executions/{execution_id}/files")

    with httpx.stream("GET", res.headers["Location"]) as s:
        s.raise_for_status()

        total = int(s.headers["Content-Length"])

        with progress.Progress(console=stderr) as p:
            task = p.add_task("Downloading...", total=total)

            with open(f"satorici-files-{execution_id}.tar.gz", "wb") as f:
                for chunk in s.iter_raw():
                    p.update(task, advance=len(chunk))
                    f.write(chunk)
