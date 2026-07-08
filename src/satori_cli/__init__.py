import json
import time
from contextlib import suppress
from datetime import datetime
from importlib.metadata import distribution, version
from typing import Optional

import rich_click as click
from httpx import HTTPStatusError

from .commands.config import config_
from .commands.execution import execution
from .commands.job import job, jobs
from .commands.local import local
from .commands.monitor import list_monitors, monitor
from .commands.output import output
from .commands.playbook import playbook, playbooks
from .commands.report import report, reports
from .commands.run import run
from .commands.scan import list_scans, scan
from .commands.search import search
from .commands.shards import shards
from .commands.shell import shell
from .commands.stop import stop
from .commands.update import update
from .exceptions import SatoriError
from .utils import options as opts
from .utils.console import stderr
from .utils.misc import list_jobs

PACKAGE_NAME = "satori-cli"
VERSION = version(PACKAGE_NAME)


def _get_installed_commit() -> str | None:
    with suppress(Exception):
        dist = distribution(PACKAGE_NAME)

        if text := dist.read_text("direct_url.json"):
            data = json.loads(text)
            return data.get("vcs_info", {}).get("commit_id")
    return None


@click.group(invoke_without_command=True)
@click.option("--page", default=1)
@click.option("--quantity", default=10)
@click.option("--public", "visibility", flag_value="PUBLIC")
@opts.output_format_opts
@click.pass_context
def cli(
    ctx,
    page: int,
    quantity: int,
    visibility: Optional[str],
    **kwargs,
):
    if ctx.invoked_subcommand is None:
        list_jobs(page, quantity, None, visibility)


cli.add_command(config_)
cli.add_command(local)
cli.add_command(run)
cli.add_command(scan)
cli.add_command(list_scans)
cli.add_command(playbooks)
cli.add_command(playbook)
cli.add_command(monitor)
cli.add_command(list_monitors)
cli.add_command(jobs)
cli.add_command(job)
cli.add_command(execution)
cli.add_command(reports)
cli.add_command(report)
cli.add_command(stop)
cli.add_command(search)
cli.add_command(shards)
cli.add_command(update)
cli.add_command(output)
cli.add_command(shell)


def main():
    now = datetime.fromtimestamp(int(time.time()))
    full_version = VERSION

    if commit_sha := _get_installed_commit():
        full_version += f" {commit_sha[:7]}"

    stderr.print(f"Satori CLI {full_version} - Started on {now}")

    try:
        cli()
        return
    except HTTPStatusError as e:
        stderr.print_json(e.response.text)
    except SatoriError as e:
        stderr.print("ERROR:", e)

    return 1
