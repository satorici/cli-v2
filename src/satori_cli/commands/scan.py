from typing import Optional

import rich_click as click

from ..api import client
from ..exceptions import SatoriError
from ..utils import options as opts
from ..utils.arguments import Source, source_arg
from ..utils.console import stdout, wait_job_until_finished
from ..utils.misc import list_jobs, remove_none_values
from ..utils.wrappers import JobWrapper


class ScanGroup(click.Group):
    def parse_args(self, ctx, args):
        if args and args[0].isdigit() and (
            len(args) == 1 or args[1] in self.commands
        ):
            ctx.obj = int(args.pop(0))
        return super().parse_args(ctx, args)

    def resolve_command(self, ctx, args):
        if ctx.obj is None and args:
            return "create", self.commands["create"], args
        return super().resolve_command(ctx, args)

    def list_commands(self, ctx):
        return [name for name in super().list_commands(ctx) if name != "create"]


@click.command("scans")
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option("--public", "visibility", flag_value="PUBLIC")
@opts.json_opt
def list_scans(page: int, quantity: int, visibility: Optional[str], **kwargs):
    return list_jobs(page, quantity, "SCAN", visibility)


@click.group(cls=ScanGroup, invoke_without_command=True)
@opts.json_opt
@click.pass_context
def scan(ctx, **kwargs):
    """Start a repository scan or manage an existing scan.

    Create: scan REPOSITORY SOURCE [OPTIONS]

    Manage: scan SCAN_ID [status|stop|clean|delete]
    """
    if ctx.invoked_subcommand is None and ctx.obj is not None:
        res = client.get(f"/jobs/{ctx.obj}")
        stdout.print(JobWrapper(res.json()))


@scan.command(name="create", hidden=True)
@click.argument("repository")
@source_arg
@click.option("-q", "--quantity", type=int)
@opts.region_filter_opt
@opts.sync_opt
@opts.input_opt
@opts.env_opt
@opts.memory_opt
@opts.cpu_opt
@opts.image_opt
@opts.json_opt
def scan_create(
    repository: str,
    source: Source,
    sync: bool,
    region_filter: tuple[str],
    quantity: Optional[int],
    input: Optional[dict[str, list[str]]],
    env: Optional[dict[str, str]],
    cpu: Optional[int],
    memory: Optional[int],
    image: Optional[str],
    **kwargs,
):
    if source.type == "DIR":
        raise SatoriError("Directory sources are not compatible with scan")

    container_settings = {}

    if local_playbook := source.playbook:
        input = local_playbook.get_inputs_from_env(input)
        container_settings = remove_none_values(local_playbook.container_settings)

    container_settings.update(
        remove_none_values(
            {"cpu": cpu, "memory": memory, "image": image, "environment_variables": env}
        )
    )

    body = {
        "playbook_source": source.playbook_data(),
        "parameters": input,
        "regions": list(region_filter),
        "repository_data": {"repository": repository},
        "criteria": {"quantity": quantity},
        "environment_variables": env,
        "container_settings": remove_none_values(container_settings),
    }

    res = client.post("/jobs/scans", json=body)
    scan_job = res.json()

    stdout.print(JobWrapper(scan_job))

    if sync:
        wait_job_until_finished(scan_job["id"])


@scan.command(name="status")
@opts.json_opt
@click.pass_obj
def scan_status(scan_id: int, **kwargs):
    res = client.get(f"/jobs/{scan_id}")
    stdout.print(JobWrapper(res.json()))


@scan.command(name="stop")
@click.pass_obj
def scan_stop(scan_id: int):
    client.patch(f"/jobs/scans/{scan_id}", json={"status": "CANCELED"})
    stdout.print("Scan stopped")


@scan.command(name="clean")
@click.pass_obj
def scan_clean(scan_id: int):
    execution_ids: list[int] = []
    page = 1

    while True:
        res = client.get(
            "/executions",
            params={"job_id": scan_id, "quantity": 100, "page": page},
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


@scan.command(name="delete")
@click.pass_obj
def scan_delete(scan_id: int):
    client.delete(f"/jobs/{scan_id}")
    stdout.print("Scan deleted")
