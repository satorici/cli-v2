from typing import Optional

import rich_click as click

from ..api import client
from ..utils import options as opts
from ..utils.console import stdout
from ..utils.groups import IdGroup
from ..utils.misc import list_jobs
from ..utils.wrappers import JobWrapper


@click.command("monitors")
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option("--public", "visibility", flag_value="PUBLIC")
@opts.json_opt
def list_monitors(page: int, quantity: int, visibility: Optional[str], **kwargs):
    return list_jobs(page, quantity, "MONITOR", visibility)


@click.group(cls=IdGroup, invoke_without_command=True)
@opts.json_opt
@click.pass_context
def monitor(ctx, **kwargs):
    if ctx.invoked_subcommand is None:
        if ctx.obj is None:
            raise click.UsageError("Missing argument 'MONITOR-ID'.")
        res = client.get(f"/jobs/{ctx.obj}")
        stdout.print(JobWrapper(res.json()))


@monitor.command(name="visibility")
@click.argument(
    "value", type=click.Choice(["PUBLIC", "PRIVATE", "UNLISTED"], case_sensitive=False)
)
@click.pass_obj
def monitor_visibility(monitor_id: int, value: str):
    client.patch(f"/jobs/{monitor_id}", json={"visibility": value.upper()})
    stdout.print(f"Monitor visibility set to {value.upper()}")


@monitor.command(name="start")
@click.pass_obj
def monitor_start(monitor_id: int):
    client.patch(f"/jobs/monitors/{monitor_id}", json={"status": "RUNNING"})
    stdout.print("Monitor started")


@monitor.command(name="pause")
@click.pass_obj
def monitor_pause(monitor_id: int):
    client.patch(f"/jobs/monitors/{monitor_id}", json={"status": "PAUSED"})
    stdout.print("Monitor paused")


# `stop` is an alias of `pause`
monitor.add_command(monitor_pause, name="stop")


@monitor.command(name="clean")
@click.pass_obj
def monitor_clean(monitor_id: int):
    execution_ids: list[int] = []
    page = 1

    while True:
        res = client.get(
            "/executions",
            params={"job_id": monitor_id, "quantity": 100, "page": page},
        )
        data = res.json()
        items = data["items"]

        if not items:
            break

        execution_ids.extend(item["id"] for item in items)

        if len(execution_ids) >= data["total"]:
            break

        page += 1

    if execution_ids:
        client.post("/executions/delete", json=execution_ids)

    stdout.print(f"Deleted {len(execution_ids)} reports")


@monitor.command(name="delete")
@click.pass_obj
def monitor_delete(monitor_id: int):
    client.delete(f"/jobs/{monitor_id}")
    stdout.print("Monitor deleted")
