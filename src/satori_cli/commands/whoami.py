import rich_click as click

from ..api import client
from ..config import config
from ..utils.console import stdout


@click.command("whoami")
def whoami():
    settings = client.get("/settings").json()
    configured = settings["github"]["token"]["configured"]
    pat_status = "configured" if configured else "not configured"
    stdout.print(f"Profile: {config.profile}")
    if organization := config.get("organization"):
        stdout.print(f"Organization: {organization}")
    stdout.print(f"GitHub PAT: {pat_status}")
