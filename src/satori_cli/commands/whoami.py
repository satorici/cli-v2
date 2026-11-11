import rich_click as click
from httpx2 import HTTPStatusError

from ..api import client
from ..config import config
from ..utils.console import stdout


def _organization_label(organization) -> str:
    try:
        name = client.get(f"/organizations/{organization}").json()["name"]
    except HTTPStatusError:
        return str(organization)
    return f"{name} ({organization})"


@click.command("whoami")
def whoami():
    settings = client.get("/settings").json()
    configured = settings["github"]["token"]["configured"]
    pat_status = "configured" if configured else "not configured"
    profile = settings.get("profile") or {}
    stdout.print(f"Profile: {config.profile}")
    if name := profile.get("name"):
        stdout.print(f"Name: {name}")
    if email := profile.get("email"):
        stdout.print(f"Email: {email}")
    if organization := config.get("organization"):
        stdout.print(f"Organization: {_organization_label(organization)}")
    stdout.print(f"GitHub PAT: {pat_status}")
