import rich_click as click

from ..utils.console import show_execution_output

execution_id_arg = click.argument("execution-id", type=int)


@click.command()
@execution_id_arg
def output(execution_id: int):
    show_execution_output(execution_id)
