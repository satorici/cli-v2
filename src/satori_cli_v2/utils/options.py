from collections import defaultdict

import click


def _input_callback(ctx, name, inputs):
    if inputs:
        parameters = defaultdict(list)

        for k, v in inputs:
            parameters[k].append(v)

        return dict(parameters)


input_opt = click.option(
    "--input", "-i", type=(str, str), multiple=True, callback=_input_callback
)
region_filter_opt = click.option("--region-filter", "-r", multiple=True)
sync_opt = click.option("--sync", "-s", is_flag=True, default=False)
