import sys

import rich_click as click
from rich.table import Table

from ..api import client
from ..utils.console import stdout
from ..utils.options import saved_repo_opt


def _params(repository: str | None) -> dict:
    return {"repository": repository} if repository else {}


@click.group()
def secrets():
    """Saved secrets, set as environment variables of every job you create (not
    LOCAL), or with --repo of that repository's runs and scans. Values are
    write-only and visible to any playbook you run."""


@secrets.command(name="list")
@saved_repo_opt
def list_secrets(repository: str | None):
    """List saved secret names"""
    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Saved at")
    for secret in client.get("/settings/secrets", params=_params(repository)).json():
        table.add_row(secret["name"], secret["created_at"])
    stdout.print(table)


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _read_value() -> str:
    # Never an argument, so it stays out of the shell history
    if _stdin_is_tty():
        return click.prompt("Value", hide_input=True)
    return sys.stdin.read().removesuffix("\n")


@secrets.command(name="set")
@click.argument("name")
@saved_repo_opt
def set_secret(name: str, repository: str | None):
    """Save the secret NAME, prompting for its value or reading it from stdin"""
    value = _read_value()
    if not value:
        raise click.UsageError("The secret value must not be empty")
    client.put(
        f"/settings/secrets/{name}",
        json={"value": value},
        params=_params(repository),
    )
    stdout.print(f"{name} saved")


@secrets.command(name="unset")
@click.argument("name")
@saved_repo_opt
def unset_secret(name: str, repository: str | None):
    """Delete the saved secret NAME"""
    client.delete(f"/settings/secrets/{name}", params=_params(repository))
    stdout.print(f"{name} deleted")
