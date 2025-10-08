import math
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import BytesIO
from itertools import groupby
from pathlib import Path
from typing import Optional

import msgpack
import rich_click as click
from click_option_group import MutuallyExclusiveOptionGroup, optgroup
from rich.console import Console

from ..api import client
from ..utils.console import stderr, stdout
from ..utils.misc import remove_none_values
from ..utils.wrappers import ExecutionListWrapper, OutputWrapper, PagedWrapper


def isodatetime(arg: str):
    return datetime.fromisoformat(arg)


def get_execution_ids(params):
    params["page"] = 1
    params["quantity"] = 100

    res = client.get("/executions", params=params)
    body = res.json()

    total = body["total"]
    execution_ids = [item["id"] for item in body["items"]]

    if total > 100:
        pages = math.ceil(total / 100)

        for page in range(2, pages + 1):
            res = client.get("/executions", params=params | {"page": page})
            body = res.json()

            execution_ids.extend(item["id"] for item in body["items"])

    return execution_ids


def bulk_download(path: Path, params):
    if "status" in params and params["status"] != "FINISHED":
        stderr.print("Only FINISHED executions can be downloaded")
        sys.exit(1)

    params["status"] = "FINISHED"

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
    if "status" in params and params["status"] != "RUNNING":
        stderr.print("Only RUNNING executions can be stopped")
        sys.exit(1)

    params["status"] = "RUNNING"

    execution_ids = get_execution_ids(params)

    with ThreadPoolExecutor() as executor:
        for execution_id in execution_ids:
            executor.submit(client.patch, f"/executions/{execution_id}/cancel")

    stdout.print("Executions stopped")


@click.command()
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option("--job-type", type=click.Choice(["RUN", "SCAN", "MONITOR", "GITHUB"]))
@click.option("--job-id", type=int)
@click.option("--global", is_flag=True)
@optgroup.group(cls=MutuallyExclusiveOptionGroup)
@optgroup.option("--download", type=Path, help="Path to download outputs")
@optgroup.option("--stop", is_flag=True)
@click.option(
    "--status", type=click.Choice(["FINISHED", "CANCELED", "RUNNING", "QUEUED"])
)
@click.option("--visibility", type=click.Choice(["PUBLIC", "PRIVATE", "UNLISTED"]))
@click.option("--from", type=isodatetime)
@click.option("--to", type=isodatetime)
@click.option("--report-status", type=click.Choice(["PASS", "FAIL"]))
@click.option("--severity", type=click.IntRange(min=0, max=5))
@click.option("--playbook")
def search(download: Optional[Path], stop: bool, **kwargs):
    params = remove_none_values(kwargs)

    if download:
        bulk_download(download, params)
        return
    if stop:
        bulk_stop(params)
        return

    res = client.get("/executions", params=params)

    stdout.print(
        PagedWrapper(
            res.json(), params["page"], params["quantity"], ExecutionListWrapper
        )
    )
