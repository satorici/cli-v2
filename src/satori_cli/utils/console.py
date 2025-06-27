import time
from concurrent.futures import ThreadPoolExecutor
from itertools import groupby
from pathlib import Path

import httpx
import msgpack
from rich import progress
from rich.console import Console

from ..api import client
from ..utils.wrappers import ExecutionWrapper, OutputWrapper

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
            tries = 0

            while tries < 4:
                try:
                    res = client.get(f"jobs/{job_id}")
                    status = res.json()["status"]
                    p.update(task, description=status)
                    break
                except httpx.TimeoutException:
                    tries += 1

            time.sleep(1)


def show_execution_output(execution_id: int):
    with client.stream(
        "GET", f"/executions/{execution_id}/output", follow_redirects=True
    ) as s:
        loaded = msgpack.Unpacker(s.extensions["network_stream"])
        grouped = groupby(loaded, lambda o: o["path"])

        for path, outputs in grouped:
            stdout.rule(path)

            for output in outputs:
                stdout.print(OutputWrapper(output))


def show_execution(execution_id: int):
    res = client.get(f"/executions/{execution_id}", follow_redirects=True)
    stdout.print(ExecutionWrapper(res.json()))


def download_execution_files(execution_id: int):
    res = client.get(f"/executions/{execution_id}/files")

    with httpx.stream("GET", res.headers["Location"]) as s:
        s.raise_for_status()

        total = int(s.headers["Content-Length"])

        with progress.Progress(console=stderr) as p:
            task = p.add_task(
                f"Downloading execution {execution_id} files...", total=total
            )

            with open(f"satorici-files-{execution_id}.tar.gz", "wb") as f:
                for chunk in s.iter_raw():
                    p.update(task, advance=len(chunk))
                    f.write(chunk)


def export_job_files(job_id: int, region: str | None = None, dest: str = "."):
    if not Path(dest).is_dir():
        Path(dest).mkdir(parents=True, exist_ok=True)

    def get_ids():
        page = 1

        while True:
            res = client.get(
                "/executions", params={"job_id": job_id, "page": page, "quantity": 100}
            ).json()

            if not res["items"]:
                break

            for item in res["items"]:
                if region is not None and item["data"].get("region") == region:
                    yield item["id"]
                    continue

                yield item["id"]

            page += 1

    with httpx.Client() as c:

        def download(id: int):
            url = client.get(f"/executions/{id}/files").headers["Location"]

            with c.stream("GET", url) as s:
                with Path(dest, f"satorici-files-{id}.tar.gz").open("wb") as f:
                    for chunk in s.iter_raw():
                        f.write(chunk)

        with ThreadPoolExecutor() as executor:
            executor.map(download, get_ids())
