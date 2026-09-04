import json

import rich_click as click

from ..api import client
from ..exceptions import SatoriError
from ..playbooks_api import client as playbooks_client
from ..utils import options as opts
from ..utils.console import stdout
from ..utils.format import is_json_output
from ..utils.wrappers import PlaybookCatalogWrapper, PlaybookDetailWrapper


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
        if execution_id_or_uri.isdigit():
            execution = client.get(f"/executions/{execution_id_or_uri}").json()
            source = execution["job"]["playbook_source"]
            if not source.startswith("satori://"):
                raise SatoriError("Job playbook is not a public playbook")
            playbook_id = source.removeprefix("satori://")
        elif execution_id_or_uri.startswith("satori://"):
            playbook_id = execution_id_or_uri.removeprefix("satori://")
        else:
            raise SatoriError(
                "Argument must be an execution ID or a playbook URI starting with satori://"
            )

        res = playbooks_client.get(f"/playbooks/{playbook_id}")
        stdout.print(PlaybookDetailWrapper(res.json()))
