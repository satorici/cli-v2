import io
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Literal

import httpx
import msgpack
from rich import progress
from rich.console import Console

from ..api import client
from ..exceptions import SatoriError
from ..utils.output_filter import run_test_filter
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
            else:
                raise SatoriError("Fetch status failed after 3 retries")

            time.sleep(1)


def _print_output_entry(output: dict, console: Console, current_path: str) -> str:
    if result := output.get("filtered_result"):
        value = output["output"].get(result)
        if value is not None:
            if isinstance(value, bytes):
                value = value.decode(errors="ignore")
            console.print(value, highlight=False, markup=False, soft_wrap=True)
        return current_path

    if current_path != output["path"]:
        console.rule(output["path"])
        current_path = output["path"]

    console.print(OutputWrapper(output))
    return current_path


def format_raw_results(file, console=None, filter_tests: list[str] | None = None):
    console = console or stdout
    outputs = [line for line in msgpack.Unpacker(file) if line]

    if filter_tests:
        outputs = run_test_filter(filter_tests, outputs)

    current_path = ""
    for output in outputs:
        current_path = _print_output_entry(output, console, current_path)


def show_raw_output(execution_id: int, stream: Literal["stdout", "stderr"]):
    with SpooledTemporaryFile() as f:
        res = client.get(f"/executions/{execution_id}/output", follow_redirects=True)
        f.write(res.content)
        f.seek(0)

        for output in msgpack.Unpacker(f):
            stdout.print(output["output"][stream].decode(errors="ignore"))


def show_execution_output(
    execution_id: int, console=None, filter_tests: list[str] | None = None
):
    class HttpxStreamFile(io.RawIOBase):
        def __init__(self, response: httpx.Response):
            self._iter = response.iter_bytes()

        def readable(self):
            return True

        def readinto(self, b):
            try:
                chunk = next(self._iter)
                n = len(chunk)
                b[:n] = chunk
                return n
            except StopIteration:
                return 0

    with client.stream(
        "GET", f"/executions/{execution_id}/output", follow_redirects=True, timeout=None
    ) as stream:
        format_raw_results(HttpxStreamFile(stream), console, filter_tests)


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
