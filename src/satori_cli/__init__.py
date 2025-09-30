import sys
from typing import Optional

import rich_click as click
from httpx import HTTPStatusError

from .auth import authenticate
from .commands.execution import execution
from .commands.job import job
from .commands.monitor import list_monitors, monitor
from .commands.report import report, reports
from .commands.run import run
from .commands.scan import list_scans, scan
from .commands.search import search
from .commands.stop import stop
from .config import config
from .constants import SATORI_HOME
from .exceptions import SatoriError
from .utils.console import stderr, stdout
from .utils.options import profile_opt


@click.group()
def cli():
    pass


@cli.command()
@profile_opt
def login(profile: str):
    credentials = authenticate()

    access_token = credentials["access_token"]
    refresh_token = credentials["refresh_token"]

    config.save("refresh_token", refresh_token, profile)

    profile_path = SATORI_HOME / f"{profile}"
    profile_path.mkdir(exist_ok=True)

    (profile_path / "access-token").write_text(access_token)

    stderr.print("Login succesful!")


@cli.command("config")
@click.argument("key", required=False)
@click.argument("value", required=False)
@profile_opt
def config_(key: Optional[str], value: Optional[str], **kwargs):
    if key is None:
        stdout.print(config)
        return

    if value is None:
        try:
            stdout.print(config[key])
        except KeyError:
            stderr.print(f"'{key}' not found in profile {kwargs['profile']}")
        return

    if key and value == "":
        stderr.print(f"'{key}' value must not be empty")
        sys.exit(1)

    config.save(key, value, kwargs["profile"])


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


def main():
    try:
        cli()
        return
    except HTTPStatusError as e:
        stderr.print_json(e.response.text)
    except SatoriError as e:
        stderr.print("ERROR:", e)

    return 1
