import asyncio
from tempfile import SpooledTemporaryFile
from typing import Optional

import httpx
import msgpack
import rich_click as click

from ..api import client
from ..models import Playbook
from ..utils import options as opts
from ..utils.arguments import Source, source_arg
from ..utils.console import stdout
from ..utils.execution.runner import process_commands
from ..utils.wrappers import JobWrapper


@click.command()
@source_arg
@opts.playbook_opt
@opts.input_opt
@click.option("--timeout", type=int)
@click.option("--run", multiple=True)
def local(
    source: Source,
    playbook: Optional[Playbook],
    input: Optional[dict[str, list[str]]],
    timeout: Optional[int],
    run: Optional[tuple[str]],
    **kwargs,
):
    playbook_data = playbook.playbook_data() if playbook else source.playbook_data()

    body = {
        "playbook_source": playbook_data,
        "parameters": input,
    }

    local = client.post("/jobs/locals", json=body).json()

    stdout.print(JobWrapper(local))

    with SpooledTemporaryFile() as recipe, SpooledTemporaryFile() as results:
        res = httpx.get(local["recipe_url"])
        recipe.write(res.content)
        recipe.seek(0)

        unpacked = msgpack.Unpacker(recipe)

        if run:
            unpacked = (cline for cline in unpacked if cline["path"].startswith(run))

        settings = httpx.get(local["settings_url"]).json()

        async def execute():
            async for cline, result in process_commands(unpacked, settings, timeout):
                msgpack.pack(cline | {"output": result}, results)

        asyncio.run(execute())

        results.seek(0)

        client.put(f"/jobs/locals/{local['id']}", files={"results": results})
