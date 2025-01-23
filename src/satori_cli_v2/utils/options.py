from collections import defaultdict

import click


def _input_callback(ctx, name, inputs):
    if inputs:
        parameters = defaultdict(list)

        for k, v in inputs:
            parameters[k].append(v)

        return dict(parameters)


def _env_callback(ctx, name, envs):
    if envs:
        return {k: v for k, v in envs}


input_opt = click.option(
    "--data", "-d", "input", type=(str, str), multiple=True, callback=_input_callback
)
env_opt = click.option(
    "--env", "-e", type=(str, str), multiple=True, callback=_env_callback
)
region_filter_opt = click.option("--region-filter", "-r", multiple=True)
sync_opt = click.option("--sync", "-s", is_flag=True, default=False)
profile_opt = click.option("--profile", default="default")
