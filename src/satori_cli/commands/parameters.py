from urllib.parse import quote

import rich_click as click
from rich.table import Table

from ..api import client
from ..utils.console import stdout
from ..utils.options import saved_repo_opt


def _params(repository: str | None) -> dict:
    return {"repository": repository} if repository else {}


@click.group()
def parameters():
    """Saved parameters, applied to every job you create, or with --repo to that
    repository's runs and scans. `-d` values win over them."""


@parameters.command(name="list")
@saved_repo_opt
def list_parameters(repository: str | None):
    """List saved parameters"""
    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Values")
    res = client.get("/settings/parameters", params=_params(repository))
    for param in res.json():
        table.add_row(param["name"], ",".join(param["values"]))
    stdout.print(table)


@parameters.command(name="set")
@click.argument("name")
@click.argument("values", nargs=-1, required=True)
@saved_repo_opt
def set_parameter(name: str, values: tuple[str, ...], repository: str | None):
    """Save NAME with one or more VALUES, replacing its previous values"""
    client.put(
        f"/settings/parameters/{quote(name, safe='')}",
        json={"values": values},
        params=_params(repository),
    )
    stdout.print(f"{name} saved")


@parameters.command(name="unset")
@click.argument("name")
@saved_repo_opt
def unset_parameter(name: str, repository: str | None):
    """Delete the saved parameter NAME"""
    client.delete(
        f"/settings/parameters/{quote(name, safe='')}", params=_params(repository)
    )
    stdout.print(f"{name} deleted")
