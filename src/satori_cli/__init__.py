import time
from datetime import datetime
from importlib.metadata import distribution, version

import rich_click as click
from httpx import HTTPStatusError

from .commands.config import config_
from .commands.execution import execution
from .commands.job import job
from .commands.local import local
from .commands.monitor import list_monitors, monitor
from .commands.report import report, reports
from .commands.run import run
from .commands.scan import list_scans, scan
from .commands.search import search
from .commands.stop import stop
from .commands.update import update
from .exceptions import SatoriError
from .utils.console import stderr

PACKAGE_NAME = "satori-cli"
VERSION = version(PACKAGE_NAME)


def get_installed_commit():
    try:
        dist = distribution(PACKAGE_NAME)

        if text := dist.read_text("direct_url.json"):
            import json

            data = json.loads(text)

            return data.get("vcs_info", {}).get("commit_id")
    except Exception:
        pass


@click.group()
def cli():
    pass


cli.add_command(config_)
cli.add_command(local)
cli.add_command(run)
cli.add_command(scan)
cli.add_command(list_scans)
cli.add_command(monitor)
cli.add_command(list_monitors)
cli.add_command(job)
cli.add_command(execution)
cli.add_command(reports)
cli.add_command(report)
cli.add_command(stop)
cli.add_command(search)
cli.add_command(update)


def main():
    now = datetime.fromtimestamp(int(time.time()))
    full_version = VERSION

    if commit_sha := get_installed_commit():
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
