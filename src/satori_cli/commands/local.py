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
from ..utils.console import format_raw_results, stdout
from ..utils.execution.runner import TimedOut, process_commands
from ..utils.wrappers import JobWrapper


@click.command()
@source_arg
@opts.playbook_opt
@opts.input_opt
@click.option("--timeout", type=int)
@click.option("--run", multiple=True)
@opts.visibility_opt
@click.option("--tag", "-t", "tags", multiple=True, type=(str, str))
@click.option("--output", "-o", "show_output", is_flag=True)
def local(
    source: Source,
    playbook: Optional[Playbook],
    input: Optional[dict[str, list[str]]],
    timeout: Optional[int],
    run: Optional[tuple[str]],
    visibility: Optional[str],
    tags: Optional[tuple[tuple[str, str]]],
    show_output: bool,
    **kwargs,
):
    playbook_data = playbook.playbook_data() if playbook else source.playbook_data()

    if tags:
        tags_obj = {k: v for k, v in tags}
    else:
        tags_obj = {}

    body = {
        "playbook_source": playbook_data,
        "parameters": input,
        "visibility": visibility or "PRIVATE",
        "tags": tags_obj,
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

        try:
            asyncio.run(execute())
        except TimedOut:
            stdout.print("Execution timed out")

        results.seek(0)

        results_upload = local["results_upload"]

        res = httpx.post(
            results_upload["url"],
            data=results_upload["fields"],
            files={"file": results},
        )
        res.raise_for_status()

        if show_output:
            results.seek(0)
            format_raw_results(results)
