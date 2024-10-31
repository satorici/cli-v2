import rich_click as click

from .auth import authenticate
from .commands.execution import execution
from .commands.monitor import monitor
from .commands.run import run
from .commands.scan import scan
from .commands.job import job
from .constants import SATORI_HOME


@click.group()
def cli():
    pass


@cli.command()
def login():
    credentials = authenticate()

    access_token = credentials["access_token"]
    refresh_token = credentials["refresh_token"]

    (SATORI_HOME / "refresh-token").write_text(refresh_token)
    (SATORI_HOME / "access-token").write_text(access_token)


cli.add_command(run)
cli.add_command(scan)
cli.add_command(monitor)
cli.add_command(job)
cli.add_command(execution)


def main():
    cli()
