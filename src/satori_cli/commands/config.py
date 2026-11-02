import sys
from typing import Optional

import rich_click as click
from httpx2 import HTTPStatusError

from ..api import client
from ..config import config
from ..utils.console import stderr, stdout
from ..utils.options import profile_opt, resolve_organization


@click.command("config")
@click.argument("key", required=False)
@click.argument("value", required=False)
@profile_opt
def config_(key: Optional[str], value: Optional[str], **kwargs):
    if key is None:
        stdout.print(config)
        return

    if key == "organization" and value is None:
        _show_organization(kwargs["profile"])
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

    if key == "pat":
        client.patch("/settings", json={"github": {"token": value}})
        stdout.print("Github PAT updated")
        return

    if key == "organization":
        if value.lower() in ("none", "personal"):
            config.save(key, "null", kwargs["profile"])
            stdout.print("Using your own account")
            return
        organization_id = resolve_organization(value)
        # check the membership on your own account, not on the saved organization
        config["organization"] = None
        org = client.get(f"/organizations/{organization_id}").json()
        config.save(key, str(organization_id), kwargs["profile"])
        stdout.print(f"Using organization {organization_id} ({org['name']}) by default")
        return

    config.save(key, value, kwargs["profile"])
    stdout.print(f"{key} updated")


def _show_organization(profile: str):
    if not (organization_id := config.get("organization")):
        stdout.print("Using your own account")
        return
    # look it up on your own account, not scoped to the organization itself
    config["organization"] = None
    try:
        org = client.get(f"/organizations/{organization_id}").json()
    except HTTPStatusError:
        stdout.print(organization_id)
        stderr.print(f"Organization {organization_id} not found in profile {profile}")
        return
    stdout.print(f"{org['name']} ({organization_id})")
