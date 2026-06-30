import json

import rich_click as click

from ..config import config
from ..exceptions import SatoriError
from ..playbooks_api import client as playbooks_client
from ..utils import options as opts
from ..utils.console import stdout
from ..utils.wrappers import PlaybookCatalogWrapper, PlaybookDetailWrapper


@click.command("playbooks")
@opts.json_opt
def playbooks(**kwargs):
    res = playbooks_client.get("/playbooks")
    data = res.json()
    if config.get("json"):
        stdout.out(json.dumps(data["playbooks"], indent=2))
    else:
        stdout.print(PlaybookCatalogWrapper(data))


@click.group(invoke_without_command=True)
@click.argument("uri")
@opts.json_opt
@click.pass_context
def playbook(ctx, uri: str, **kwargs):
    if ctx.invoked_subcommand is None:
        if not uri.startswith("satori://"):
            raise SatoriError("Playbook URI must start with satori://")
        playbook_id = uri.removeprefix("satori://")
        res = playbooks_client.get(f"/playbooks/{playbook_id}")
        stdout.print(PlaybookDetailWrapper(res.json()))
