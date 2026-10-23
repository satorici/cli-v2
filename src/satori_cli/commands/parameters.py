from urllib.parse import quote

import rich_click as click
from rich.table import Table

from ..api import client
from ..utils.console import stdout


@click.group()
def parameters():
    """Saved parameters, applied to every job you create. `-d` values win over them."""


@parameters.command(name="list")
def list_parameters():
    """List saved parameters"""
    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Values")
    for param in client.get("/settings/parameters").json():
        table.add_row(param["name"], ",".join(param["values"]))
    stdout.print(table)


@parameters.command(name="set")
@click.argument("name")
@click.argument("values", nargs=-1, required=True)
def set_parameter(name: str, values: tuple[str, ...]):
    """Save NAME with one or more VALUES, replacing its previous values"""
    client.put(f"/settings/parameters/{quote(name, safe='')}", json={"values": values})
    stdout.print(f"{name} saved")


@parameters.command(name="unset")
@click.argument("name")
def unset_parameter(name: str):
    """Delete the saved parameter NAME"""
    client.delete(f"/settings/parameters/{quote(name, safe='')}")
    stdout.print(f"{name} deleted")
