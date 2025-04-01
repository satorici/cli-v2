from collections import defaultdict

import click

from ..config import config
from ..models import Playbook


def _input_callback(ctx, name, inputs: tuple[str]):
    if inputs:
        parameters = defaultdict(list)

        for input in inputs:
            k, v = input.split("=", 1)

            parameters[k].extend(v.splitlines())

        return dict(parameters)


def _env_callback(ctx, name, envs):
    if envs:
        return {k: v for k, v in envs}


def _json_callback(ctx, name, json_):
    config["json"] = json_
    return json_


def _playbook_callback(ctx, name, value):
    if value:
        return Playbook(value)


input_opt = click.option(
    "--data", "-d", "input", multiple=True, callback=_input_callback
)
env_opt = click.option(
    "--env", "-e", type=(str, str), multiple=True, callback=_env_callback
)
region_filter_opt = click.option("--region-filter", "-r", multiple=True)
sync_opt = click.option("--sync", "-s", is_flag=True, default=False)
profile_opt = click.option("--profile", default="default")
cpu_opt = click.option("--cpu", type=int)
memory_opt = click.option("--memory", type=int)
image_opt = click.option("--image")
json_opt = click.option(
    "--json", "json_", is_flag=True, default=False, callback=_json_callback
)
playbook_opt = click.option("--playbook", callback=_playbook_callback)
