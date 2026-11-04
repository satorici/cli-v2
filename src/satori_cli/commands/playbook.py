import json

import rich_click as click

from ..api import client
from ..exceptions import SatoriError
from ..playbooks_api import client as playbooks_client
from ..utils import options as opts
from ..utils.console import stdout
from ..utils.format import is_json_output
from ..utils.wrappers import PlaybookCatalogWrapper, PlaybookDetailWrapper
from ..utils.public_id import is_public_id


@click.command("playbooks")
@opts.json_opt
def playbooks(**kwargs):
    res = playbooks_client.get("/playbooks")
    data = res.json()
    if is_json_output():
        stdout.out(json.dumps(data["playbooks"], indent=2))
    else:
        stdout.print(PlaybookCatalogWrapper(data))


@click.group(invoke_without_command=True)
@click.argument("execution_id_or_uri")
@opts.json_opt
@click.pass_context
def playbook(ctx, execution_id_or_uri: str, **kwargs):
    if ctx.invoked_subcommand is None:
        if is_public_id(execution_id_or_uri):
            res = client.get(f"/executions/{execution_id_or_uri}/playbook")
            stdout.out(res.text)
            return

        if not execution_id_or_uri.startswith("satori://"):
            raise SatoriError(
                "Argument must be an execution ID (21 letters and digits) "
                "or a playbook URI starting with satori://"
            )

        playbook_id = execution_id_or_uri.removeprefix("satori://")
        res = playbooks_client.get(f"/playbooks/{playbook_id}")
        stdout.print(PlaybookDetailWrapper(res.json()))
