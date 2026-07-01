import sys

import rich_click as click

from ..api import client
from ..utils import options as opts
from ..utils.console import show_execution_output

execution_id_arg = click.argument("execution-id", type=int)


@click.command()
@execution_id_arg
@click.option("--raw", help="Pipe encoded results to stdout", is_flag=True)
@click.option("--test", "filter_tests", multiple=True)
@opts.format_opt
def output(execution_id: int, raw: bool, filter_tests: tuple[str, ...], **kwargs):
    if raw:
        with client.stream(
            "GET",
            f"/executions/{execution_id}/output",
            follow_redirects=True,
            timeout=None,
        ) as stream:
            for b in stream.iter_bytes():
                sys.stdout.buffer.write(b)

        return

    show_execution_output(
        execution_id, filter_tests=list(filter_tests) or None
    )
