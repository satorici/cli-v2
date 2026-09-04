from collections import defaultdict

import click

from ..config import config
from ..models import Playbook


def _input_callback(ctx, name, inputs: tuple[str]):
    if inputs:
        parameters = defaultdict(list)

        for input in inputs:
            if "=" not in input:
                raise click.BadParameter(
                    f"invalid format '{input}', expected KEY=VALUE"
                )

            k, v = input.split("=", 1)

            parameters[k].extend(v.splitlines())

        return dict(parameters)


def _split_callback(ctx, name, splits: tuple[str]):
    if splits:
        result = {}

        for split in splits:
            if "=" not in split:
                raise click.BadParameter(
                    f"invalid format '{split}', expected KEY=DELIMITER"
                )

            k, v = split.split("=", 1)
            result[k] = v

        return result


def apply_splits(
    parameters: dict[str, list[str]] | None,
    splits: dict[str, str] | None,
) -> dict[str, list[str]] | None:
    if not parameters or not splits:
        return parameters

    result = dict(parameters)

    for key, delimiter in splits.items():
        if key not in result:
            continue

        values = []
        for value in result[key]:
            values.extend(part for part in value.split(delimiter) if part)

        result[key] = values

    return result


def _env_callback(ctx, name, envs):
    if envs:
        return {k: v for k, v in envs}


def _json_callback(ctx, name, json_):
    config["json"] = json_
    if json_:
        config["format"] = "json"
    return json_


def _format_callback(ctx, name, value):
    if value:
        config["format"] = value
    return value


def _playbook_callback(ctx, name, value):
    if value:
        return Playbook(value)


input_opt = click.option(
    "--data", "-d", "input", multiple=True, callback=_input_callback
)
split_opt = click.option(
    "--split", "split", multiple=True, callback=_split_callback
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
format_opt = click.option(
    "--format",
    type=click.Choice(["json", "md"], case_sensitive=False),
    default=None,
    callback=_format_callback,
)


def output_format_opts(fn):
    fn = format_opt(fn)
    fn = json_opt(fn)
    return fn


page_opt = click.option("--page", default=1, type=int)
quantity_opt = click.option("--quantity", "-q", "--limit", "-l", default=10, type=int)


def pagination_opts(fn):
    fn = quantity_opt(fn)
    fn = page_opt(fn)
    return fn


playbook_opt = click.option("--playbook", "-p", callback=_playbook_callback)
visibility_opt = click.option(
    "--visibility",
    type=click.Choice(["PUBLIC", "PRIVATE", "UNLISTED"], case_sensitive=False),
)
