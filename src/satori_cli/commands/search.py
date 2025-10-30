import math
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from io import BytesIO
from itertools import groupby
from pathlib import Path
from typing import Optional

import msgpack
import rich_click as click
from click_option_group import MutuallyExclusiveOptionGroup, optgroup
from rich.console import Console
from rich.prompt import Confirm

from ..api import client
from ..utils import options as opts
from ..utils.console import stderr, stdout
from ..utils.misc import remove_none_values
from ..utils.wrappers import ExecutionListWrapper, OutputWrapper, PagedWrapper


def isodatetime(arg: str):
    return datetime.fromisoformat(arg)


def get_execution_ids(params):
    executions_per_request = 500
    params["page"] = 1
    params["quantity"] = executions_per_request

    res = client.get("/executions", params=params)
    body = res.json()

    total = body["total"]
    execution_ids = [item["id"] for item in body["items"]]

    def fetch_ids(page: int):
        res = client.get("/executions", params=params | {"page": page})
        body = res.json()

        return [item["id"] for item in body["items"]]

    if total > executions_per_request:
        pages = math.ceil(total / executions_per_request)
        futures: list[Future[list[int]]] = []

        with ThreadPoolExecutor(max_workers=8) as executor:
            for page in range(2, pages + 1):
                futures.append(executor.submit(fetch_ids, page))

        for future in futures:
            execution_ids.extend(future.result())

    return execution_ids


def bulk_download(path: Path, params):
    if params["status"] and params["status"] != ("FINISHED",):
        stderr.print("Only FINISHED executions can be downloaded")
        sys.exit(1)

    params["status"] = ["FINISHED"]

    execution_ids = get_execution_ids(params)

    def download(id):
        res = client.get(f"/executions/{id}/output", follow_redirects=True)

        with (path / f"output-{id}.txt").open("w") as f:
            console = Console(file=f, width=120)
            loaded = msgpack.Unpacker(BytesIO(res.content))
            grouped = groupby(loaded, lambda o: o["path"])

            for test_path, outputs in grouped:
                console.rule(test_path)

                for output in outputs:
                    console.print(OutputWrapper(output))

    path.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor() as executor:
        for execution_id in execution_ids:
            executor.submit(download, execution_id)

    stdout.print("Executions downloaded")


def bulk_stop(params):
    if params["status"] and params["status"] != ("RUNNING",):
        stderr.print("Only RUNNING executions can be stopped")
        sys.exit(1)

    params["status"] = ["RUNNING"]

    execution_ids = get_execution_ids(params)

    with ThreadPoolExecutor() as executor:
        for execution_id in execution_ids:
            executor.submit(client.patch, f"/executions/{execution_id}/cancel")

    stdout.print("Executions stopped")


def bulk_delete(params):
    statuses = params["status"]

    if not statuses:
        params["status"] = ["CANCELED", "FINISHED"]

    if statuses and set(statuses) != {"CANCELED", "FINISHED"}:
        stderr.print("Only CANCELED or FINISHED executions can be deleted")
        sys.exit(1)

    execution_ids = get_execution_ids(params)

    if not Confirm.ask(
        f"About to delete {len(execution_ids)} executions", console=stderr
    ):
        sys.exit()

    with ThreadPoolExecutor() as executor:
        for execution_id in execution_ids:
            executor.submit(client.delete, f"/executions/{execution_id}")

    stdout.print("Executions deleted")


@click.command()
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option(
    "--job-type", type=click.Choice(["RUN", "SCAN", "MONITOR", "GITHUB", "LOCAL"])
)
@click.option("--job-id", type=int)
@click.option("--global", is_flag=True)
@optgroup.group(cls=MutuallyExclusiveOptionGroup)
@optgroup.option("--download", type=Path, help="Path to download outputs")
@optgroup.option("--stop", is_flag=True)
@optgroup.option("--delete", is_flag=True)
@click.option(
    "--status",
    type=click.Choice(["FINISHED", "CANCELED", "RUNNING", "QUEUED"]),
    multiple=True,
)
@opts.visibility_opt
@click.option("--from", type=isodatetime)
@click.option("--to", type=isodatetime)
@click.option("--report-status", type=click.Choice(["PASS", "FAIL"]))
@click.option("--severity", type=click.IntRange(min=0, max=5))
@click.option("--playbook")
@click.option("--q")
@click.option("--tag", "-t", "tags", multiple=True)
def search(download: Optional[Path], stop: bool, delete: bool, **kwargs):
    params = remove_none_values(kwargs)

    if download:
        bulk_download(download, params)
        return
    if stop:
        bulk_stop(params)
        return
    if delete:
        bulk_delete(params)
        return

    res = client.get("/executions", params=params)

    stdout.print(
        PagedWrapper(
            res.json(), params["page"], params["quantity"], ExecutionListWrapper
        )
    )
